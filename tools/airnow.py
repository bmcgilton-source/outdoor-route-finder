"""
EPA AirNow AQI forecast tool.
Executes when Claude calls get_air_quality.
"""

import os
from datetime import date, timedelta

from logger import get_logger
from tools.base import CONFIG, call_with_retry, mock_scenario, use_mock

log = get_logger(__name__)

_BASE = CONFIG["apis"]["airnow"]["base_url"]
_AQI_THRESHOLD = CONFIG["thresholds"]["aqi_acceptable"]  # 150


def get_air_quality(latitude: float, longitude: float, start_date: str, end_date: str) -> dict:
    if use_mock():
        return _mock_aqi(start_date, end_date)
    try:
        return _live_aqi(latitude, longitude, start_date, end_date)
    except Exception as e:
        log.warning(f"AirNow unavailable — falling back to mock data. Error: {e}")
        return {**_mock_aqi(start_date, end_date), "_fallback": True, "_error": str(e)}


def _live_aqi(latitude: float, longitude: float, start_date: str, end_date: str) -> dict:
    log.info(f"AirNow: fetching live AQI for ({latitude}, {longitude}) {start_date} to {end_date}")
    api_key = os.getenv("AIRNOW_API_KEY")
    if not api_key:
        raise RuntimeError("AIRNOW_API_KEY not set")

    trip_dates = _date_range(start_date, end_date)
    days = []

    for d in sorted(trip_dates):
        url = (
            f"{_BASE}/aq/forecast/latLong/"
            f"?format=application/json"
            f"&latitude={latitude}"
            f"&longitude={longitude}"
            f"&date={d}"
            f"&distance=25"
            f"&API_KEY={api_key}"
        )
        data = call_with_retry(url)
        # AirNow returns a list; take the PM2.5 or overall entry
        aqi_value = None
        category = "Unknown"
        for entry in data:
            if entry.get("ParameterName") in ("PM2.5", "OZONE", "PM10"):
                aqi_value = entry.get("AQI", -1)
                category = entry.get("Category", {}).get("Name", "Unknown")
                break

        if aqi_value is None or aqi_value < 0:
            aqi_value = 0
            category = "Good"

        days.append({
            "date": d,
            "aqi": aqi_value,
            "category": category,
            "risk_level": _aqi_risk(aqi_value)
        })

    return {"aqi": {"days": days}}


def _date_range(start: str, end: str) -> set:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    return {str(s + timedelta(days=i)) for i in range((e - s).days + 1)}


def _aqi_risk(aqi: int) -> str:
    if aqi > _AQI_THRESHOLD:
        return "high"
    if aqi > 100:
        return "medium"
    return "low"


def _mock_aqi(start_date: str, end_date: str) -> dict:
    scenario = mock_scenario()
    trip_dates = sorted(_date_range(start_date, end_date))

    if scenario == 2:
        # Scenario 2: heavy smoke / high AQI
        base_days = [
            {"aqi": 178, "category": "Unhealthy", "risk_level": "high"},
            {"aqi": 195, "category": "Unhealthy", "risk_level": "high"},
            {"aqi": 162, "category": "Unhealthy", "risk_level": "high"},
            {"aqi": 140, "category": "Unhealthy for Sensitive Groups", "risk_level": "medium"},
        ]
    else:
        # Scenarios 1 & 3: clean air
        base_days = [
            {"aqi": 28, "category": "Good", "risk_level": "low"},
            {"aqi": 32, "category": "Good", "risk_level": "low"},
            {"aqi": 45, "category": "Good", "risk_level": "low"},
            {"aqi": 38, "category": "Good", "risk_level": "low"},
        ]

    days = []
    for i, d in enumerate(trip_dates):
        template = base_days[i % len(base_days)]
        days.append({"date": d, **template})

    return {"aqi": {"days": days}}
