"""
Plan B Sub-agent — finds and plans an alternate route in the same region.

Spawned by Assessment Agent when Replanner cannot resolve risk.
Max 1 attempt.

Selects an alternate route from routes.json (same sub_region preferred, same difficulty),
then runs the Day Planner logic for that route.
Writes to trip_context["plan_b"] — does NOT overwrite the original itinerary.
"""

import json
import re
from pathlib import Path

import anthropic

from logger import get_logger
from tools.base import CONFIG

log = get_logger(__name__)

_client = anthropic.Anthropic()
_MODEL = CONFIG["claude"]["model"]
_MAX_TOKENS = CONFIG["claude"]["max_tokens"]

_ROUTES_PATH = Path(__file__).parent.parent.parent / "data" / "routes.json"

_SYSTEM = """\
You are the Plan B advisor for TrailOps, an outdoor route planning system.

The original route is not viable due to environmental conditions. \
Your job: select the best alternate route from the candidates provided and \
build a day-by-day itinerary for it.

Selection criteria (in order):
1. Same sub_region as original (preferred, but not required)
2. Same difficulty level (preferred)
3. Lower exposure to the dominant risk factor (e.g. if fire risk, pick a route further away)

Return a JSON object with this structure:
{
  "alternate_route_id": "<id from candidates>",
  "alternate_route_name": "<name>",
  "reason_selected": "<why this route avoids the original risk>",
  "itinerary": {
    "days": [ { same structure as Day Planner } ],
    "total_miles": <float>,
    "total_elevation_gain_ft": <int>,
    "miles_per_day_avg": <float>,
    "planner_notes": "<pacing notes>"
  }
}

Do not include any text outside the JSON object.
"""


def run(trip_context: dict) -> dict:
    """
    Find and plan an alternate route.

    Reads from trip_context: selected_route, user_input, conditions, risk
    Writes to trip_context: plan_b, reasoning_trace

    Returns: updated trip_context
    """
    trace = trip_context.setdefault("reasoning_trace", [])
    trace.append({"agent": "plan_b", "event": "start"})

    original_route = trip_context["selected_route"]
    user_input = trip_context["user_input"]
    conditions = trip_context["conditions"]
    risk = trip_context["risk"]

    candidates = _get_candidates(original_route["id"])
    log.info(f"Plan B: searching {len(candidates)} alternate route candidates")

    if not candidates:
        log.warning("Plan B: no alternate route candidates available")
        trip_context["no_viable_route"] = True
        trace.append({"agent": "plan_b", "event": "no_candidates"})
        return trip_context

    user_message = _build_user_message(
        original_route, candidates, user_input, conditions, risk
    )

    response = _client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = _extract_text(response)
    plan_b = _parse_json(raw)

    if plan_b and not plan_b.get("_parse_error"):
        log.info(f"Plan B: selected '{plan_b.get('alternate_route_name', 'unknown')}' as alternate route")
        trip_context["plan_b"] = plan_b
        trace.append({
            "agent": "plan_b",
            "event": "complete",
            "alternate_route": plan_b.get("alternate_route_name", ""),
            "reason": plan_b.get("reason_selected", ""),
        })
    else:
        log.error("Plan B: JSON parse failed — setting no_viable_route")
        trip_context["no_viable_route"] = True
        trace.append({"agent": "plan_b", "event": "failed", "raw": raw[:200]})

    return trip_context


def _get_candidates(exclude_id: str) -> list[dict]:
    """Load all routes except the one already attempted."""
    with open(_ROUTES_PATH) as f:
        data = json.load(f)
    return [r for r in data["routes"] if r["id"] != exclude_id]


def _build_user_message(
    original: dict,
    candidates: list[dict],
    user_input: dict,
    conditions: dict,
    risk: dict,
) -> str:
    dates = user_input["dates"]
    trip_days = user_input.get("trip_length_days", 1)

    return (
        f"Original route '{original['name']}' is not viable.\n"
        f"Dominant risk: {risk.get('dominant_factor', 'unknown')} "
        f"({risk.get('overall_risk', 'high')})\n"
        f"Conditions summary: {conditions.get('synthesis_notes', '')}\n\n"
        f"Trip parameters: {trip_days} day(s), {dates['start']} to {dates['end']}, "
        f"difficulty: {user_input.get('difficulty', 'Moderate')}\n\n"
        f"Alternate route candidates:\n{json.dumps(candidates, indent=2)}\n\n"
        "Select the best alternate and build its itinerary. Return JSON only."
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
