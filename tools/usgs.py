"""
USGS Water Services streamflow tool.
Executes when Claude calls get_streamflow.
"""

import os
from math import asin, cos, radians, sin, sqrt

from logger import get_logger
from tools.base import CONFIG, call_with_retry, mock_scenario, use_mock

log = get_logger(__name__)

_BASE = CONFIG["apis"]["usgs"]["base_url"]


def get_streamflow(crossings: list[dict]) -> dict:
    if not crossings:
        return {"water": {"crossings": []}}
    if use_mock():
        return _mock_streamflow(crossings)
    try:
        return _live_streamflow(crossings)
    except Exception as e:
        log.warning(f"USGS unavailable — falling back to mock data. Error: {e}")
        return {**_mock_streamflow(crossings), "_fallback": True, "_error": str(e)}


def _live_streamflow(crossings: list[dict]) -> dict:
    log.info(f"USGS: fetching live streamflow for {len(crossings)} crossing(s)")
    headers = {}
    api_key = os.getenv("USGS_API_KEY")
    if api_key:
        headers["X-Api-Key"] = api_key

    results = []
    for crossing in crossings:
        lat, lon = crossing["lat"], crossing["lon"]

        # Find nearest gauge station within 0.5 degree bbox
        bbox = f"{lon - 0.5},{lat - 0.5},{lon + 0.5},{lat + 0.5}"
        locations_url = (
            f"{_BASE}/collections/monitoring-locations/items"
            f"?bbox={bbox}&f=json&limit=10"
        )
        locations = call_with_retry(locations_url, headers=headers)
        features = locations.get("features", [])

        if not features:
            results.append({
                "name": crossing["name"],
                "streamflow_cfs": None,
                "risk_level": "unknown",
                "note": "No gauge found nearby"
            })
            continue

        # Pick nearest gauge
        nearest = min(features, key=lambda f: _haversine(
            lat, lon,
            f["geometry"]["coordinates"][1],
            f["geometry"]["coordinates"][0]
        ))
        site_id = nearest["properties"]["monitoringLocationNumber"]

        # Get latest streamflow
        flow_url = (
            f"{_BASE}/collections/latest-continuous/items"
            f"?monitoringLocationNumber={site_id}&f=json"
        )
        flow_data = call_with_retry(flow_url, headers=headers)
        flow_features = flow_data.get("features", [])

        cfs = None
        for f in flow_features:
            props = f.get("properties", {})
            if "value" in props:
                cfs = float(props["value"])
                break

        results.append({
            "name": crossing["name"],
            "gauge_id": site_id,
            "streamflow_cfs": cfs,
            "risk_level": _flow_risk(cfs)
        })

    return {"water": {"crossings": results}}


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in miles between two lat/lon points."""
    r = 3958.8
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return r * 2 * asin(sqrt(a))


def _flow_risk(cfs: float | None) -> str:
    if cfs is None:
        return "unknown"
    if cfs > 500:
        return "high"
    if cfs > 200:
        return "medium"
    return "low"


def _mock_streamflow(crossings: list[dict]) -> dict:
    scenario = mock_scenario()

    if scenario == 3:
        # Scenario 3: dangerous river crossing
        flow_templates = [
            {"streamflow_cfs": 840, "risk_level": "high"},
            {"streamflow_cfs": 620, "risk_level": "high"},
        ]
    elif scenario == 2:
        flow_templates = [
            {"streamflow_cfs": 95, "risk_level": "low"},
        ]
    else:
        flow_templates = [
            {"streamflow_cfs": 120, "risk_level": "low"},
        ]

    results = []
    for i, crossing in enumerate(crossings):
        template = flow_templates[i % len(flow_templates)]
        results.append({
            "name": crossing["name"],
            "gauge_id": f"mock-gauge-{i + 1}",
            **template
        })

    return {"water": {"crossings": results}}
