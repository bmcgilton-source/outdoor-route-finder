"""
Gear Sub-agent — generates a conditions-aware gear list.

Runs INSIDE the Assessment Agent, after the Intelligence Agent has completed.
Requires: trip_context["conditions"] (weather, AQI, fire, water).

Output written to trip_context["gear"].
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
You are the Gear Advisor for TrailOps, an outdoor route planning system for performance-oriented hikers.

Your role: generate a lean, technical gear list calibrated to the specific conditions of this trip.
Assume the hiker is experienced and already owns standard hiking gear. Focus on DELTA items — \
gear additions or swaps driven by the specific conditions, route, and dates.

Tone: performance-first. Recommend technical gear (trail runners, cuben fiber/DCF, ultralight shelter, \
trekking poles for river crossings, etc.). Do NOT recommend heavy or overly conservative items unless \
conditions strictly require them.

Given the route, itinerary, and conditions data, return a JSON gear list:
{
  "gear": [
    {
      "item": "<gear item>",
      "reason": "<why this trip/conditions specifically requires it>",
      "priority": "required|recommended|optional"
    }
  ],
  "gear_notes": "<1-2 sentences on any dominant condition driving gear choices>"
}

Categories to consider (only include items warranted by conditions):
- Navigation: map/compass if trail is remote or poorly marked
- Water crossing: trekking poles, dry bags if river crossings are high
- Fire/smoke: N95 mask if AQI is high
- Rain/weather: rain shell, gaiters if precip > 50%
- Sun/heat: sun hoody, electrolytes if high temps + exposed terrain
- Cold: insulation layer if temps drop below 45°F at elevation
- Emergency: SAR beacon for Epic/remote routes

Do not include any text outside the JSON object.
"""


def run(trip_context: dict) -> dict:
    """
    Generate conditions-aware gear list.

    Reads from trip_context:
      - selected_route
      - itinerary
      - conditions (weather, aqi, fire, water)
      - user_input.difficulty

    Writes to trip_context:
      - gear
      - reasoning_trace (appended)

    Returns: updated trip_context
    """
    route = trip_context["selected_route"]
    conditions = trip_context.get("conditions", {})
    itinerary = trip_context.get("itinerary", {})
    user_input = trip_context["user_input"]
    trace = trip_context.setdefault("reasoning_trace", [])

    log.info("Gear: generating conditions-aware gear list")
    trace.append({"agent": "gear", "event": "start"})

    user_message = _build_user_message(route, itinerary, conditions, user_input)

    response = _client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = _extract_text(response)
    gear_output = _parse_json(raw)

    if gear_output.get("_parse_error"):
        log.warning("Gear: JSON parse failed — gear list may be empty")
    log.info(f"Gear: complete — {len(gear_output.get('gear', []))} items")
    trip_context["gear"] = gear_output.get("gear", [])
    trip_context.setdefault("gear_notes", gear_output.get("gear_notes", ""))

    trace.append({
        "agent": "gear",
        "event": "complete",
        "item_count": len(trip_context["gear"]),
        "gear_notes": gear_output.get("gear_notes", ""),
    })

    return trip_context


def _build_user_message(
    route: dict, itinerary: dict, conditions: dict, user_input: dict
) -> str:
    days = itinerary.get("days", [])
    weather_days = conditions.get("weather", {}).get("days", [])
    aqi_days = conditions.get("aqi", {}).get("days", [])
    fire = conditions.get("fire", {})
    water = conditions.get("water", {})
    synthesis = conditions.get("synthesis_notes", "")

    return (
        f"Generate a gear list for this trip.\n\n"
        f"Route: {route['name']} ({route['difficulty']} / {route['route_type']})\n"
        f"Total miles: {route['total_miles']} over {len(days)} day(s)\n"
        f"Difficulty: {user_input.get('difficulty', 'Unknown')}\n\n"
        f"Conditions summary: {synthesis}\n\n"
        f"Weather:\n{json.dumps(weather_days, indent=2)}\n\n"
        f"AQI:\n{json.dumps(aqi_days, indent=2)}\n\n"
        f"Fire:\n{json.dumps(fire, indent=2)}\n\n"
        f"Water crossings:\n{json.dumps(water, indent=2)}\n\n"
        "Return JSON only."
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
        return {"gear": [], "gear_notes": raw, "_parse_error": True}
