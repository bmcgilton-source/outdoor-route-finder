"""
Washington DOT mountain pass conditions tool.

Pre-flight gate: called directly by the Orchestrator (not via Claude tool use)
before the Intelligence Agent runs. If the access pass is closed, the pipeline
exits early rather than running a full conditions check for an unreachable route.

Fail-open policy: if the WSDOT API is unavailable, assume the pass is open and
let the pipeline continue. An API outage shouldn't block trip planning.
"""

import os

from logger import get_logger
from tools.base import CONFIG, call_with_retry, mock_scenario, use_mock

log = get_logger(__name__)

_BASE = CONFIG["apis"]["wa_dot"]["base_url"]
_ENDPOINT = CONFIG["apis"]["wa_dot"]["endpoints"]["pass_conditions"]
_KEY_ENV = CONFIG["apis"]["wa_dot"]["auth"]["env_var"]

# Route ID → WSDOT MountainPassId
# None = no mountain pass required for this route (no gate applied)
_ROUTE_PASS_MAP: dict[str, int | None] = {
    "goat-rocks-snowgrass":     2,    # White Pass (US-12)
    "enchantments-traverse":    None, # Icicle Creek Rd — no pass gate
    "olympic-high-divide":      None, # US-101 — no pass
    "maple-pass-loop":          17,   # North Cascades Hwy (SR-20) — seasonal closure
    "pasayten-wilderness":      17,   # North Cascades Hwy (SR-20) — seasonal closure
    "rattlesnake-ledge":        7,    # Snoqualmie Pass (I-90)
    "mount-pilchuck":           None, # Mountain Loop Hwy — no WSDOT pass
    "heather-lake":             None, # Mountain Loop Hwy — no WSDOT pass
    "ozette-triangle":          None, # US-101 — no pass
    "lake-22":                  None, # Mountain Loop Hwy — no WSDOT pass
    "mount-si":                 None, # No pass needed
    "skyline-loop-rainier":     22,   # Cayuse Pass (SR-410)
    "sahale-arm":               17,   # North Cascades Hwy (SR-20) — seasonal closure
    "snoqualmie-lake":          7,    # Snoqualmie Pass (I-90)
    "wonderland-trail":         22,   # Cayuse Pass (SR-410)
    "glacier-peak-white-chuck": None, # Mountain Loop Hwy — no WSDOT pass
}

_PASS_NAMES: dict[int, str] = {
    2:  "White Pass (US-12)",
    3:  "Stevens Pass (US-2)",
    7:  "Snoqualmie Pass (I-90)",
    17: "North Cascades Highway (SR-20)",
    22: "Cayuse Pass (SR-410)",
    23: "Chinook Pass (SR-410)",
    39: "Hurricane Ridge Road",
}


def get_pass_status(route_id: str) -> dict:
    """
    Return the mountain pass status for the given route.

    Returns a dict with:
      pass_id:             WSDOT pass ID (None if no relevant pass)
      pass_name:           Human-readable pass name (None if no relevant pass)
      is_open:             True if pass is open or no gate applies
      road_condition:      Road condition string from WSDOT
      weather_condition:   Weather condition string from WSDOT
      restriction:         Restriction text, or None if no restriction
      _gated:              True if this route has a relevant pass (gate was checked)
    """
    # Ad-hoc routes (route_id starts with "adhoc-") skip the gate — we don't
    # know their access road, so fail-open.
    if route_id.startswith("adhoc-"):
        return _no_gate_result()

    pass_id = _ROUTE_PASS_MAP.get(route_id)
    if pass_id is None:
        return _no_gate_result()

    if use_mock() or os.getenv("MOCK_PASS_CLOSED", "false").lower() == "true":
        return _mock_pass_status(pass_id, route_id)

    api_key = os.getenv(_KEY_ENV, "")
    if not api_key:
        log.warning("WSDOT: no API key set — assuming pass is open (fail-open)")
        return _open_result(pass_id)

    try:
        return _live_pass_status(pass_id, api_key)
    except Exception as e:
        log.warning(f"WSDOT unavailable — assuming pass is open. Error: {e}")
        return {**_open_result(pass_id), "_fallback": True, "_error": str(e)}


def _live_pass_status(pass_id: int, api_key: str) -> dict:
    log.info(f"WSDOT: fetching live pass conditions for pass ID {pass_id}")
    url = f"{_BASE}{_ENDPOINT}?AccessCode={api_key}"
    data = call_with_retry(url)

    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected WSDOT response type: {type(data)}")

    pass_obj = next((p for p in data if p.get("MountainPassId") == pass_id), None)
    if pass_obj is None:
        log.warning(f"WSDOT: pass ID {pass_id} not found in response — assuming open")
        return _open_result(pass_id)

    is_open = bool(pass_obj.get("IsOpen", True))
    road_condition = pass_obj.get("RoadCondition", "")
    weather_condition = pass_obj.get("WeatherCondition", "")

    restriction = None
    r1 = pass_obj.get("RestrictionOne", {}) or {}
    if r1.get("RestrictionText"):
        restriction = r1["RestrictionText"]

    return {
        "pass_id":           pass_id,
        "pass_name":         _PASS_NAMES.get(pass_id, f"Pass {pass_id}"),
        "is_open":           is_open,
        "road_condition":    road_condition,
        "weather_condition": weather_condition,
        "restriction":       restriction,
        "_gated":            True,
    }


def _mock_pass_status(pass_id: int, route_id: str = "") -> dict:
    """
    Mock pass status.
    - MOCK_SCENARIO=4 (Maple Pass / SR-20 closure) → return closed for SR-20 routes
    - MOCK_PASS_CLOSED=true → return closed for any gated pass
    - Otherwise → return open
    """
    scenario_4 = mock_scenario() == 4 and pass_id == 17  # SR-20 closed in scenario 4
    closed = os.getenv("MOCK_PASS_CLOSED", "false").lower() == "true" or scenario_4
    if closed:
        log.info(f"WSDOT mock: returning CLOSED for pass {pass_id} (MOCK_PASS_CLOSED=true)")
        return {
            "pass_id":           pass_id,
            "pass_name":         _PASS_NAMES.get(pass_id, f"Pass {pass_id}"),
            "is_open":           False,
            "road_condition":    "Seasonal Closure",
            "weather_condition": "Not Available",
            "restriction":       f"{_PASS_NAMES.get(pass_id, 'Pass')} — seasonal closure in effect",
            "_gated":            True,
        }
    log.info(f"WSDOT mock: returning OPEN for pass {pass_id}")
    return _open_result(pass_id)


def _open_result(pass_id: int) -> dict:
    return {
        "pass_id":           pass_id,
        "pass_name":         _PASS_NAMES.get(pass_id, f"Pass {pass_id}"),
        "is_open":           True,
        "road_condition":    "Open",
        "weather_condition": "",
        "restriction":       None,
        "_gated":            True,
    }


def _no_gate_result() -> dict:
    return {
        "pass_id":           None,
        "pass_name":         None,
        "is_open":           True,
        "road_condition":    "",
        "weather_condition": "",
        "restriction":       None,
        "_gated":            False,
    }
