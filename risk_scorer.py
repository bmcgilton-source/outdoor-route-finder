"""
Risk Scorer — deterministic code, not a Claude call.

Scores each trip day from conditions data and sets overall trip risk.
Writes risk output to trip_context["risk"].

Risk levels: low=0, medium=1, high=2
Replanning is triggered if overall_risk >= 1 (medium or high).
"""

from logger import get_logger

log = get_logger(__name__)

_LEVEL = {"low": 0, "medium": 1, "high": 2, "unknown": 0}
_REVERSE = {0: "low", 1: "medium", 2: "high"}


def score(trip_context: dict) -> dict:
    """
    Score all trip days and set overall risk.

    Reads from trip_context:
      - conditions (weather, aqi, fire, water)
      - itinerary.days

    Writes to trip_context:
      - risk

    Returns: updated trip_context
    """
    conditions = trip_context.get("conditions", {})
    days = trip_context.get("itinerary", {}).get("days", [])

    weather_by_date = {
        d["date"]: d for d in conditions.get("weather", {}).get("days", [])
    }
    aqi_by_date = {
        d["date"]: d for d in conditions.get("aqi", {}).get("days", [])
    }
    fire_risk_level = conditions.get("fire", {}).get("risk_level", "low")
    water_crossings = conditions.get("water", {}).get("crossings", [])

    # Overall water risk is the worst crossing on any day
    water_risk_level = _worst_risk([c.get("risk_level", "low") for c in water_crossings])

    scored_days = []
    for day in days:
        date = day.get("date", "")
        w = weather_by_date.get(date, {})
        a = aqi_by_date.get(date, {})

        weather_score = _LEVEL.get(w.get("risk_level", "low"), 0)
        aqi_score = _LEVEL.get(a.get("risk_level", "low"), 0)
        fire_score = _LEVEL.get(fire_risk_level, 0)
        water_score = _LEVEL.get(water_risk_level, 0)

        day_score = max(weather_score, aqi_score, fire_score, water_score)

        scored_days.append({
            "day": day.get("day"),
            "date": date,
            "risk_level": _REVERSE[day_score],
            "factors": {
                "weather": _REVERSE[weather_score],
                "aqi": _REVERSE[aqi_score],
                "fire": _REVERSE[fire_score],
                "water": _REVERSE[water_score],
            },
        })

    overall_score = max((d["risk_level"] for d in scored_days), key=lambda r: _LEVEL[r]) \
        if scored_days else "low"
    # If no days (e.g. parse error), fall back to component max
    if not scored_days:
        overall_score = _REVERSE[max(
            _LEVEL.get(fire_risk_level, 0),
            _LEVEL.get(water_risk_level, 0),
        )]

    dominant = _dominant_factor(scored_days)

    trip_context["risk"] = {
        "days": scored_days,
        "overall_risk": overall_score,
        "dominant_factor": dominant,
        "replanning_required": _LEVEL[overall_score] >= 1,
    }

    log.info(f"Risk Scorer: {overall_score.upper()} (dominant: {dominant}, replanning: {trip_context['risk']['replanning_required']})")
    trip_context.setdefault("reasoning_trace", []).append({
        "agent": "risk_scorer",
        "event": "complete",
        "overall_risk": overall_score,
        "replanning_required": trip_context["risk"]["replanning_required"],
        "dominant_factor": dominant,
    })

    return trip_context


def _worst_risk(levels: list[str]) -> str:
    if not levels:
        return "low"
    return _REVERSE[max(_LEVEL.get(r, 0) for r in levels)]


def _dominant_factor(scored_days: list[dict]) -> str | None:
    """Return the factor that produced the highest risk score, or None if all low."""
    factor_max = {"weather": 0, "aqi": 0, "fire": 0, "water": 0}
    for day in scored_days:
        for factor, level in day.get("factors", {}).items():
            factor_max[factor] = max(factor_max[factor], _LEVEL.get(level, 0))

    best_score = max(factor_max.values())
    if best_score == 0:
        return None
    # Return the factor with the highest score (first alphabetically on tie)
    return next(f for f, s in sorted(factor_max.items()) if s == best_score)
