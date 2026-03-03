"""
Intelligence Agent — gathers all environmental conditions via parallel tool calls.

Architecture:
  - Single Claude API call with all 4 tools defined in the request
  - Claude calls all 4 tools in parallel (parallel tool use)
  - Python executes the tools concurrently with ThreadPoolExecutor
  - Claude synthesizes results into the Conditions Schema
  - Writes `conditions` to Trip Context and appends to `reasoning_trace`

Forecast horizon:
  - If the trip start date is more than forecast_horizon_days (default 7) from today,
    live APIs cannot provide meaningful forecasts. In that case the agent skips the
    tool use loop and calls _get_historical_conditions() instead, which asks Claude
    to return typical seasonal averages for the route's region and month.
"""

import concurrent.futures
import json
import re
from datetime import date

import anthropic

from logger import get_logger
from tools.airnow import get_air_quality
from tools.base import CONFIG
from tools.inaturalist import get_wildlife
from tools.nifc import get_fire_data
from tools.nws import get_weather
from tools.reddit import get_community_reports
from tools.tool_definitions import INTELLIGENCE_TOOLS
from tools.usgs import get_streamflow

log = get_logger(__name__)

_client      = anthropic.Anthropic()
_MODEL       = CONFIG["claude"]["model"]        # sonnet — tool loop + synthesis
_HAIKU_MODEL = CONFIG["claude"]["haiku_model"]  # haiku — historical conditions
_MAX_TOKENS  = CONFIG["claude"]["max_tokens"]
_HORIZON_DAYS = CONFIG["thresholds"]["forecast_horizon_days"]

_TOOL_MAP = {
    "get_weather":            get_weather,
    "get_air_quality":        get_air_quality,
    "get_fire_data":          get_fire_data,
    "get_streamflow":         get_streamflow,
    "get_wildlife":           get_wildlife,
    "get_community_reports":  get_community_reports,
}

_HISTORICAL_SYSTEM = """\
You are the Intelligence Agent for TrailOps, an outdoor route planning system for the Pacific Northwest.

The trip is more than 7 days out, so live weather and air quality forecasts are not available.
Your job is to return typical seasonal conditions for this route based on historical averages
and general knowledge of the region and time of year.

Return ONLY a valid JSON object with exactly this structure:
{
  "weather": {
    "source": "historical_average",
    "typical_high_f": <int>,
    "typical_low_f": <int>,
    "typical_precip_inches": <float, monthly average>,
    "typical_conditions": "<brief description, e.g. 'Cool and wet with possible snow above 5000 ft'>",
    "alerts": []
  },
  "aqi": {
    "source": "historical_average",
    "typical_category": "<Good / Moderate / USG / Unhealthy / etc.>",
    "typical_aqi": <int>,
    "fire_season_note": "<one sentence on wildfire smoke risk for this month and region>"
  },
  "fire": {
    "source": "historical_average",
    "typical_fire_risk": "<Low / Moderate / High / Very High>",
    "note": "<one sentence on historical fire activity for this region and month>"
  },
  "water": {
    "source": "historical_average",
    "crossings": [
      {
        "name": "<crossing name from route data>",
        "typical_flow": "<Low / Moderate / High / Very High>",
        "note": "<one sentence, e.g. 'Snowmelt peaks in June; typically safe by late July'>"
      }
    ]
  },
  "community_reports": {
    "posts": [],
    "post_count": 0,
    "source": "community_reports",
    "notes": "Community trip reports are not available for trips more than 7 days out."
  },
  "synthesis_notes": "<2-3 plain sentences summarising typical conditions for this route in this month. State clearly that this is based on historical averages and that the user should check current forecasts closer to their trip date.>"
}

Rules:
- Base your estimates on the sub_region, elevation, and month provided.
- For water crossings, use the crossing names from the route data. If there are no crossings, use an empty list.
- synthesis_notes must be plain prose only: no JSON, no code blocks, no markdown, no backticks.
- Do not include any text outside the JSON object.
"""

_SYSTEM = """\
You are the Intelligence Agent for TrailOps, an outdoor route planning system for the Pacific Northwest.

Your role: gather ALL environmental conditions for a hiking route by calling all six tools, then \
synthesize the results into a structured JSON conditions object.

Steps:
1. Call get_weather, get_air_quality, get_fire_data, get_streamflow, get_wildlife, and \
get_community_reports. Call all six simultaneously — do not wait for one before calling the next.
2. After all results are returned, synthesize them into a single JSON response.

Your final response MUST be valid JSON with exactly this structure:
{
  "weather":             { <full get_weather response> },
  "aqi":                 { <full get_air_quality response> },
  "fire":                { <full get_fire_data response> },
  "water":               { <full get_streamflow response> },
  "wildlife":            { <full get_wildlife response> },
  "community_reports":   { <full get_community_reports response> },
  "synthesis_notes": "<2-3 plain sentences summarising key conditions>"
}

Rules:
- Include the complete tool output under each key — do not summarize or truncate it.
- For routes with no water crossings, get_streamflow will return an empty crossings list — include it.
- synthesis_notes must be plain prose only: no JSON, no code blocks, no markdown, no backticks.
  Flag the single highest-risk factor first, then note anything else actionable.
  Mention wildlife if risk_level is medium or high.
  If community_reports has posts, briefly note whether they confirm or contradict official data.
  Always label community reports as unverified.
  Example: "Weather looks clear for both days with no alerts. AQI is Good. One river crossing
  is at moderate flow — confirm conditions day-of. Community reports (unverified) mention high water."
- Do not include any text outside the JSON object. Output the JSON immediately with no preamble.
"""


def run(trip_context: dict) -> dict:
    """
    Execute the Intelligence Agent tool use loop.

    Reads from trip_context:
      - selected_route
      - user_input.dates

    Writes to trip_context:
      - conditions  (Conditions Schema)
      - reasoning_trace (appended)

    Returns: updated trip_context
    """
    route = trip_context["selected_route"]
    dates = trip_context["user_input"]["dates"]
    trace = trip_context.setdefault("reasoning_trace", [])

    trace.append({"agent": "intelligence", "event": "start", "route": route["id"]})

    # --- Forecast horizon check ---
    try:
        trip_start = date.fromisoformat(dates["start"])
        days_until_trip = (trip_start - date.today()).days
    except (KeyError, ValueError):
        days_until_trip = 0  # if we can't parse the date, proceed with live APIs

    if days_until_trip > _HORIZON_DAYS:
        log.info(f"Intelligence: {days_until_trip}d until trip (>{_HORIZON_DAYS}d horizon) — using historical conditions")
        trace.append({
            "agent": "intelligence",
            "event": "historical_mode",
            "days_until_trip": days_until_trip,
            "horizon_days": _HORIZON_DAYS,
        })
        conditions = _get_historical_conditions(route, dates)
        trip_context["conditions"] = conditions
        trace.append({
            "agent": "intelligence",
            "event": "complete",
            "synthesis_notes": conditions.get("synthesis_notes", ""),
        })
        return trip_context

    log.info(f"Intelligence: starting live tool use loop for {route['name']} ({dates['start']} to {dates['end']})")
    messages = [{"role": "user", "content": _build_user_message(route, dates)}]

    # Tool use loop — continues until Claude returns end_turn
    while True:
        response = _client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM,
            tools=INTELLIGENCE_TOOLS,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            log.debug(f"Intelligence: tools called: {[t.name for t in tool_uses]}")

            trace.append({
                "agent": "intelligence",
                "event": "tools_called",
                "tools": [t.name for t in tool_uses],
            })

            tool_results = _execute_tools_parallel(tool_uses)

            # Extend message history with assistant response + tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        elif response.stop_reason == "end_turn":
            raw_text = _extract_text(response)
            conditions = _parse_json(raw_text)

            # Defensively strip any JSON/markdown that leaked into synthesis_notes
            notes = conditions.get("synthesis_notes", "")
            if isinstance(notes, str):
                # Truncate at the first code-fence or JSON object if Claude misbehaves
                for sentinel in ("```", "{"):
                    idx = notes.find(sentinel)
                    if idx > 0:
                        notes = notes[:idx].strip()
                conditions["synthesis_notes"] = notes

            if conditions.get("_parse_error"):
                log.warning("Intelligence: JSON parse failed — synthesis_notes contains raw response")
            log.info("Intelligence: conditions synthesized successfully")
            trip_context["conditions"] = conditions

            trace.append({
                "agent": "intelligence",
                "event": "complete",
                "synthesis_notes": conditions.get("synthesis_notes", ""),
            })
            return trip_context

        else:
            log.error(f"Intelligence: unexpected stop_reason '{response.stop_reason}'")
            raise RuntimeError(
                f"Intelligence Agent: unexpected stop_reason '{response.stop_reason}'"
            )


def _get_historical_conditions(route: dict, dates: dict) -> dict:
    """
    Return typical seasonal conditions via a single Claude call when the trip is
    beyond the live-forecast horizon. Uses the same Conditions Schema as the live path.
    Falls back to a stub on any error.
    """
    crossings = route.get("water_crossings", [])
    crossing_names = [c.get("name", "unnamed") for c in crossings]
    trip_month = dates["start"][5:7]  # "YYYY-MM-DD" → "MM"

    user_msg = (
        f"Provide typical seasonal conditions for this hiking route:\n\n"
        f"Route: {route['name']}\n"
        f"Sub-region: {route.get('sub_region', 'Pacific Northwest')}\n"
        f"Difficulty: {route.get('difficulty', 'unknown')}\n"
        f"Elevation range: {route.get('elevation_gain_ft', 'unknown')} ft gain\n"
        f"Trip month: {trip_month}\n"
        f"Water crossings: {json.dumps(crossing_names)}\n\n"
        "Return historical average conditions for this month and region."
    )

    try:
        response = _client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_HISTORICAL_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = _extract_text(response)
        conditions = _parse_json(raw)
        # Defensive strip on synthesis_notes
        notes = conditions.get("synthesis_notes", "")
        if isinstance(notes, str):
            for sentinel in ("```", "{"):
                idx = notes.find(sentinel)
                if idx > 0:
                    notes = notes[:idx].strip()
            conditions["synthesis_notes"] = notes
        conditions["_historical"] = True
        return conditions
    except Exception as exc:
        return {
            "weather":           {"source": "historical_average"},
            "aqi":               {"source": "historical_average"},
            "fire":              {"source": "historical_average"},
            "water":             {"source": "historical_average", "crossings": []},
            "wildlife":          {"source": "historical_average"},
            "community_reports": {"posts": [], "post_count": 0, "source": "community_reports"},
            "synthesis_notes": (
                "Your trip is more than a week out, so live forecasts aren't available yet. "
                "Check back closer to your departure date for current conditions."
            ),
            "_historical": True,
            "_error": str(exc),
        }


def _build_user_message(route: dict, dates: dict) -> str:
    """Construct the user message with all route data Claude needs to call the tools."""
    bb = route["bounding_box"]
    trailhead = route["trailhead"]
    crossings = route.get("water_crossings", [])

    return (
        f"Gather conditions for this hiking trip:\n\n"
        f"Route: {route['name']}\n"
        f"Sub-region: {route.get('sub_region', 'Pacific Northwest')}\n"
        f"Trailhead: {trailhead['lat']}, {trailhead['lon']}\n"
        f"Bounding box: min_lat={bb['min_lat']}, max_lat={bb['max_lat']}, "
        f"min_lon={bb['min_lon']}, max_lon={bb['max_lon']}\n"
        f"Water crossings: {json.dumps(crossings)}\n"
        f"Trip dates: {dates['start']} to {dates['end']}\n\n"
        f"For get_community_reports, use trail_name=\"{route['name']}\" "
        f"and region=\"{route.get('sub_region', '')}\". "
        "Call all six tools now."
    )


def _execute_tools_parallel(tool_uses: list) -> list:
    """Execute all tool calls concurrently. Returns list of tool_result content blocks."""
    id_to_result = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tool_uses)) as executor:
        futures = {
            executor.submit(_call_tool, t.name, t.input): t.id
            for t in tool_uses
        }
        for future in concurrent.futures.as_completed(futures):
            tool_use_id = futures[future]
            try:
                result = future.result()
                id_to_result[tool_use_id] = {"content": json.dumps(result), "is_error": False}
            except Exception as exc:
                id_to_result[tool_use_id] = {
                    "content": json.dumps({"error": str(exc)}),
                    "is_error": True,
                }

    return [
        {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": data["content"],
            **({"is_error": True} if data["is_error"] else {}),
        }
        for tool_use_id, data in id_to_result.items()
    ]


def _call_tool(name: str, inputs: dict) -> dict:
    fn = _TOOL_MAP.get(name)
    if fn is None:
        raise ValueError(f"Unknown tool: {name}")
    return fn(**inputs)


def _extract_text(response) -> str:
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return "{}"


def _parse_json(raw: str) -> dict:
    """Extract and parse JSON from Claude's response, stripping any markdown fences."""
    text = re.sub(r"```(?:json)?\s*", "", raw).strip().strip("`").strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Claude sometimes includes preamble text before the JSON block.
    # Find the first { and try parsing from there.
    start = text.find("{")
    if start != -1:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            pass
    # Return the raw text in synthesis_notes so nothing is silently lost
    return {
        "weather":           {},
        "aqi":               {},
        "fire":              {},
        "water":             {},
        "wildlife":          {},
        "community_reports": {},
        "synthesis_notes":   raw,
        "_parse_error":      True,
    }
