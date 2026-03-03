"""
Wildlife Data Tool — queries iNaturalist for recent bear and cougar sightings near a route.

Uses the iNaturalist observations API (no key required for read-only access).
Queries the route bounding box for research-grade observations in the past 30 days.
"""

from datetime import date, timedelta

from logger import get_logger
from tools.base import call_with_retry, mock_scenario, use_mock

log = get_logger(__name__)

_BASE_URL  = "https://api.inaturalist.org/v1/observations"
_DAYS_BACK = 30  # look-back window for "recent" sightings


def get_wildlife(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> dict:
    """Return recent bear and cougar sightings within the route bounding box."""
    if use_mock():
        return _mock_wildlife()
    try:
        return _live_wildlife(min_lat, max_lat, min_lon, max_lon)
    except Exception as e:
        log.warning(f"iNaturalist API failed ({e}) — returning empty wildlife data")
        return {
            "recent_sightings": [],
            "bear_count": 0,
            "cougar_count": 0,
            "risk_level": "low",
            "notes": "Wildlife data unavailable. Check with the local ranger station for recent activity.",
            "_days_back": _DAYS_BACK,
            "_error": str(e),
        }


def _live_wildlife(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> dict:
    today = date.today()
    base_params = {
        "swlat": min_lat,
        "swlng": min_lon,
        "nelat": max_lat,
        "nelng": max_lon,
        "d1": (today - timedelta(days=_DAYS_BACK)).isoformat(),
        "d2": today.isoformat(),
        "quality_grade": "research",
        "per_page": 50,
        "order": "desc",
        "order_by": "created_at",
    }

    bears   = _query_taxon(base_params, taxon_name="Ursus",        label="Bear")
    cougars = _query_taxon(base_params, taxon_name="Puma concolor", label="Cougar")

    bear_count   = len(bears)
    cougar_count = len(cougars)
    risk         = _risk_level(bear_count, cougar_count)

    return {
        "recent_sightings": bears + cougars,
        "bear_count":   bear_count,
        "cougar_count": cougar_count,
        "risk_level":   risk,
        "notes":        _build_notes(bear_count, cougar_count, risk),
        "_days_back":   _DAYS_BACK,
    }


def _query_taxon(base_params: dict, taxon_name: str, label: str) -> list:
    """Query iNaturalist for a single taxon. Returns a list of sighting dicts."""
    params = {**base_params, "taxon_name": taxon_name}
    try:
        data    = call_with_retry(_BASE_URL, params=params)
        results = data.get("results", [])
    except Exception as e:
        log.warning(f"iNaturalist: {taxon_name} query failed ({e})")
        return []

    sightings = []
    for obs in results:
        lat, lon = None, None
        coords = obs.get("location", "")
        if coords and "," in coords:
            try:
                lat, lon = (float(x) for x in coords.split(",", 1))
            except ValueError:
                pass
        sightings.append({
            "species": label,
            "taxon":   obs.get("taxon", {}).get("name", taxon_name),
            "date":    obs.get("observed_on", ""),
            "place":   obs.get("place_guess", ""),
            "lat":     lat,
            "lon":     lon,
        })
    return sightings


def _risk_level(bear_count: int, cougar_count: int) -> str:
    if cougar_count > 0 or bear_count >= 3:
        return "high"
    if bear_count >= 1:
        return "medium"
    return "low"


def _build_notes(bear_count: int, cougar_count: int, risk: str) -> str:
    parts = []
    if bear_count:
        parts.append(f"{bear_count} bear sighting{'s' if bear_count != 1 else ''} in the last 30 days")
    if cougar_count:
        parts.append(f"{cougar_count} cougar sighting{'s' if cougar_count != 1 else ''} in the last 30 days")
    if not parts:
        return "No bear or cougar sightings reported in the last 30 days. Standard wildlife precautions apply."
    base = ". ".join(p.capitalize() for p in parts) + "."
    if risk == "high":
        return base + " Carry bear spray and practice bear-safe camp hygiene. High wildlife activity."
    return base + " Carry bear spray. Store food properly."


def _mock_wildlife() -> dict:
    scenario = mock_scenario()
    if scenario == 1:
        # Goat Rocks — one bear sighting, medium risk
        return {
            "recent_sightings": [
                {"species": "Bear", "taxon": "Ursus americanus", "date": "2024-07-12",
                 "place": "Snowgrass Flat", "lat": 46.43, "lon": -121.53},
            ],
            "bear_count":   1,
            "cougar_count": 0,
            "risk_level":   "medium",
            "notes": "1 bear sighting in the last 30 days near Snowgrass Flat. Carry bear spray. Store food properly.",
            "_days_back": _DAYS_BACK,
            "_mock": True,
        }
    elif scenario == 2:
        # Enchantments — no recent wildlife (fire/smoke is the concern)
        return {
            "recent_sightings": [],
            "bear_count":   0,
            "cougar_count": 0,
            "risk_level":   "low",
            "notes": "No bear or cougar sightings reported in the last 30 days. Standard wildlife precautions apply.",
            "_days_back": _DAYS_BACK,
            "_mock": True,
        }
    else:
        # Olympic High Divide — active bear + cougar area, high risk
        return {
            "recent_sightings": [
                {"species": "Bear", "taxon": "Ursus americanus", "date": "2024-07-18",
                 "place": "Seven Lakes Basin", "lat": 47.93, "lon": -123.72},
                {"species": "Bear", "taxon": "Ursus americanus", "date": "2024-07-15",
                 "place": "High Divide Trail", "lat": 47.95, "lon": -123.74},
                {"species": "Cougar", "taxon": "Puma concolor", "date": "2024-07-10",
                 "place": "Sol Duc drainage", "lat": 47.98, "lon": -123.80},
            ],
            "bear_count":   2,
            "cougar_count": 1,
            "risk_level":   "high",
            "notes": "2 bear sightings and 1 cougar sighting in the last 30 days. Carry bear spray and practice bear-safe camp hygiene. High wildlife activity.",
            "_days_back": _DAYS_BACK,
            "_mock": True,
        }
