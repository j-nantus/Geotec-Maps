"""Flag bores whose coordinates look wrong (in Port Phillip Bay, or outside parish)."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

# Approximate open-water Port Phillip Bay, inset ~1–2 km from the foreshore so
# beach / pier investigation bores are not flagged. Vertices are lon, lat.
PORT_PHILLIP_OPEN_WATER = [
    (144.78, -37.90),
    (144.90, -37.90),
    (144.97, -37.93),
    (145.00, -37.98),
    (145.02, -38.06),
    (145.04, -38.14),
    (145.00, -38.20),
    (144.88, -38.22),
    (144.78, -38.18),
    (144.72, -38.10),
    (144.70, -38.00),
    (144.74, -37.94),
    (144.78, -37.90),
]

PARISH_SERVICE = (
    "https://corp-gis.mapshare.vic.gov.au/arcgis/rest/services/"
    "Mapshare/Boundary/MapServer/1/query"
)


def point_in_ring(lon: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-cast point-in-polygon for a closed ring of (lon, lat)."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-18) + xi):
            inside = not inside
        j = i
    return inside


def point_in_polygon(lon: float, lat: float, rings: list[list[tuple[float, float]]]) -> bool:
    """True if point is in outer ring and not in any hole (rings[1:])."""
    if not rings or not point_in_ring(lon, lat, rings[0]):
        return False
    for hole in rings[1:]:
        if point_in_ring(lon, lat, hole):
            return False
    return True


def _rings_from_geometry(geom: dict) -> list[list[list[tuple[float, float]]]]:
    """Return list of polygons, each as list of rings of (lon, lat)."""
    if not geom:
        return []
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if gtype == "Polygon":
        return [[[(c[0], c[1]) for c in ring] for ring in coords]]
    if gtype == "MultiPolygon":
        return [[[(c[0], c[1]) for c in ring] for ring in poly] for poly in coords]
    # Esri JSON
    if "rings" in geom:
        return [[[(c[0], c[1]) for c in ring] for ring in geom["rings"]]]
    return []


def in_open_water(lon: float, lat: float) -> bool:
    return point_in_ring(lon, lat, PORT_PHILLIP_OPEN_WATER)


def _get_json(url: str, params: dict) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(full, headers={"User-Agent": "geotech-data-map/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_parish_polygons(names: set[str]) -> dict[str, list[list[list[tuple[float, float]]]]]:
    """Map normalised parish name -> list of polygons (each a list of rings)."""
    out: dict[str, list[list[list[tuple[float, float]]]]] = {}
    for name in sorted(n for n in names if n):
        key = name.upper()
        # Bore records use title case with trailing spaces; Vicmap uses various cases.
        where = f"UPPER(parish_name)='{key.replace(chr(39), chr(39)+chr(39))}'"
        try:
            payload = _get_json(PARISH_SERVICE, {
                "where": where,
                "outFields": "parish_name",
                "returnGeometry": "true",
                "outSR": 4326,
                "f": "geojson",
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  parish {name!r}: download failed ({exc})")
            continue
        polys: list[list[list[tuple[float, float]]]] = []
        for feat in payload.get("features", []):
            polys.extend(_rings_from_geometry(feat.get("geometry") or {}))
        if polys:
            out[key] = polys
            print(f"  parish {name}: {len(polys)} polygon(s)")
        else:
            print(f"  parish {name}: not found in Vicmap")
    return out


def outside_parish(
    lon: float,
    lat: float,
    parish: str,
    parish_polys: dict[str, list[list[list[tuple[float, float]]]]],
) -> bool:
    key = parish.upper().strip()
    if not key or key not in parish_polys:
        return False  # no parish recorded, or boundary unavailable — do not flag
    for poly in parish_polys[key]:
        if point_in_polygon(lon, lat, poly):
            return False
    return True


def flag_bore(
    lon: float,
    lat: float,
    parish: str,
    parish_polys: dict[str, list[list[list[tuple[float, float]]]]],
) -> tuple[bool, bool]:
    """Return (in_water, outside_parish)."""
    return (
        in_open_water(lon, lat),
        outside_parish(lon, lat, parish, parish_polys),
    )
