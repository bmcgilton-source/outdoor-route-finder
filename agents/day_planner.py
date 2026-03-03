"""
Day Planner Sub-agent — builds the initial day-by-day itinerary from route data alone.

Runs in PARALLEL with the Intelligence Agent. Does not use conditions data.
Works from: selected_route, user_input (dates, trip_length_days, difficulty)

Output written to trip_context["itinerary"].
"""

import json
import math

import anthropic

from logger import get_logger
from tools.base import CONFIG

log = get_logger(__name__)

_client = anthropic.Anthropic()
_MODEL = CONFIG["claude"]["model"]
_MAX_TOKENS = CONFIG["claude"]["max_tokens"]

_SYSTEM = """\
You are the Day Planner for TrailOps, an outdoor route planning system for performance-oriented hikers.

Your role: build a day-by-day hiking itinerary from route data. You have NO conditions information yet \
— your job is to plan the route structure only.

Tone: performance-first. Prefer high mileage, challenging terrain, max elevation gain. \
Assume the hiker is fit and experienced.

Given route data and trip parameters, produce a JSON itinerary with this structure:
{
  "days": [
    {
      "day": 1,
      "date": "YYYY-MM-DD",
      "start_waypoint": "<name>",
      "end_waypoint": "<name>",
      "miles": <float>,
      "elevation_gain_ft": <int>,
      "elevation_loss_ft": <int>,
      "cumulative_miles": <float>,
      "highlights": ["<key viewpoint or objective>"],
      "water_sources": ["<name of water crossing or source within this day's segment>"],
      "camp": "<campsite name or 'day hike — return to trailhead'>",
      "description": "<1-2 sentences describing the day's terrain, character, and what the hiker will experience>"
    }
  ],
  "total_miles": <float>,
  "total_elevation_gain_ft": <int>,
  "miles_per_day_avg": <float>,
  "planner_notes": "<1-2 sentences on pacing logic, key decision points>",
  "itinerary_summary": "<1 paragraph narrative of the full trip arc: what the hiker experiences each day, key terrain and highlights, how the days build on each other>"
}

Rules:
- Distribute miles evenly across days, slightly front-loading if terrain allows.
- For day hikes (trip_length_days=1): plan the full route as a single day.
- For loops: return to trailhead on the final day.
- For thru-hikes: end at the exit trailhead on the final day.
- elevation_gain_ft and elevation_loss_ft per day should be estimated from waypoint elevations.
- water_sources: use the provided water sources list (each has a cumulative_miles value) to assign sources to \
the correct day based on that day's mileage range. Also include river crossings that fall within the day's segment. \
If a day has no water sources, use ["carry sufficient water — no sources on this segment"].
- Do not include any text outside the JSON object.
"""


def run(trip_context: dict) -> dict:
    """
    Build initial itinerary from route data.

    Reads from trip_context:
      - selected_route
      - user_input.dates
      - user_input.trip_length_days
      - user_input.difficulty

    Writes to trip_context:
      - itinerary
      - reasoning_trace (appended)

    Returns: updated trip_context
    """
    route = trip_context["selected_route"]
    user_input = trip_context["user_input"]
    trace = trip_context.setdefault("reasoning_trace", [])

    log.info(f"Day Planner: building {user_input.get('trip_length_days', 1)}-day itinerary for {route['name']}")
    trace.append({"agent": "day_planner", "event": "start", "route": route["id"]})

    user_message = _build_user_message(route, user_input)

    response = _client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = _extract_text(response)
    itinerary = _parse_json(raw)

    if itinerary.get("_parse_error"):
        log.warning("Day Planner: JSON parse failed — itinerary may be empty")
    log.info(f"Day Planner: complete — {len(itinerary.get('days', []))} days planned")
    trip_context["itinerary"] = itinerary
    trace.append({
        "agent": "day_planner",
        "event": "complete",
        "days_planned": len(itinerary.get("days", [])),
        "planner_notes": itinerary.get("planner_notes", ""),
    })

    return trip_context


def _build_user_message(route: dict, user_input: dict) -> str:
    dates = user_input["dates"]
    trip_days = user_input.get("trip_length_days", 1)
    difficulty = user_input.get("difficulty", "Moderate")

    water_crossings = route.get("water_crossings", [])
    water_sources = route.get("water_sources", [])

    crossings_section = (
        f"River/stream crossings (fords — include in water_sources and flag as potential hazard):\n"
        f"{json.dumps(water_crossings, indent=2)}\n\n"
        if water_crossings
        else "River crossings: none documented.\n\n"
    )
    sources_section = (
        f"Water sources by cumulative mile (lakes, tarns, springs, streams — assign each to the correct day):\n"
        f"{json.dumps(water_sources, indent=2)}\n\n"
        if water_sources
        else "Water sources: none documented — note in water_sources that the hiker should carry all water.\n\n"
    )

    return (
        f"Build an itinerary for this trip:\n\n"
        f"Route: {route['name']}\n"
        f"Type: {route['route_type']}\n"
        f"Total miles: {route['total_miles']}\n"
        f"Total elevation gain: {route['elevation_gain_ft']} ft\n"
        f"Difficulty: {difficulty}\n"
        f"Trip length: {trip_days} day(s)\n"
        f"Start date: {dates['start']}\n"
        f"End date: {dates['end']}\n\n"
        f"Waypoints:\n{json.dumps(route['waypoints'], indent=2)}\n\n"
        f"{crossings_section}"
        f"{sources_section}"
        "Distribute the route across the trip days. Return JSON only."
    )


def _extract_text(response) -> str:
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return "{}"


def _parse_json(raw: str) -> dict:
    import re
    text = re.sub(r"```(?:json)?\s*", "", raw).strip().strip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "days": [],
            "total_miles": 0,
            "total_elevation_gain_ft": 0,
            "miles_per_day_avg": 0,
            "planner_notes": raw,
            "_parse_error": True,
        }
