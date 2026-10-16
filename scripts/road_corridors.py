"""Major-road corridors linking towns (Vicmap Transport TR_ROAD).

Freeways, highways, and numbered arterials are buffered so bores along routes
between urban centres are kept even when they fall outside ABS UCL footprints.
"""

from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from collections import defaultdict

ROAD_SERVICE = (
    "https://core-gis.mapshare.vic.gov.au/arcgis/rest/services/"
    "Mapshare/TRRoad/MapServer/0/query"
)

# Freeway (0), Highway (1), or Arterial (2) with a route number (M/A/B/C…).
ROAD_WHERE = (
    "class_code IN (0,1) OR (class_code = 2 AND route_no IS NOT NULL)"
)
PAGE_SIZE = 2000
SIMPLIFY_OFFSET = 0.001  # ~100 m

# Corridor half-width around road centreline.
DEFAULT_CORRIDOR_M = 2000.0

# Spatial hash cell size (~ corridor width).
CELL_DEG = 0.02


def _get_json(url: str, params: dict, retries: int = 4) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "geotech-data-map/0.1"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if "error" in payload:
                raise RuntimeError(payload["error"])
            return payload
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f"  road retry in {wait}s after error: {exc}")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _lines_from_geometry(geom: dict) -> list[list[tuple[float, float]]]:
    if not geom:
        return []
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if gtype == "LineString":
        return [[(c[0], c[1]) for c in coords]]
    if gtype == "MultiLineString":
        return [[(c[0], c[1]) for c in line] for line in coords]
    # Esri JSON
    if "paths" in geom:
        return [[(c[0], c[1]) for c in path] for path in geom["paths"]]
    return []


def fetch_major_roads(bbox: tuple[float, float, float, float]) -> list[dict]:
    """Return road segments as {points, bbox} dicts."""
    envelope = json.dumps({
        "xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[2], "ymax": bbox[3],
        "spatialReference": {"wkid": 4326},
    })
    segments: list[dict] = []
    offset = 0
    while True:
        payload = _get_json(ROAD_SERVICE, {
            "where": ROAD_WHERE,
            "geometry": envelope,
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "class_code,route_no,ezi_road_name",
            "returnGeometry": "true",
            "outSR": 4326,
            "f": "geojson",
            "maxAllowableOffset": str(SIMPLIFY_OFFSET),
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
        })
        features = payload.get("features") or []
        for feat in features:
            for points in _lines_from_geometry(feat.get("geometry") or {}):
                if len(points) < 2:
                    continue
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                segments.append({
                    "points": points,
                    "bbox": (min(xs), min(ys), max(xs), max(ys)),
                })
        print(f"  roads: {offset + len(features)} features ({len(segments)} segments)")
        if len(features) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        if offset > 200_000:
            break
    return segments


def _metres_per_degree(lat: float) -> tuple[float, float]:
    m_lat = 111_320.0
    m_lon = 111_320.0 * math.cos(math.radians(lat))
    return m_lon, m_lat


def _dist_point_to_segment_m(
    lon: float, lat: float,
    x1: float, y1: float, x2: float, y2: float,
) -> float:
    m_lon, m_lat = _metres_per_degree(lat)
    px, py = lon * m_lon, lat * m_lat
    ax, ay = x1 * m_lon, y1 * m_lat
    bx, by = x2 * m_lon, y2 * m_lat
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _dist_point_to_polyline_m(lon: float, lat: float, points: list[tuple[float, float]]) -> float:
    best = float("inf")
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        d = _dist_point_to_segment_m(lon, lat, x1, y1, x2, y2)
        if d < best:
            best = d
    return best


def build_road_index(segments: list[dict]) -> dict[tuple[int, int], list[int]]:
    index: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, seg in enumerate(segments):
        min_lon, min_lat, max_lon, max_lat = seg["bbox"]
        c0 = int(math.floor(min_lon / CELL_DEG))
        c1 = int(math.floor(max_lon / CELL_DEG))
        r0 = int(math.floor(min_lat / CELL_DEG))
        r1 = int(math.floor(max_lat / CELL_DEG))
        for c in range(c0, c1 + 1):
            for r in range(r0, r1 + 1):
                index[(c, r)].append(i)
    return index


def near_major_road(
    lon: float,
    lat: float,
    segments: list[dict],
    index: dict[tuple[int, int], list[int]],
    max_m: float = DEFAULT_CORRIDOR_M,
) -> bool:
    m_lon, m_lat = _metres_per_degree(lat)
    pad_lon = max_m / max(m_lon, 1.0)
    pad_lat = max_m / m_lat
    c0 = int(math.floor((lon - pad_lon) / CELL_DEG))
    c1 = int(math.floor((lon + pad_lon) / CELL_DEG))
    r0 = int(math.floor((lat - pad_lat) / CELL_DEG))
    r1 = int(math.floor((lat + pad_lat) / CELL_DEG))
    seen: set[int] = set()
    for c in range(c0, c1 + 1):
        for r in range(r0, r1 + 1):
            for i in index.get((c, r), ()):
                if i in seen:
                    continue
                seen.add(i)
                seg = segments[i]
                min_lon, min_lat, max_lon, max_lat = seg["bbox"]
                if (lon < min_lon - pad_lon or lon > max_lon + pad_lon
                        or lat < min_lat - pad_lat or lat > max_lat + pad_lat):
                    continue
                if _dist_point_to_polyline_m(lon, lat, seg["points"]) <= max_m:
                    return True
    return False
