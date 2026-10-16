"""ABS ASGS 2021 Urban Centres and Localities (UCL) for study-area clipping.

Major Urban + Other Urban footprints intersecting the download bbox are used so
bores are kept only inside town/city boundaries, not the full rectangular box.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from location_flags import _rings_from_geometry, point_in_polygon

UCL_SERVICE = "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/UCL/MapServer/0/query"

# Degrees (~50 m). Keeps geometries small enough for a fast point-in-polygon pass.
SIMPLIFY_OFFSET = 0.0005


def _get_json(url: str, params: dict) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(full, headers={"User-Agent": "geotech-data-map/0.1"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ring_bbox(ring: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def fetch_urban_polygons(
    bbox: tuple[float, float, float, float],
) -> tuple[list[dict], list[str]]:
    """Download Major/Other Urban UCL polygons intersecting bbox.

    Returns (polygons, names) where each polygon is
    {"name": str, "rings": [...], "bbox": (min_lon, min_lat, max_lon, max_lat)}.
    """
    envelope = json.dumps({
        "xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[2], "ymax": bbox[3],
        "spatialReference": {"wkid": 4326},
    })
    payload = _get_json(UCL_SERVICE, {
        "where": (
            "state_name_2021='Victoria' AND "
            "sos_name_2021 IN ('Major Urban','Other Urban')"
        ),
        "geometry": envelope,
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "ucl_name_2021,sos_name_2021",
        "returnGeometry": "true",
        "outSR": 4326,
        "f": "geojson",
        "maxAllowableOffset": str(SIMPLIFY_OFFSET),
    })
    polygons: list[dict] = []
    names: list[str] = []
    for feat in payload.get("features", []):
        name = (feat.get("properties") or {}).get("ucl_name_2021") or ""
        if name:
            names.append(name)
        for rings in _rings_from_geometry(feat.get("geometry") or {}):
            if not rings or not rings[0]:
                continue
            polygons.append({
                "name": name,
                "rings": rings,
                "bbox": _ring_bbox(rings[0]),
            })
    names = sorted(set(names))
    return polygons, names


def point_in_urban(lon: float, lat: float, polygons: list[dict]) -> bool:
    for poly in polygons:
        min_lon, min_lat, max_lon, max_lat = poly["bbox"]
        if lon < min_lon or lon > max_lon or lat < min_lat or lat > max_lat:
            continue
        if point_in_polygon(lon, lat, poly["rings"]):
            return True
    return False


def clip_bores_to_study_area(
    bores: dict[str, dict],
    lithology: list[dict],
    polygons: list[dict],
    road_segments: list[dict] | None = None,
    road_index: dict | None = None,
    corridor_m: float = 2000.0,
) -> tuple[dict[str, dict], list[dict], dict[str, int]]:
    """Keep bores inside urban footprints or within corridor_m of a major road."""
    from road_corridors import near_major_road

    use_roads = bool(road_segments and road_index is not None)
    kept_keys: set[str] = set()
    stats = {"urban": 0, "corridor": 0}
    for key, b in bores.items():
        lon, lat = float(b["lon"]), float(b["lat"])
        if point_in_urban(lon, lat, polygons):
            kept_keys.add(key)
            stats["urban"] += 1
        elif use_roads and near_major_road(lon, lat, road_segments, road_index, corridor_m):
            kept_keys.add(key)
            stats["corridor"] += 1
    clipped_bores = {k: v for k, v in bores.items() if k in kept_keys}
    clipped_lith = [row for row in lithology if row["key"] in kept_keys]
    return clipped_bores, clipped_lith, stats
