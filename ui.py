"""
TrailOps — Terminal MVP UI

Collects trip parameters via a Claude-powered conversation,
validates them, then hands off to the Orchestrator.

Swap this file for Streamlit post-MVP without touching any agent code.
"""

import json
import sys
import textwrap
from datetime import date

# Ensure UTF-8 output on Windows (handles em-dashes, smart quotes in Claude responses)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import json as _json
from pathlib import Path

import anthropic

from tools.base import CONFIG

_client = anthropic.Anthropic()
_MODEL       = CONFIG["claude"]["model"]        # sonnet — brief rendering
_HAIKU_MODEL = CONFIG["claude"]["haiku_model"]  # haiku — intake, Q&A, classification
_ROUTES_PATH = Path(__file__).parent / "data" / "routes.json"

_BRIEF_RENDER_SYSTEM = """\
You are the output renderer for TrailOps, a Pacific Northwest hiking trip planner.

You receive a trip brief as JSON and render it as clean, readable plain text \
suitable for printing or pasting into any document.

Rules:
- Plain text only. No markdown whatsoever: no **, no *, no #, no bullet hyphens, \
  no > blockquotes, no backticks, no code fences.
- Section labels on their own line, followed by a colon or in plain caps.
- Use a row of dashes (---) or equals signs (===) as section dividers if helpful.
- Write in a warm, conversational tone — like a knowledgeable friend briefing you.
- Include EVERY piece of data from the brief. Do not skip or summarize fields. \
  All dates, distances, elevations, and place names must appear verbatim.
- For the itinerary, list each day on its own line with its date, risk level, \
  waypoints, mileage, elevation gain, highlights, water sources, and camp.

Follow this structure exactly:

  YOUR TRIP BRIEF
  ============================================================
  [Opening sentence: route name, trip length as "X-day", difficulty, route type, region]
  [Second sentence: total miles and elevation gain]

  [Route description if present]

  [Permit and parking info as one or two natural sentences]

  [Days-adjusted note as a natural sentence, only if present in brief]

  ------------------------------------------------------------
  Overall risk: [level]  |  Main concern: [dominant factor]
  ------------------------------------------------------------

  [Conditions summary paragraph]

  Itinerary — [avg mi/day] mi/day average

    Day N (date)  [RISK LEVEL]   start waypoint to end waypoint   X mi  +Y ft
    Highlights: ...
    Water: [list sources from water_sources; if empty, write "carry sufficient water"]
    Camp: ...

  [Itinerary summary paragraph]

  What to Pack
    Must-have: [item (reason), item (reason)]
    Recommended: [items]
    Nice to have: [items]

  [Gear notes paragraph if present]

  [Plan B section only if status is plan_b — explain original route was replaced, \
   name the alternate route and why it was chosen]

  ============================================================
"""


_TYPICAL_MPD = {"Easy": 8.0, "Moderate": 10.0, "Hard": 12.0, "Epic": 16.0}


def _typical_days(r: dict) -> int:
    return max(1, round(r["total_miles"] / _TYPICAL_MPD.get(r["difficulty"], 10.0)))


def _build_system() -> str:
    """Build intake system prompt, injecting available route names for direct search."""
    routes = _json.load(open(_ROUTES_PATH))["routes"]
    route_list = "\n".join(
        f'  - {r["id"]}: "{r["name"]}" ({r["difficulty"]}, {r["route_type"]}, {r["sub_region"]}, typical {_typical_days(r)} days)'
        for r in routes
    )
    today = date.today().isoformat()
    return f"""\
TODAY'S DATE: {today}  ← use this as your reference when inferring dates. All trip dates must be on or after today.


You are the intake agent for TrailOps, an outdoor route planning system for the Pacific Northwest.

Your job: have a short conversation with the hiker to collect their trip parameters, \
then return a structured JSON object when you have everything you need.

DIRECT ROUTE SEARCH:
If the user mentions a specific trail or destination by name AND it clearly matches one of \
the routes in the list below (same trail name, obvious alias, or common short form), \
include its "route_id" in your output. \
Do NOT match a different trail just because it's in the same region or has similar difficulty — \
if the user's trail is not in the list, leave route_id null and set requested_trail instead. \
When route_id is set, difficulty and route_type are derived automatically. \
Use the route's "typical N days" as trip_length_days — do NOT ask the user how many days. \
Only ask for dates if missing.

Available routes:
{route_list}

STANDARD MODE (no specific route named):
Required fields (you MUST collect these):
- dates: start and end date of the trip (YYYY-MM-DD format)
- difficulty: one of Easy, Moderate, Hard, Epic
  - Easy: 8-10 mi/day, minimal elevation
  - Moderate: 10-12 mi/day, moderate elevation
  - Hard: 12-16 mi/day, high elevation gain
  - Epic: 16+ mi/day, maximum challenge
- trip_length_days: number of days (default 1 if not stated)

Optional fields:
- sub_region: one of North Cascades, South Cascades, Central Cascades, Olympics, Eastern Cascades

Rules:
- Ask only ONE follow-up question at a time if something is missing.
- If the user names a specific trail (whether or not it is in the list above), NEVER ask for difficulty, route_type, or trip length. For known routes, derive these from the route data. For unknown trails, leave them null — they are generated automatically. Only ask for dates if missing.
- Apply defaults silently: trip_length_days=1. Never ask about route_type.
- Only set route_type if the user explicitly mentions it (e.g. "I want a loop", "point-to-point"). \
  Otherwise leave it null.
- Derive season from dates — do not ask for it.
- Infer approximate dates silently from vague expressions — do NOT ask for specifics:
    "early <month>" → 1st–10th → use the 5th
    "mid <month>" → 11th–20th → use the 15th
    "late <month>" → 21st–end → use the 25th
    "next weekend" → nearest upcoming Saturday + Sunday
    Use TODAY'S DATE above to determine the correct year. If the month/day is already past \
    in the current year, use next year. Never produce a date before today. \
    Acknowledge the assumption in a brief follow-up message, \
    then immediately output the JSON.
- Write in plain conversational prose. Do not use markdown: no bold (**), no italics (*), \
  no bullet points, no headers. Just natural sentences.
- Once you have all required fields, output ONLY a JSON object with this exact structure \
  and nothing else:

Standard output (no specific route named):
{{
  "dates": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}},
  "difficulty": "Easy|Moderate|Hard|Epic",
  "trip_length_days": 1,
  "route_type": "thru|out-and-back|loop",
  "sub_region": null,
  "route_id": null,
  "requested_trail": null
}}

Direct route output (specific trail named and found in list above):
{{
  "dates": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}},
  "difficulty": null,
  "trip_length_days": 3,
  "route_type": null,
  "sub_region": null,
  "route_id": "<id from route list above>",
  "requested_trail": "<exact trail name the user mentioned>"
}}
Note: trip_length_days must be an integer — use the route's "typical N days" value from the route list.

Unknown trail output (trail named but NOT in list above):
{{
  "dates": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}},
  "difficulty": null,
  "trip_length_days": 1,
  "route_type": null,
  "sub_region": null,
  "route_id": null,
  "requested_trail": "<exact trail name the user mentioned>"
}}

Do not include any explanation or text outside the JSON when returning the final result.
"""


def collect_user_input() -> dict:
    """
    Run the intake conversation loop.
    Returns validated user_input dict when all required fields are collected.
    """
    print("\n=== TrailOps — Pacific Northwest Route Planner ===")
    print("Hey, tell me about your trip. (Type 'quit' to exit)\n")

    system = _build_system()
    messages = []

    while True:
        user_text = input("You: ").strip()

        if user_text.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            sys.exit(0)

        if not user_text:
            continue

        messages.append({"role": "user", "content": user_text})

        response = _client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=512,
            system=system,
            messages=messages,
        )

        assistant_text = response.content[0].text
        messages.append({"role": "assistant", "content": assistant_text})

        # Check if Claude returned the final JSON
        parsed = _try_parse_json(assistant_text)
        if parsed and _is_valid_input(parsed):
            print(f"\nTrailOps: Got it. Planning your trip...\n")
            return parsed

        # Otherwise print Claude's follow-up question
        print(f"\nTrailOps: {assistant_text}\n")



def render_brief(brief: dict) -> None:
    """Print the trip brief to the terminal."""
    status = brief.get("status", "ok")

    if status == "no_route_found":
        print("\nHmm, we couldn't find a route that fits those parameters.")
        msg = brief.get("message", "")
        if msg:
            print(msg)
        steps = brief.get("suggested_next_steps", [])
        if steps:
            print("\nA few things to try:")
            for step in steps:
                print(f"  - {step}")
        return

    if status == "no_viable_route":
        nvr = brief.get("no_viable_route", {})
        print("\nAfter checking all the options, we can't recommend a route right now.")
        overall = nvr.get("overall_risk", "")
        dominant = nvr.get("dominant_factor", "")
        if overall and dominant:
            print(f"Risk came in at {overall.upper()} with {dominant} as the main concern.")
        elif overall:
            print(f"Risk level: {overall.upper()}")
        if nvr.get("route_attempted"):
            print(f"We evaluated {nvr['route_attempted']} and couldn't make it work safely.")
        if nvr.get("conditions_summary"):
            print(f"\n{nvr['conditions_summary']}")
        tried = nvr.get("what_was_tried", [])
        if tried:
            print("\nHere's what we tried:")
            for item in tried:
                print(f"  - {item}")
        steps = nvr.get("suggested_next_steps", [])
        if steps:
            print("\nNext steps:")
            for step in steps:
                print(f"  - {step}")
        return

    # Normal brief — let Claude render it as clean formatted prose
    # Strip reasoning_trace from the render payload (large, not useful for display)
    render_payload = {k: v for k, v in brief.items() if k != "reasoning_trace"}

    response = _client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=_BRIEF_RENDER_SYSTEM,
        messages=[{
            "role": "user",
            "content": json.dumps(render_payload, indent=2),
        }],
    )
    print()
    print(response.content[0].text)


def follow_up_loop(brief: dict) -> None:
    """
    Post-brief Q&A loop. The user can ask follow-up questions about the trip,
    conditions, gear, itinerary, or route. Claude has the full brief as context.
    """
    system = (
        "You are a knowledgeable trail advisor for TrailOps, an outdoor route planning system "
        "for the Pacific Northwest. The user has just received a trip brief and may have follow-up "
        "questions about the route, conditions, risk, gear, itinerary, or anything else related to their trip.\n\n"
        "Be conversational, warm, and concise. Write in plain prose — no markdown, no bullet points, "
        "no bold text. Answer from the trip brief data where possible. "
        "If asked about something not in the brief, draw on your knowledge of Pacific Northwest hiking.\n\n"
        f"TRIP BRIEF:\n{json.dumps(brief, indent=2)}"
    )

    print("\nGot any questions about the trip? Ask away. (Type 'quit' to exit)\n")
    messages = []

    while True:
        user_text = input("You: ").strip()

        if user_text.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            sys.exit(0)

        if not user_text:
            continue

        messages.append({"role": "user", "content": user_text})

        response = _client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=1024,
            system=system,
            messages=messages,
        )

        reply = response.content[0].text
        messages.append({"role": "assistant", "content": reply})
        print(f"\nTrailOps: {reply}\n")


def present_route_options(options: list, user_input: dict) -> dict:
    """
    Print a ranked options table and prompt the user to choose a route.
    Returns user_input with route_id (and difficulty/route_type) locked in.
    """
    if not options:
        return user_input

    trip_days     = options[0]["trip_days"]
    is_multi_day  = trip_days > 1
    days_adjusted = any(o.get("days_adjusted") for o in options)
    original_days = user_input.get("trip_length_days")

    print("\n" + "=" * 100)
    print("  Here are some routes that look like a good fit for your trip:")
    if days_adjusted and original_days and original_days != trip_days:
        print(f"  (No route fits exactly {original_days} day(s) at a comfortable pace — "
              f"showing options for {trip_days} day(s) instead)")
    print("=" * 100)

    def _permit_label(res: dict) -> str:
        if not res:
            return "Unknown"
        if not res.get("permit_required"):
            return "None"
        ptype = res.get("permit_type", "")
        if ptype == "lottery":
            return "Lottery!"
        if ptype == "advance":
            return "Advance"
        return "Required"

    if is_multi_day:
        print(f"  {'#':<3} {'Route':<36} {'Days':>4} {'Miles':>6} {'Gain':>10} {'Mi/Day':>7} {'Elev/Day':>9}  {'Permit':<10}  Fit")
        print(f"  {'---':<3} {'------':<36} {'----':>4} {'-----':>6} {'--------':>10} {'------':>7} {'--------':>9}  {'------':<10}  ---")
    else:
        print(f"  {'#':<3} {'Route':<36} {'Miles':>6} {'Gain':>10}  {'Permit':<10}  Fit")
        print(f"  {'---':<3} {'------':<36} {'-----':>6} {'--------':>10}  {'------':<10}  ---")

    # Fit column starts at this offset (spaces before the fit text on continuation lines)
    fit_indent_multi = " " * 97
    fit_indent_day   = " " * 74
    fit_wrap_width   = 55

    for opt in options:
        r      = opt["route"]
        name   = r["name"] if len(r["name"]) <= 36 else r["name"][:33] + "..."
        marker = "*" if opt["is_best"] else " "
        gain   = f"+{r['elevation_gain_ft']:,} ft"
        permit = _permit_label(opt.get("reservations", {}))
        fit_lines = textwrap.wrap(opt["rationale"], width=fit_wrap_width) or [""]

        if is_multi_day:
            print(
                f"  {marker}{opt['rank']:<2} {name:<36} {opt['trip_days']:>4} "
                f"{r['total_miles']:>6} {gain:>10} {opt['mi_per_day']:>7.1f} "
                f"{opt['elev_per_day']:>9,}  {permit:<10}  {fit_lines[0]}"
            )
            for line in fit_lines[1:]:
                print(fit_indent_multi + line)
        else:
            print(f"  {marker}{opt['rank']:<2} {name:<36} {r['total_miles']:>6} {gain:>10}  {permit:<10}  {fit_lines[0]}")
            for line in fit_lines[1:]:
                print(fit_indent_day + line)

    legend = "  * = recommended  |  Permit: None=no permit needed, Advance=reserve on Recreation.gov, Lottery!=competitive lottery"
    if is_multi_day:
        legend += "\n  Days = your planned trip length  |  Mi/Day & Elev/Day based on your trip length"
    print(f"\n{legend}")
    print("=" * 100)

    print("\nWhich one catches your eye?\n")
    while True:
        choice = input("You: ").strip()
        if choice.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            sys.exit(0)
        if not choice:
            continue
        idx = _interpret_route_selection(choice, options)
        if idx is not None:
            selected = options[idx]
            chosen   = selected["route"]
            user_input["route_id"]        = chosen["id"]
            user_input["difficulty"]      = chosen["difficulty"]
            user_input["route_type"]      = chosen["route_type"]
            user_input.pop("requested_trail", None)
            if selected.get("days_adjusted"):
                user_input["trip_length_days"] = selected["trip_days"]
            print(f"\nTrailOps: Great, let's plan {chosen['name']}.\n")
            return user_input
        print("\nTrailOps: Hmm, I didn't quite catch that — which route were you thinking?\n")


def _interpret_route_selection(user_text: str, options: list) -> int | None:
    """
    Use Claude to map a natural language route selection to an option index (0-based).
    Returns None if Claude can't determine which option the user meant.
    """
    import re as _re
    option_lines = "\n".join(
        f"{i+1}. {o['route']['name']} ({o['route']['difficulty']}, "
        f"{o['route']['route_type']}, {o['route']['sub_region']})"
        for i, o in enumerate(options)
    )
    response = _client.messages.create(
        model=_HAIKU_MODEL,
        max_tokens=5,
        system=(
            "The user was shown a list of hiking route options and is choosing one.\n"
            f"Options:\n{option_lines}\n\n"
            "Based on the user's message, reply with ONLY the option number (1, 2, 3, etc.). "
            "If you cannot determine which option they mean, reply with 0."
        ),
        messages=[{"role": "user", "content": user_text}],
    )
    text = response.content[0].text.strip()
    digits = _re.sub(r"\D", "", text)
    try:
        n = int(digits)
        if 1 <= n <= len(options):
            return n - 1
    except (ValueError, TypeError):
        pass
    return None


def _save_adhoc_route(route: dict) -> bool:
    """Append a Claude-generated route to routes.json, stripping internal metadata fields.

    Returns True if saved, False if a route with the same id already exists.
    """
    to_save = {k: v for k, v in route.items() if not k.startswith("_")}
    with open(_ROUTES_PATH) as f:
        data = _json.load(f)
    if any(r.get("id") == to_save.get("id") for r in data["routes"]):
        return False
    data["routes"].append(to_save)
    with open(_ROUTES_PATH, "w") as f:
        _json.dump(data, f, indent=2)
    print(f"\nTrailOps: Saved {to_save['name']} to your routes database.\n")
    return True


def _try_parse_json(text: str) -> dict | None:
    """Try to parse text as JSON. Returns None if not valid JSON.

    Handles: code fences, preamble prose before the JSON object.
    """
    import re
    # Strip code fences
    stripped = re.sub(r"```(?:json)?\s*", "", text).strip().strip("`").strip()
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass
    # Preamble before JSON — find first { and parse from there
    idx = stripped.find("{")
    if idx > 0:
        try:
            return json.loads(stripped[idx:])
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _is_valid_input(data: dict) -> bool:
    """Check that all required fields are present.

    Two valid paths:
    - Standard: dates + difficulty + trip_length_days + route_type
    - Direct route: dates + route_id (difficulty/route_type derived from route)
    """
    try:
        assert "dates" in data
        assert "start" in data["dates"] and "end" in data["dates"]
        # Accept int or float (Claude occasionally outputs 2.0 instead of 2)
        assert isinstance(data.get("trip_length_days"), (int, float))
        if data.get("route_id") or data.get("requested_trail"):
            return True  # named trail path: difficulty/route_type derived later
        assert data.get("difficulty") in ("Easy", "Moderate", "Hard", "Epic")
        assert data.get("route_type") in ("thru", "out-and-back", "loop", None)
        return True
    except (AssertionError, TypeError, KeyError):
        return False


if __name__ == "__main__":
    import orchestrator

    user_input = collect_user_input()

    if user_input.get("requested_trail") and not user_input.get("route_id"):
        # Unknown trail — skip options table, adhoc route generated inside orchestrator
        print(
            f"\nTrailOps: '{user_input['requested_trail']}' isn't in our database. "
            "Generating route data now...\n"
        )
    elif user_input.get("route_id"):
        # User named a specific trail — go straight to planning, no options table
        trail_name = user_input.get("requested_trail") or user_input["route_id"]
        print(f"\nTrailOps: Got it, planning {trail_name} now...\n")
    else:
        # Standard search — show ranked options table
        options    = orchestrator.get_route_options(user_input)
        user_input = present_route_options(options, user_input)

    brief = orchestrator.run(user_input)
    render_brief(brief)

    # If this was a Claude-generated route, show a disclaimer and offer to save
    if brief.get("route", {}).get("_adhoc"):
        route_name = brief["route"]["name"]
        print(
            "\nNote: waypoint coordinates for this route are approximate "
            "(generated from Claude's training knowledge, not GPS data)."
        )
        print(f"\nWant to save {route_name} to your routes database for future trips? (yes/no)")
        while True:
            ans = input("You: ").strip().lower()
            if ans in ("yes", "y"):
                _save_adhoc_route(brief["route"])
                break
            elif ans in ("no", "n", ""):
                break

    follow_up_loop(brief)
