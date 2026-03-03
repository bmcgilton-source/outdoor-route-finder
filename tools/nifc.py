"""
NIFC wildfire perimeter tool.
Executes when Claude calls get_fire_data.
"""

from math import asin, cos, radians, sin, sqrt

from logger import get_logger
from tools.base import CONFIG, call_with_retry, mock_scenario, use_mock

log = get_logger(__name__)

_BASE = CONFIG["apis"]["nifc"]["base_url"]
_DEFAULT_PARAMS = CONFIG["apis"]["nifc"]["default_query_params"]


def get_fire_data(
    min_lat: float, max_lat: float,
    min_lon: float, max_lon: float,
    trailhead_lat: float, trailhead_lon: float
) -> dict:
    if use_mock():
        return _mock_fire(trailhead_lat, trailhead_lon)
    try:
        return _live_fire(min_lat, max_lat, min_lon, max_lon, trailhead_lat, trailhead_lon)
    except Exception as e:
        log.warning(f"NIFC unavailable — falling back to mock data. Error: {e}")
        return {**_mock_fire(trailhead_lat, trailhead_lon), "_fallback": True, "_error": str(e)}


def _live_fire(
    min_lat: float, max_lat: float,
    min_lon: float, max_lon: float,
    trailhead_lat: float, trailhead_lon: float
) -> dict:
    log.info(f"NIFC: fetching live fire perimeters for bbox ({min_lat},{min_lon}) to ({max_lat},{max_lon})")
    # ArcGIS envelope geometry: xmin,ymin,xmax,ymax
    geometry = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    url = f"{_BASE}{CONFIG['apis']['nifc']['endpoints']['current_perimeters']}"

    params = {
        "where": "1=1",
        "geometry": geometry,
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "IncidentName,GISAcres,CreateDate,PerimeterCategory",
        "f": "geojson"
    }

    data = call_with_retry(url, params=params)
    features = data.get("features", [])

    fires = []
    closest_miles = None

    for feature in features:
        props = feature.get("properties", {})
        name = props.get("IncidentName", "Unknown Fire")
        acres = props.get("GISAcres", 0)

        # Use centroid of bounding box for distance approximation
        geom = feature.get("geometry", {})
        coords = geom.get("coordinates", [])
        fire_lat, fire_lon = _centroid(coords, geom.get("type", ""))

        if fire_lat and fire_lon:
            dist = _haversine(trailhead_lat, trailhead_lon, fire_lat, fire_lon)
            if closest_miles is None or dist < closest_miles:
                closest_miles = round(dist, 1)
            fires.append({"name": name, "acres": acres, "distance_miles": round(dist, 1)})

    return {
        "fire": {
            "active_fires_nearby": fires,
            "closest_fire_miles": closest_miles,
            "risk_level": _fire_risk(closest_miles)
        }
    }


def _centroid(coords: list, geom_type: str) -> tuple:
    """Rough centroid from first ring of polygon coordinates."""
    try:
        if geom_type == "Polygon":
            ring = coords[0]
        elif geom_type == "MultiPolygon":
            ring = coords[0][0]
        else:
            return None, None
        lats = [c[1] for c in ring]
        lons = [c[0] for c in ring]
        return sum(lats) / len(lats), sum(lons) / len(lons)
    except (IndexError, TypeError):
        return None, None


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return r * 2 * asin(sqrt(a))


def _fire_risk(closest_miles: float | None) -> str:
    if closest_miles is None:
        return "low"
    if closest_miles <= 5:
        return "high"
    if closest_miles <= 15:
        return "medium"
    return "low"


def _mock_fire(trailhead_lat: float, trailhead_lon: float) -> dict:
    scenario = mock_scenario()

    if scenario == 2:
        # Scenario 2: active fire causing smoke/AQI issues nearby
        fires = [{"name": "Chelan Complex", "acres": 42000, "distance_miles": 12.4}]
        closest = 12.4
    elif scenario == 3:
        # Scenario 3: no fire, weather is the risk
        fires = []
        closest = None
    else:
        # Scenario 1: clean
        fires = []
        closest = None

    return {
        "fire": {
            "active_fires_nearby": fires,
            "closest_fire_miles": closest,
            "risk_level": _fire_risk(closest)
        }
    }
