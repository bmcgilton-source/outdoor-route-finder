"""
Replanner Sub-agent — adjusts the itinerary to reduce risk.

Spawned by Assessment Agent when overall_risk >= medium.
Max 1 attempt. Modifies trip_context["itinerary"] in place.

Strategy: adjust daily pacing, avoid high-risk days, shift mileage —
but stay on the SAME route. Does not change the route.
"""

import json
import re

import anthropic

from logger import get_logger
from tools.base import CONFIG

log = get_logger(__name__)

_client     = anthropic.Anthropic()
_MODEL      = CONFIG["claude"]["haiku_model"]
_MAX_TOKENS = CONFIG["claude"]["max_tokens"]

_SYSTEM = """\
You are the Replanner for TrailOps, an outdoor route planning system.

A hiking itinerary has been flagged as high or medium risk due to environmental conditions. \
Your job: adjust the day-by-day pacing to reduce exposure to the highest-risk days, \
while staying on the SAME route.

Tactics available:
- Shift mileage: front-load or back-load miles to avoid a bad weather day
- Adjust camp locations to reach shelter earlier on a risky day
- Add rest day buffer if trip_length allows
- Note days where hiker should start early (before afternoon thunderstorms, etc.)

You may NOT:
- Change the route (same start/end trailhead, same waypoints)
- Add more days than the original trip_length
- Remove a day
- Change or omit the "date" field on any day — preserve each day's exact YYYY-MM-DD date

Return the revised itinerary JSON with the SAME structure as the original, plus a \
"replanner_notes" field explaining what was changed and why.

Do not include any text outside the JSON object.
"""


def run(trip_context: dict) -> dict:
    """
    Attempt to replan the itinerary to reduce risk.

    Reads from trip_context: itinerary, conditions, risk, selected_route
    Writes to trip_context: itinerary (updated), reasoning_trace

    Returns: updated trip_context
    """
    log.info("Replanner: adjusting itinerary to reduce risk")
    trace = trip_context.setdefault("reasoning_trace", [])
    trace.append({"agent": "replanner", "event": "start"})

    route = trip_context["selected_route"]
    itinerary = trip_context["itinerary"]
    conditions = trip_context["conditions"]
    risk = trip_context["risk"]

    user_message = _build_user_message(route, itinerary, conditions, risk)

    response = _client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = _extract_text(response)
    revised = _parse_json(raw)

    if revised and not revised.get("_parse_error"):
        log.info("Replanner: itinerary adjusted successfully")
        trip_context["itinerary"] = revised
        trace.append({
            "agent": "replanner",
            "event": "complete",
            "replanner_notes": revised.get("replanner_notes", ""),
        })
    else:
        log.warning("Replanner: JSON parse failed — returning original itinerary")
        trace.append({"agent": "replanner", "event": "failed", "raw": raw[:200]})

    return trip_context


def _build_user_message(
    route: dict, itinerary: dict, conditions: dict, risk: dict
) -> str:
    return (
        f"Replan this itinerary to reduce risk.\n\n"
        f"Route: {route['name']} ({route['route_type']})\n\n"
        f"Current itinerary:\n{json.dumps(itinerary, indent=2)}\n\n"
        f"Risk assessment:\n{json.dumps(risk, indent=2)}\n\n"
        f"Conditions summary: {conditions.get('synthesis_notes', '')}\n\n"
        f"Weather details:\n{json.dumps(conditions.get('weather', {}), indent=2)}\n\n"
        "Adjust the itinerary to reduce exposure. Return revised JSON only."
    )


def _extract_text(response) -> str:
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return "{}"


def _parse_json(raw: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", raw).strip().strip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_parse_error": True, "_raw": raw}
