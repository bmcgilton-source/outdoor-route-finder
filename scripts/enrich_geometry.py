#!/usr/bin/env python3
"""
Enrich routes with trail geometry from OpenStreetMap via Overpass API.

For each route:
  1. Query Overpass for trail ways by name within the bounding box
  2. Fall back to all path/track ways in bbox if name search finds nothing
  3. Chain ways into a continuous polyline
  4. Downsample with Ramer-Douglas-Peucker
  5. Write to data/geometry/{route-id}.json

Usage:
    python scripts/enrich_geometry.py              # all routes
    python scripts/enrich_geometry.py goat-rocks-snowgrass maple-pass-loop
    python scripts/enrich_geometry.py --dry-run    # show query plan only
"""

import json
import math
import sys
import time
from pathlib import Path

import requests

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT    = Path(__file__).parent.parent
ROUTES_PATH  = REPO_ROOT / "data" / "routes.json"
GEOMETRY_DIR = REPO_ROOT / "data" / "geometry"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# ── Tuning ────────────────────────────────────────────────────────────────────

# Perpendicular distance threshold in degrees for RDP simplification.
# 0.0001° ≈ 11m — enough precision for trail-map zoom levels.
RDP_EPSILON = 0.0001

# Words stripped from route name before building the OSM name search regex.
_STRIP_WORDS = {
    "loop", "trail", "trails", "traverse", "via", "wilderness",
    "route", "path", "peak", "lookout", "flat", "arm", "lake",
}

# ── Overpass queries ──────────────────────────────────────────────────────────

def _bbox_str(bb: dict) -> str:
    return f"{bb['min_lat']},{bb['min_lon']},{bb['max_lat']},{bb['max_lon']}"


def _name_keywords(route_name: str) -> list[str]:
    """Extract meaningful words from the route name for OSM name search."""
    words = []
    for token in route_name.replace("—", " ").replace("-", " ").split():
        word = token.strip(".,()").lower()
        if len(word) >= 4 and word not in _STRIP_WORDS:
            words.append(token.strip(".,()"))
    return words


def _overpass_name_query(bb: dict, keywords: list[str]) -> str:
    """Query ways whose name contains ANY of the keywords (case-insensitive)."""
    pattern = "|".join(keywords)
    bbox = _bbox_str(bb)
    return f"""
[out:json][timeout:40];
(
  way["highway"~"path|track|footway"]["name"~"{pattern}",i]({bbox});
);
out geom;
"""


def _overpass_bbox_query(bb: dict) -> str:
    """Query all path/track ways in the bounding box (fallback)."""
    bbox = _bbox_str(bb)
    return f"""
[out:json][timeout:40];
(
  way["highway"~"path|track|footway"]({bbox});
);
out geom;
"""


def _run_overpass(query: str) -> list[dict]:
    resp = requests.post(
        OVERPASS_URL,
        data={"data": query},
        timeout=50,
        headers={"User-Agent": "TrailOps-GeometryEnricher/1.0"},
    )
    resp.raise_for_status()
    return resp.json().get("elements", [])


# ── Geometry processing ───────────────────────────────────────────────────────

def _chain_ways(elements: list[dict]) -> list[tuple[float, float]]:
    """
    Chain OSM ways (each with embedded geometry) into a single ordered polyline.
    Uses a greedy nearest-endpoint algorithm to connect segments.
    """
    segments = []
    for el in elements:
        if el.get("type") == "way" and el.get("geometry"):
            pts = [(n["lat"], n["lon"]) for n in el["geometry"]]
            if len(pts) >= 2:
                segments.append(pts)

    if not segments:
        return []
    if len(segments) == 1:
        return segments[0]

    # Start with the longest segment (most likely the main trail)
    segments.sort(key=len, reverse=True)
    chained = list(segments.pop(0))

    while segments:
        last = chained[-1]
        best_i, best_dist, best_reverse = 0, float("inf"), False
        for i, seg in enumerate(segments):
            d_fwd = _dist(last, seg[0])
            d_rev = _dist(last, seg[-1])
            if d_fwd < best_dist:
                best_i, best_dist, best_reverse = i, d_fwd, False
            if d_rev < best_dist:
                best_i, best_dist, best_reverse = i, d_rev, True
        seg = segments.pop(best_i)
        if best_reverse:
            seg = list(reversed(seg))
        # Skip duplicate junction point if endpoints are very close
        if _dist(last, seg[0]) < 0.00005:
            chained.extend(seg[1:])
        else:
            chained.extend(seg)

    return chained


def _dist(a: tuple, b: tuple) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _point_to_segment_dist(p: tuple, a: tuple, b: tuple) -> float:
    """Perpendicular distance from point p to line segment a–b."""
    if a == b:
        return _dist(p, a)
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    proj = (a[0] + t * dx, a[1] + t * dy)
    return _dist(p, proj)


def _rdp(points: list[tuple], epsilon: float) -> list[tuple]:
    """Ramer-Douglas-Peucker polyline simplification."""
    if len(points) < 3:
        return points
    max_dist, max_idx = 0.0, 0
    for i in range(1, len(points) - 1):
        d = _point_to_segment_dist(points[i], points[0], points[-1])
        if d > max_dist:
            max_dist, max_idx = d, i
    if max_dist > epsilon:
        left  = _rdp(points[:max_idx + 1], epsilon)
        right = _rdp(points[max_idx:], epsilon)
        return left[:-1] + right
    return [points[0], points[-1]]


# ── Per-route processing ──────────────────────────────────────────────────────

def process_route(route: dict, dry_run: bool = False) -> str:
    """
    Fetch, simplify, and save geometry for one route.
    Returns: 'ok' | 'fallback' | 'empty' | 'dry_run'
    """
    bb       = route["bounding_box"]
    keywords = _name_keywords(route["name"])
    route_id = route["id"]

    print(f"  Keywords: {keywords}")

    if dry_run:
        print(f"  [dry-run] Would query Overpass, write data/geometry/{route_id}.json")
        return "dry_run"

    # Pass 1: name-based search
    elements = []
    if keywords:
        try:
            q = _overpass_name_query(bb, keywords)
            elements = _run_overpass(q)
            print(f"  Name search: {len(elements)} way(s) found")
        except Exception as e:
            print(f"  Name search failed: {e}")

    used_fallback = False

    # Pass 2: bbox fallback if name search found nothing
    if not elements:
        print("  Falling back to bbox query…")
        used_fallback = True
        try:
            q = _overpass_bbox_query(bb)
            elements = _run_overpass(q)
            print(f"  Bbox query: {len(elements)} way(s) found")
        except Exception as e:
            print(f"  Bbox query failed: {e}")

    if not elements:
        print("  WARNING: No geometry found — skipping")
        return "empty"

    coords     = _chain_ways(elements)
    simplified = _rdp(coords, RDP_EPSILON)

    print(f"  Chained: {len(coords)} pts  →  RDP: {len(simplified)} pts")

    geometry = [
        {"lat": round(lat, 6), "lon": round(lon, 6)}
        for lat, lon in simplified
    ]

    out_path = GEOMETRY_DIR / f"{route_id}.json"
    out_path.write_text(json.dumps(geometry, indent=2))
    print(f"  Saved: {out_path}")

    return "fallback" if used_fallback else "ok"


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    GEOMETRY_DIR.mkdir(parents=True, exist_ok=True)

    args    = sys.argv[1:]
    dry_run = "--dry-run" in args
    targets = [a for a in args if not a.startswith("--")]

    routes = json.loads(ROUTES_PATH.read_text())["routes"]

    if targets:
        routes = [r for r in routes if r["id"] in targets]
        if not routes:
            print(f"No routes matched: {targets}")
            sys.exit(1)

    # Skip ad-hoc routes — they have no bounding_box and aren't permanent
    routes = [r for r in routes if "bounding_box" in r]

    results: dict[str, str] = {}

    for i, route in enumerate(routes):
        print(f"\n[{i + 1}/{len(routes)}] {route['id']}")
        results[route["id"]] = process_route(route, dry_run=dry_run)
        if i < len(routes) - 1 and not dry_run:
            time.sleep(1.5)  # be polite to the public Overpass instance

    print("\n-- Summary ----------------------------------")
    for rid, status in results.items():
        icon = {"ok": "✓", "fallback": "~", "empty": "✗", "dry_run": "?"}.get(status, "?")
        print(f"  {icon}  {rid:<35}  {status}")

    empties = [rid for rid, s in results.items() if s == "empty"]
    if empties:
        print(f"\n  {len(empties)} route(s) need manual geometry — check OSM for their relation IDs")


if __name__ == "__main__":
    main()
