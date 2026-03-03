"""
Orchestrator — deterministic pipeline controller. Owns the Trip Context object.

Execution order:
  1. Validate structured input from UI
  2. Select route from routes.json
  3. Run Intelligence Agent + Day Planner in PARALLEL
  4. Run Assessment Agent (gear + risk + optional replanning)
  5. Assemble and return the final trip brief

The Orchestrator never makes Claude API calls directly.
It only moves data between agents and enforces pipeline order.
"""

import concurrent.futures
import json
import re
from datetime import date, timedelta
from pathlib import Path

import anthropic

from agents import assessment_agent, brief_reviewer, intelligence_agent
from agents import day_planner
from logger import get_logger
from tools.base import CONFIG

log = get_logger(__name__)

_claude = anthropic.Anthropic()
_MODEL = CONFIG["claude"]["model"]

_ROUTES_PATH = Path(__file__).parent / "data" / "routes.json"

_DIFFICULTY_MILES_PER_DAY = {
    "Easy": (8, 10),
    "Moderate": (10, 12),
    "Hard": (12, 16),
    "Epic": (16, 999),
}

# Lower-bound of each difficulty range — used to estimate "typical days" per route
_DIFFICULTY_TYPICAL_MPD = {
    "Easy": 8.0,
    "Moderate": 10.0,
    "Hard": 12.0,
    "Epic": 16.0,
}


def get_route_options(user_input: dict) -> list[dict]:
    """
    Return 3+ ranked route options for the user to choose from before the pipeline runs.

    Each option dict contains:
      - route:        the route dict from routes.json
      - rank:         1-based display position
      - is_best:      True for the top recommended option
      - trip_days:    day count used for per-day calculations (may differ from user request)
      - mi_per_day:   total_miles / trip_days
      - elev_per_day: elevation_gain_ft / trip_days
      - typical_days: natural days at difficulty pace (route-specific)
      - rationale:    why it's the best fit, or what trade-offs it has
      - days_adjusted: True if trip_days was shifted ±1 from the user's request
    """
    with open(_ROUTES_PATH) as f:
        all_routes = json.load(f)["routes"]

    _MIN_MPD = 5.0
    _MAX_MPD = 15.0

    route_id    = user_input.get("route_id")
    difficulty  = user_input.get("difficulty", "Moderate")
    route_type  = user_input.get("route_type") or None  # None = no preference
    sub_region  = user_input.get("sub_region")
    trip_days   = user_input.get("trip_length_days", 1)
    season_month = _month_from_date(user_input["dates"]["start"])

    # If a route_id is pinned, derive difficulty/route_type from it
    pinned_route = None
    if route_id:
        pinned_route = next((r for r in all_routes if r["id"] == route_id), None)
        if pinned_route:
            difficulty = pinned_route["difficulty"]
            route_type = pinned_route["route_type"]

    def _typical_days(r: dict) -> int:
        return max(1, round(r["total_miles"] / _DIFFICULTY_TYPICAL_MPD.get(r["difficulty"], 10.0)))

    def _score(r: dict, days: int) -> dict:
        diff_match   = r["difficulty"] == difficulty
        # type_match is None when user expressed no preference (no scoring penalty)
        type_match   = (r["route_type"] == route_type) if route_type else None
        region_match = bool(sub_region and r["sub_region"].lower() == sub_region.lower())
        in_season    = season_month in r.get("season", [])
        miles_ok     = _MIN_MPD <= r["total_miles"] / max(days, 1) <= _MAX_MPD
        # How close is the route's natural pace to the user's requested trip length?
        # 3 pts = exact match, 2 = ±1 day, 1 = ±2 days, 0 = more than 2 days off
        typ_days = _typical_days(r)
        days_fit = max(0, 3 - abs(typ_days - days))
        total = (
            int(diff_match)          * 4 +
            days_fit                 * 3 +  # trip-length proximity (replaces miles_ok * 1)
            int(in_season)           * 3 +
            int(bool(type_match))    * 2 +  # 0 when no preference
            int(region_match)        * 1 +
            int(miles_ok)            * 1
        )
        return {
            "diff_match": diff_match, "type_match": type_match,
            "region_match": region_match, "in_season": in_season,
            "miles_ok": miles_ok, "days_fit": days_fit, "typical_days": typ_days, "total": total,
        }

    def _rationale(r: dict, s: dict, is_best: bool, pinned: bool = False) -> str:
        if pinned:
            return "Your requested route — planning as specified"
        if is_best:
            parts = ["Best overall match for your criteria"]
            if s["in_season"]:
                parts.append("peak season access")
            else:
                parts.append("may have limited access for your dates")
            if s["region_match"] and sub_region:
                parts.append(f"in your preferred {sub_region} region")
            if s["type_match"]:
                parts.append(f"{r['route_type']} format as requested")
            return "; ".join(parts)
        # Non-best: call out pros and cons on each dimension
        pros, cons = [], []
        if s["diff_match"]:
            pros.append(f"matches your {difficulty} difficulty target")
        else:
            cons.append(f"rated {r['difficulty']} — not your requested {difficulty}")
        if s["type_match"] is True:
            pros.append(f"{r['route_type']} as requested")
        elif s["type_match"] is False:
            cons.append(f"{r['route_type']} format (you asked for {route_type})")
        if s["in_season"]:
            pros.append("in season")
        else:
            cons.append("likely off season for your dates")
        if sub_region:
            if s["region_match"]:
                pros.append(f"in {sub_region}")
            else:
                cons.append(f"located in {r['sub_region']} (not {sub_region})")
        if not s["miles_ok"]:
            mpd = r["total_miles"] / max(days_used, 1)
            cons.append(f"{mpd:.1f} mi/day falls outside the 5-15 mi/day window")
        day_diff = abs(s["typical_days"] - days_used)
        if day_diff >= 2:
            cons.append(f"typically a {s['typical_days']}-day trip (you asked for {days_used})")
        elif day_diff == 1:
            pros.append(f"typically {s['typical_days']} days — close to your {days_used}-day plan")
        segments = []
        if pros:
            segments.append("Pros: " + ", ".join(pros))
        if cons:
            segments.append("Cons: " + ", ".join(cons))
        return " | ".join(segments) if segments else "Alternative option"

    def _build_option(r, s, rank, is_best, days, pinned=False, days_adjusted=False):
        typical = s.get("typical_days") or _typical_days(r)
        res = r.get("reservations", {})
        return {
            "rank":          rank,
            "route":         r,
            "is_best":       is_best,
            "trip_days":     days,
            "mi_per_day":    round(r["total_miles"] / max(days, 1), 1),
            "elev_per_day":  round(r["elevation_gain_ft"] / max(days, 1)),
            "typical_days":  typical,
            "rationale":     _rationale(r, s, is_best, pinned),
            "days_adjusted": days_adjusted,
            "reservations":  res,
        }

    # --- Find candidates: exact days, then ±1 ---
    days_used     = trip_days
    days_adjusted = False

    def _candidates(days):
        return [r for r in all_routes
                if _MIN_MPD <= r["total_miles"] / max(days, 1) <= _MAX_MPD]

    pool = _candidates(trip_days)
    if not pool:
        for adj in [trip_days - 1, trip_days + 1]:
            if adj >= 1:
                pool = _candidates(adj)
                if pool:
                    days_used     = adj
                    days_adjusted = True
                    break
    if not pool:
        pool = list(all_routes)  # last resort: show everything

    # Score and sort the full pool
    scored = sorted(
        [(r, _score(r, days_used)) for r in pool],
        key=lambda x: x[1]["total"],
        reverse=True,
    )

    options = []

    if pinned_route:
        # Pinned route goes first; fill 2 alternatives from the scored pool
        ps = _score(pinned_route, days_used)
        options.append(_build_option(pinned_route, ps, 1, True, days_used,
                                     pinned=True, days_adjusted=days_adjusted))
        rank = 2
        for r, s in scored:
            if len(options) >= 3:
                break
            if r["id"] != route_id:
                options.append(_build_option(r, s, rank, False, days_used,
                                             days_adjusted=days_adjusted))
                rank += 1
    else:
        # Top 3 from difficulty-matched routes first
        diff_matched = [(r, s) for r, s in scored if s["diff_match"]]
        for i, (r, s) in enumerate(diff_matched[:3]):
            options.append(_build_option(r, s, i + 1, i == 0, days_used,
                                         days_adjusted=days_adjusted))
        # Fill remaining slots with best remaining routes (any difficulty)
        rank = len(options) + 1
        for r, s in scored:
            if len(options) >= 3:
                break
            if not any(o["route"]["id"] == r["id"] for o in options):
                options.append(_build_option(r, s, rank, False, days_used,
                                             days_adjusted=days_adjusted))
                rank += 1

    return options


def run(user_input: dict, progress_cb=None) -> dict:
    """
    Execute the full pipeline for a trip planning request.

    Args:
        user_input:   validated dict with trip parameters
        progress_cb:  optional callable(str) for live UI progress updates.
                      Called from the main thread only — NOT from worker threads.

    Returns:
        trip_brief dict (assembled from Trip Context)
    """
    def _cb(msg: str) -> None:
        log.debug(msg)
        print(msg, flush=True)
        if progress_cb:
            progress_cb(msg)
    # Initialize Trip Context
    trip_context = {
        "user_input": user_input,
        "selected_route": None,
        "conditions": {},
        "itinerary": {},
        "gear": [],
        "risk": {},
        "plan_b": None,
        "no_viable_route": None,
        "reasoning_trace": [],
    }

    trip_context["reasoning_trace"].append(
        {"agent": "orchestrator", "event": "start", "user_input": user_input}
    )

    # Step 1: Select route
    route = _select_route(user_input)
    if route is None:
        return _no_route_response(user_input)

    trip_context["selected_route"] = route
    log.info(f"Orchestrator: route selected — {route['name']} ({route['difficulty']}, {route['sub_region']})")
    trip_context["reasoning_trace"].append(
        {"agent": "orchestrator", "event": "route_selected", "route": route["id"]}
    )
    _cb(f"Route selected: {route['name']}  ·  {route['difficulty']}, {route['sub_region']}")

    # Step 2: Intelligence Agent + Day Planner in parallel
    # Note: these run in worker threads — progress_cb is NOT passed in to avoid
    # calling st.write() from a non-main thread.
    _cb("Fetching live weather, air quality, fire & water data…")
    trip_context = _run_parallel(trip_context)
    _cb("Conditions checked, day-by-day itinerary built")

    # Step 3: Assessment (gear + risk + optional replanning)
    trip_context = assessment_agent.run(trip_context, progress_cb=progress_cb)

    # Step 4: Assemble trip brief
    brief = _assemble_brief(trip_context)

    # Step 5: Final prose review — clean markdown artifacts, fix formatting
    _cb("Polishing the trip brief…")
    brief = brief_reviewer.run(brief)

    return brief


def _select_route(user_input: dict) -> dict | None:
    """
    Select the best matching route from routes.json.

    Matching priority:
      1. Difficulty match (required)
      2. Route type match (preferred)
      3. Sub-region match (preferred if provided)
      4. Trip length fit (miles/day within difficulty range)
    """
    with open(_ROUTES_PATH) as f:
        all_routes = json.load(f)["routes"]

    # Direct route lookup — user named a specific trail in our database
    route_id = user_input.get("route_id")
    if route_id:
        match = next((r for r in all_routes if r["id"] == route_id), None)
        if match:
            user_input.setdefault("difficulty", match["difficulty"])
            user_input.setdefault("route_type", match["route_type"])
            return match

    # Unknown trail — user named a trail not in our database; generate route data
    requested_trail = user_input.get("requested_trail")
    if requested_trail and not route_id:
        log.warning(f"Orchestrator: '{requested_trail}' not in database — generating ad-hoc route data")
        print(f"      -> '{requested_trail}' not in database — generating route data...", flush=True)
        generated = _generate_adhoc_route(requested_trail, user_input)
        if generated:
            user_input.setdefault("difficulty", generated["difficulty"])
            user_input.setdefault("route_type", generated["route_type"])
            return generated

    _MIN_MPD = 5.0
    _MAX_MPD = 15.0
    difficulty = user_input.get("difficulty", "Moderate")
    route_type = user_input.get("route_type") or None  # None = no preference
    sub_region = user_input.get("sub_region")
    trip_days = user_input.get("trip_length_days", 1)
    season_month = _month_from_date(user_input["dates"]["start"])

    def score(r: dict) -> tuple:
        diff_match = int(r["difficulty"] == difficulty)
        type_match = int(r["route_type"] == route_type) if route_type else 0
        region_match = int(bool(sub_region and r["sub_region"].lower() == sub_region.lower()))
        in_season = int(season_month in r.get("season", []))
        miles_ok = int(_miles_per_day_ok(r["total_miles"], trip_days, difficulty))
        return (diff_match, in_season, type_match, region_match, miles_ok)

    # Hard filter: 5–15 mi/day window. Keeps short routes from being stretched across too
    # many days and long routes from being crammed into too few days.
    # Falls back to ±1 day if no exact match exists.
    def _candidates_for_days(days: int) -> list:
        return [
            r for r in all_routes
            if r["difficulty"] == difficulty
            and _MIN_MPD <= r["total_miles"] / max(days, 1) <= _MAX_MPD
        ]

    candidates = _candidates_for_days(trip_days)

    if not candidates:
        # Try adjacent day counts before giving up
        for adjusted_days in [trip_days - 1, trip_days + 1]:
            if adjusted_days < 1:
                continue
            candidates = _candidates_for_days(adjusted_days)
            if candidates:
                log.info(f"Orchestrator: no exact {trip_days}-day fit — adjusting to {adjusted_days} day(s)")
                print(
                    f"  No route fits exactly {trip_days} days at a good pace — "
                    f"adjusting to {adjusted_days} day(s).",
                    flush=True,
                )
                user_input["trip_length_days"] = adjusted_days
                user_input["_days_adjusted"] = True
                user_input["_days_original"] = trip_days
                trip_days = adjusted_days
                break

    if not candidates:
        return None

    return max(candidates, key=score)


def _generate_adhoc_route(trail_name: str, user_input: dict) -> dict | None:
    """
    Ask Claude to generate approximate route data for a trail not in our database.
    Returns a route dict matching the routes.json schema, or None on failure.
    """
    system = """\
You are a Pacific Northwest hiking data assistant. When given a trail name, generate a \
route data object with approximate GPS coordinates based on your knowledge.

Return ONLY a valid JSON object matching this exact schema — no text outside the JSON:
{
  "id": "adhoc-<url-safe-slug>",
  "name": "<full official trail name>",
  "sub_region": "<one of: North Cascades, South Cascades, Central Cascades, Olympics, Eastern Cascades, Mt. Rainier>",
  "route_type": "<thru|out-and-back|loop>",
  "difficulty": "<Easy|Moderate|Hard|Epic>",
  "total_miles": <float>,
  "elevation_gain_ft": <int>,
  "description": "<2-3 sentence description of the trail character and highlights>",
  "season": ["<month names when trail is typically accessible>"],
  "trailhead": {"name": "<trailhead name>", "lat": <float>, "lon": <float>},
  "bounding_box": {"min_lat": <float>, "max_lat": <float>, "min_lon": <float>, "max_lon": <float>},
  "water_crossings": [{"name": "<creek/river name>", "lat": <float>, "lon": <float>}],
  "water_sources": [
    {"name": "<lake/tarn/spring/stream name>", "type": "<lake|tarn|spring|stream|river>", "cumulative_miles": <float>}
  ],
  "waypoints": [
    {"name": "<waypoint name>", "lat": <float>, "lon": <float>, "elevation_ft": <int>, "cumulative_miles": <float>}
  ],
  "reservations": {
    "permit_required": <true|false>,
    "permit_type": "<none|advance|lottery|self-issue>",
    "booking_system": <null or "Recreation.gov">,
    "parking_pass": "<Discover Pass|Northwest Forest Pass|National Park entrance fee|none>",
    "notes": "<1-2 sentences on permit and parking requirements>"
  }
}

Rules:
- Coordinates are approximate — use your best knowledge of the trail's actual location.
- waypoints: include trailhead, key junctions/camps/summits, and end point (4-6 waypoints typical).
  cumulative_miles must increase monotonically from 0.0 to total_miles.
- water_sources: list reliable filter points along the route with their approximate cumulative mile position.
  Include rivers/streams that parallel the trail, lakes at or near waypoints, and known springs.
  If no reliable sources exist on a segment, omit rather than fabricate.
- water_crossings: river/stream fords only (not lakes or springs).

If the trail is not in Washington state or is completely unknown to you, return {"error": "unknown"}.
"""
    dates = user_input.get("dates", {})
    response = _claude.messages.create(
        model=_MODEL,
        max_tokens=1500,
        system=system,
        messages=[{
            "role": "user",
            "content": (
                f"Generate route data for: {trail_name}\n"
                f"Trip dates: {dates.get('start', '')} to {dates.get('end', '')}"
            )
        }],
    )

    raw = next((b.text for b in response.content if hasattr(b, "text")), "{}")
    text = re.sub(r"```(?:json)?\s*", "", raw).strip().strip("`").strip()
    start = text.find("{")
    if start != -1:
        text = text[start:]
    try:
        data = json.loads(text)
        if data.get("error") == "unknown":
            return None
        data["_adhoc"] = True
        data["_coordinates_approximate"] = True
        return data
    except (json.JSONDecodeError, ValueError):
        return None


def _run_parallel(trip_context: dict) -> dict:
    """Run Intelligence Agent, Day Planner, and (for live trips) historical averages concurrently."""
    import copy
    from datetime import date

    # Determine if trip is within live forecast horizon
    _HORIZON = 7
    try:
        dates = trip_context["user_input"]["dates"]
        trip_start = date.fromisoformat(dates.get("start", ""))
        live_path = (trip_start - date.today()).days <= _HORIZON
    except (KeyError, ValueError):
        live_path = True

    # Deep copy so each worker gets its own isolated context.
    intel_ctx = copy.deepcopy(trip_context)
    intel_ctx["reasoning_trace"] = []

    planner_ctx = copy.deepcopy(trip_context)
    planner_ctx["reasoning_trace"] = []

    route = trip_context["selected_route"]
    dates = trip_context["user_input"]["dates"]

    workers = 3 if live_path else 2
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        intel_future   = executor.submit(intelligence_agent.run, intel_ctx)
        planner_future = executor.submit(day_planner.run, planner_ctx)
        hist_future    = (
            executor.submit(intelligence_agent._get_historical_conditions, route, dates)
            if live_path else None
        )

        intel_result   = intel_future.result()
        planner_result = planner_future.result()
        hist_result    = hist_future.result() if hist_future else None

    trip_context["conditions"] = intel_result.get("conditions", {})
    trip_context["itinerary"]  = planner_result.get("itinerary", {})
    if hist_result:
        trip_context["conditions_historical"] = hist_result
    trip_context["reasoning_trace"].extend(intel_result.get("reasoning_trace", []))
    trip_context["reasoning_trace"].extend(planner_result.get("reasoning_trace", []))

    return trip_context


def _assemble_brief(trip_context: dict) -> dict:
    """Assemble the final trip brief from Trip Context."""
    route = trip_context["selected_route"]
    itinerary = trip_context.get("itinerary", {})
    conditions            = trip_context.get("conditions", {})
    conditions_historical = trip_context.get("conditions_historical")
    risk = trip_context.get("risk", {})
    gear = trip_context.get("gear", [])
    plan_b = trip_context.get("plan_b")
    no_viable = trip_context.get("no_viable_route")
    trace = trip_context.get("reasoning_trace", [])

    if no_viable and isinstance(no_viable, dict):
        return {
            "status": "no_viable_route",
            "no_viable_route": no_viable,
            "route": {
                "id":               route["id"],
                "name":             route["name"],
                "sub_region":       route["sub_region"],
                "difficulty":       route["difficulty"],
                "route_type":       route.get("route_type", ""),
                "total_miles":      route["total_miles"],
                "elevation_gain_ft": route["elevation_gain_ft"],
                "description":      route.get("description", ""),
                "reservations":     route.get("reservations", {}),
            },
            "itinerary": itinerary,
            "conditions": {
                "_historical": conditions.get("_historical", False),
                "weather":     conditions.get("weather", {}),
                "aqi":         conditions.get("aqi", {}),
                "fire":        conditions.get("fire", {}),
                "water":       conditions.get("water", {}),
                "wildlife":    conditions.get("wildlife", {}),
            },
            "risk":       risk,
            "gear":       gear,
            "gear_notes": trip_context.get("gear_notes", ""),
            "reasoning_trace": trace,
        }

    user_input = trip_context.get("user_input", {})
    days_adjusted = user_input.get("_days_adjusted", False)
    days_original = user_input.get("_days_original")
    days_used = user_input.get("trip_length_days")

    brief = {
        "status": "ok",
        "route": {
            "id": route["id"],
            "name": route["name"],
            "sub_region": route["sub_region"],
            "difficulty": route["difficulty"],
            "route_type": route.get("route_type", ""),
            "total_miles": route["total_miles"],
            "elevation_gain_ft": route["elevation_gain_ft"],
            "description": route.get("description", ""),
            "reservations": route.get("reservations", {}),
            **({ "_adhoc": True, "_coordinates_approximate": True }
               if route.get("_adhoc") else {}),
        },
        "itinerary": itinerary,
        "conditions": {
            "summary":    conditions.get("synthesis_notes", ""),
            "_historical": conditions.get("_historical", False),
            "weather":    conditions.get("weather", {}),
            "aqi":        conditions.get("aqi", {}),
            "fire":       conditions.get("fire", {}),
            "water":      conditions.get("water", {}),
            "wildlife":   conditions.get("wildlife", {}),
        },
        "risk": risk,
        "gear": gear,
        "gear_notes": trip_context.get("gear_notes", ""),
        "reasoning_trace": trace,
    }

    if conditions_historical:
        brief["conditions_historical"] = {
            "summary": conditions_historical.get("synthesis_notes", ""),
            "weather": conditions_historical.get("weather", {}),
            "aqi":     conditions_historical.get("aqi", {}),
            "fire":    conditions_historical.get("fire", {}),
            "water":   conditions_historical.get("water", {}),
        }

    if days_adjusted:
        brief["days_adjusted"] = {
            "original_days": days_original,
            "planned_days": days_used,
            "note": (
                f"No route fits exactly {days_original} day(s) within the 5-15 mi/day range. "
                f"Plan adjusted to {days_used} day(s)."
            ),
        }

    if plan_b:
        brief["status"] = "plan_b"
        brief["plan_b"] = plan_b

    return brief


def _miles_per_day_ok(total_miles: float, trip_days: int, difficulty: str) -> bool:
    lo, hi = _DIFFICULTY_MILES_PER_DAY.get(difficulty, (8, 20))
    mpd = total_miles / max(trip_days, 1)
    return lo * 0.6 <= mpd <= hi * 1.5  # allow ±40% flex


def _month_from_date(date_str: str) -> str:
    try:
        d = date.fromisoformat(date_str)
        return d.strftime("%B")  # e.g. "July"
    except ValueError:
        return ""


def _no_route_response(user_input: dict) -> dict:
    difficulty = user_input.get("difficulty", "Moderate")
    trip_days = user_input.get("trip_length_days", 1)
    _MIN_MPD = 5.0
    _MAX_MPD = 15.0

    try:
        with open(_ROUTES_PATH) as f:
            all_routes = json.load(f)["routes"]
        diff_routes = [r for r in all_routes if r["difficulty"] == difficulty]

        if diff_routes:
            longest = max(diff_routes, key=lambda r: r["total_miles"])
            shortest = min(diff_routes, key=lambda r: r["total_miles"])
            max_days = max(1, int(longest["total_miles"] // _MIN_MPD))
            min_days = max(1, int(shortest["total_miles"] // _MAX_MPD) + (
                1 if shortest["total_miles"] % _MAX_MPD else 0
            ))

            # Too many days requested — no route long enough
            if trip_days > max_days:
                longer = [
                    r for r in all_routes
                    if _MIN_MPD <= r["total_miles"] / trip_days <= _MAX_MPD
                    and r["difficulty"] != difficulty
                ]
                suggestions = [
                    f"Plan a {max_days}-day trip instead — the longest {difficulty} route "
                    f"is {longest['name']} ({longest['total_miles']} miles)",
                ]
                if longer:
                    longer.sort(key=lambda r: abs(r["total_miles"] / trip_days - 10))
                    suggestions.append(
                        f"Or try a {longer[0]['difficulty']} route: "
                        f"{longer[0]['name']} ({longer[0]['total_miles']} miles fits {trip_days} days)"
                    )
                return {
                    "status": "no_route_found",
                    "message": (
                        f"No {difficulty} route is long enough for a {trip_days}-day trip "
                        f"(min 5 mi/day). The longest {difficulty} route is "
                        f"{longest['name']} at {longest['total_miles']} miles ({max_days} days max)."
                    ),
                    "suggested_next_steps": suggestions,
                }

            # Too few days — route would exceed 15 mi/day
            if trip_days < min_days:
                suggestions = [
                    f"Plan at least {min_days} days — the shortest {difficulty} route "
                    f"is {shortest['name']} ({shortest['total_miles']} miles, needs {min_days}+ days at 15 mi/day max)",
                ]
                shorter = [
                    r for r in all_routes
                    if _MIN_MPD <= r["total_miles"] / trip_days <= _MAX_MPD
                    and r["difficulty"] != difficulty
                ]
                if shorter:
                    shorter.sort(key=lambda r: r["total_miles"] / trip_days, reverse=True)
                    suggestions.append(
                        f"Or try a {shorter[0]['difficulty']} route that fits {trip_days} day(s): "
                        f"{shorter[0]['name']} ({shorter[0]['total_miles']} miles)"
                    )
                return {
                    "status": "no_route_found",
                    "message": (
                        f"A {trip_days}-day {difficulty} trip would exceed 15 miles/day. "
                        f"The shortest {difficulty} route is "
                        f"{shortest['name']} at {shortest['total_miles']} miles."
                    ),
                    "suggested_next_steps": suggestions,
                }
    except Exception:
        pass

    return {
        "status": "no_route_found",
        "message": "No route found matching your criteria.",
        "suggested_next_steps": [
            "Try a different difficulty level",
            "Expand sub_region or leave it blank to search all regions",
        ],
    }
