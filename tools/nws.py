"""
NOAA/NWS weather forecast tool.
Executes when Claude calls get_weather.
"""

from datetime import date, timedelta
from typing import Any

from logger import get_logger
from tools.base import CONFIG, call_with_retry, mock_scenario, use_mock

log = get_logger(__name__)

_BASE = CONFIG["apis"]["nws"]["base_url"]
_HEADERS = CONFIG["apis"]["nws"]["auth"]["headers"]


def get_weather(latitude: float, longitude: float, start_date: str, end_date: str) -> dict:
    if use_mock():
        return _mock_weather(start_date, end_date)
    try:
        return _live_weather(latitude, longitude, start_date, end_date)
    except Exception as e:
        log.warning(f"NWS unavailable — falling back to mock data. Error: {e}")
        return {**_mock_weather(start_date, end_date), "_fallback": True, "_error": str(e)}


def _live_weather(latitude: float, longitude: float, start_date: str, end_date: str) -> dict:
    log.info(f"NWS: fetching live weather for ({latitude}, {longitude}) {start_date} to {end_date}")
    # Step 1: resolve grid coordinates
    points = call_with_retry(
        f"{_BASE}/points/{latitude},{longitude}",
        headers=_HEADERS
    )
    props = points["properties"]
    forecast_url = props["forecast"]
    alerts_url = f"{_BASE}/alerts/active?area=WA"

    # Step 2: get forecast and alerts in parallel (sequential here for simplicity)
    forecast = call_with_retry(forecast_url, headers=_HEADERS)
    alerts_data = call_with_retry(alerts_url, headers=_HEADERS)

    # Step 3: filter forecast periods to trip date range
    trip_dates = _date_range(start_date, end_date)
    days = []
    for period in forecast["properties"]["periods"]:
        period_date = period["startTime"][:10]
        if period_date not in trip_dates or not period["isDaytime"]:
            continue
        precip_chance = (period.get("probabilityOfPrecipitation") or {}).get("value") or 0
        wind_speed = _parse_wind(period.get("windSpeed", "0 mph"))
        risk = _weather_risk(precip_chance, wind_speed)
        days.append({
            "date": period_date,
            "summary": period["shortForecast"],
            "precip_chance": round(precip_chance / 100, 2),
            "high_f": period["temperature"] if period["temperatureUnit"] == "F" else None,
            "wind_mph": wind_speed,
            "risk_level": risk
        })

    alerts = [
        {"event": a["properties"]["event"], "headline": a["properties"]["headline"]}
        for a in alerts_data.get("features", [])
    ]

    return {"weather": {"days": days, "alerts": alerts}}


def _date_range(start: str, end: str) -> set:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    return {str(s + timedelta(days=i)) for i in range((e - s).days + 1)}


def _parse_wind(wind_str: str) -> int:
    try:
        return int(wind_str.split()[0])
    except (ValueError, IndexError):
        return 0


def _weather_risk(precip_chance: float, wind_mph: int) -> str:
    if precip_chance > 60 or wind_mph > 40:
        return "high"
    if precip_chance > 30 or wind_mph > 20:
        return "medium"
    return "low"


def _mock_weather(start_date: str, end_date: str) -> dict:
    scenario = mock_scenario()
    trip_dates = sorted(_date_range(start_date, end_date))

    if scenario == 3:
        # Scenario 3: high weather risk
        base_days = [
            {"summary": "Heavy Rain", "precip_chance": 0.85, "high_f": 52, "wind_mph": 35, "risk_level": "high"},
            {"summary": "Rain Likely", "precip_chance": 0.70, "high_f": 54, "wind_mph": 25, "risk_level": "high"},
            {"summary": "Partly Cloudy", "precip_chance": 0.20, "high_f": 61, "wind_mph": 10, "risk_level": "low"},
            {"summary": "Mostly Sunny", "precip_chance": 0.10, "high_f": 65, "wind_mph": 8, "risk_level": "low"},
        ]
        alerts = [{"event": "Flash Flood Watch", "headline": "Flash Flood Watch in effect through Tuesday evening"}]
    elif scenario == 2:
        # Scenario 2: clear weather, smoke from AQI
        base_days = [
            {"summary": "Sunny", "precip_chance": 0.05, "high_f": 78, "wind_mph": 5, "risk_level": "low"},
            {"summary": "Sunny", "precip_chance": 0.05, "high_f": 80, "wind_mph": 8, "risk_level": "low"},
            {"summary": "Mostly Sunny", "precip_chance": 0.10, "high_f": 76, "wind_mph": 10, "risk_level": "low"},
            {"summary": "Partly Cloudy", "precip_chance": 0.15, "high_f": 72, "wind_mph": 12, "risk_level": "low"},
        ]
        alerts = []
    else:
        # Scenario 1: clean conditions
        base_days = [
            {"summary": "Sunny", "precip_chance": 0.05, "high_f": 72, "wind_mph": 8, "risk_level": "low"},
            {"summary": "Mostly Sunny", "precip_chance": 0.10, "high_f": 70, "wind_mph": 10, "risk_level": "low"},
            {"summary": "Partly Cloudy", "precip_chance": 0.20, "high_f": 68, "wind_mph": 12, "risk_level": "low"},
            {"summary": "Mostly Sunny", "precip_chance": 0.10, "high_f": 71, "wind_mph": 9, "risk_level": "low"},
        ]
        alerts = []

    days = []
    for i, d in enumerate(trip_dates):
        template = base_days[i % len(base_days)]
        days.append({"date": d, **template})

    return {"weather": {"days": days, "alerts": alerts}}
