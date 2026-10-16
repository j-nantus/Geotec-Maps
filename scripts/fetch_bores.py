"""Download Victorian groundwater bore locations and lithology logs for an area.

Source: DEECA "Victorian Groundwater Bores" ArcGIS map service (CC BY 4.0).
Bores are first pulled for a coarse download box, then kept if they fall inside
ABS ASGS 2021 Urban Centres and Localities (Major Urban + Other Urban) or within
a buffer of major Vicmap roads (freeway / highway / numbered arterial) linking
those towns.

Writes data/bores.csv and data/lithology.csv in a common format.

Usage:
    python fetch_bores.py                       # towns/cities + road corridors
    python fetch_bores.py --bbox 144.8 -37.9 145.1 -37.7
    python fetch_bores.py --no-urban-clip       # keep full rectangular box
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from road_corridors import DEFAULT_CORRIDOR_M, build_road_index, fetch_major_roads
from urban_areas import clip_bores_to_study_area, fetch_urban_polygons

SERVICE = (
    "https://corp-gis.mapshare.vic.gov.au/arcgis/rest/services/"
    "GroundwaterBores/GWBores/MapServer"
)

# Download envelope wide enough for full Ballarat UCL (west edge ~143.76) through
# Warragul, and Anglesea / Western Port. Final keep-set is urban + road corridors.
MELBOURNE_BBOX = (143.70, -38.60, 146.10, -37.25)

PAGE_SIZE = 2000

BORE_LAYERS = {
    "monitoring": 12,
    "historic": 42,
    "register": 43,
}
LITHOLOGY_LAYERS = {
    "monitoring": 7,
    "historic": 47,
    "register": 3,
}

# Lower number wins when a bore has more than one log.
LOG_PRIORITY = {
    ("drillers log", "primary interpretation"): 0,
    ("geologists log", "primary geological log"): 1,
    ("geologists log", "interpretation from hole"): 2,
    ("drillers log", "secondary interpretation"): 3,
}

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _get_json(url: str, params: dict, retries: int = 4) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "geotech-data-map/0.1"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if "error" in payload:
                raise RuntimeError(payload["error"])
            return payload
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f"  retry in {wait}s after error: {exc}", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def fetch_layer(layer_id: int, bbox: tuple[float, float, float, float]) -> list[dict]:
    """Return every feature in the bbox as attribute dicts with lon/lat added."""
    envelope = json.dumps(
        {"xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[2], "ymax": bbox[3],
         "spatialReference": {"wkid": 4326}}
    )
    url = f"{SERVICE}/{layer_id}/query"
    base = {
        "where": "1=1",
        "geometry": envelope,
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "outSR": 4326,
        "returnGeometry": "true",
        "orderByFields": "OBJECTID",
        "resultRecordCount": PAGE_SIZE,
        "f": "json",
    }
    rows: list[dict] = []
    offset = 0
    while True:
        payload = _get_json(url, {**base, "resultOffset": offset})
        feats = payload.get("features", [])
        for f in feats:
            attrs = dict(f.get("attributes", {}))
            geom = f.get("geometry") or {}
            attrs["_lon"] = geom.get("x")
            attrs["_lat"] = geom.get("y")
            rows.append(attrs)
        print(f"  layer {layer_id}: {len(rows)} records", end="\r")
        if not feats or not payload.get("exceededTransferLimit", len(feats) == PAGE_SIZE):
            break
        offset += len(feats)
    print()
    return rows


def _s(value) -> str:
    return "" if value is None else str(value).strip().strip('"')


def _f(value) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _date(ms) -> str:
    if ms in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def normalise_bores(raw: dict[str, list[dict]]) -> dict[str, dict]:
    bores: dict[str, dict] = {}
    # Historic first so monitoring records (better maintained) overwrite duplicates.
    for dataset in ("historic", "monitoring"):
        for r in raw[dataset]:
            bore_id = _s(r.get("boreid"))
            if not bore_id or r["_lat"] is None:
                continue
            bores[f"VGB-{bore_id}"] = {
                "key": f"VGB-{bore_id}",
                "bore_id": bore_id,
                "dataset": dataset,
                "lat": r["_lat"],
                "lon": r["_lon"],
                "depth_m": _f(r.get("depth_of_bore_m")),
                "drilled": _date(r.get("drillenddate") or r.get("drillstartdate")),
                "use": _s(r.get("use")).rstrip(","),
                "position_accuracy": _s(r.get("positonaccuracy")),
                "driller": _s(r.get("drillername")),
                "wmis_url": _s(r.get("wmis_url")),
                "parish": _s(r.get("parish")),
            }
    for r in raw["register"]:
        report_id = _s(r.get("reportid"))
        if not report_id or r["_lat"] is None:
            continue
        bores[f"REG-{report_id}"] = {
            "key": f"REG-{report_id}",
            "bore_id": _s(r.get("station")) or report_id,
            "dataset": "register",
            "lat": r["_lat"],
            "lon": r["_lon"],
            "depth_m": _f(r.get("depthcompl")),
            "drilled": _date(r.get("enddate") or r.get("startdate")),
            "use": _s(r.get("boreuse")),
            "position_accuracy": "Water Register (since 2017)",
            "driller": _s(r.get("driller")),
            "wmis_url": "",
            "parish": "",
        }
    return bores


def normalise_lithology(raw: dict[str, list[dict]], bores: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []

    # Historic and monitoring: choose a single log per bore by priority.
    for dataset in ("historic", "monitoring"):
        by_bore: dict[str, dict[tuple, list[dict]]] = {}
        for r in raw[dataset]:
            bore_id = _s(r.get("boreid"))
            source = _s(r.get("source")).lower()
            interp = _s(r.get("interpretation")).lower()
            by_bore.setdefault(bore_id, {}).setdefault((source, interp), []).append(r)
        for bore_id, logs in by_bore.items():
            key = f"VGB-{bore_id}"
            if key not in bores:
                continue
            best = min(logs, key=lambda k: LOG_PRIORITY.get(k, 99))
            for r in logs[best]:
                desc = _s(r.get("lithologydescription") or r.get("lithology_description"))
                rows.append({
                    "key": key,
                    "log_source": best[0].title(),
                    "depth_from_m": _f(r.get("depth_from_m")),
                    "depth_to_m": _f(r.get("depth_to_m")),
                    "description": " ".join(desc.split()),
                })

    for r in raw["register"]:
        key = f"REG-{_s(r.get('reportid'))}"
        if key not in bores:
            continue
        rows.append({
            "key": key,
            "log_source": "Drillers Log",
            "depth_from_m": _f(r.get("depthfrom")),
            "depth_to_m": _f(r.get("depthto")),
            "description": " ".join(_s(r.get("descript")).split()),
        })

    # Drop duplicate intervals (some bores share a log across datasets).
    seen = set()
    unique = []
    for row in rows:
        sig = (row["key"], row["depth_from_m"], row["depth_to_m"], row["description"])
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(row)
    unique.sort(key=lambda r: (r["key"], r["depth_from_m"] if r["depth_from_m"] is not None else 0))
    return unique


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    try:
        tmp.replace(path)
    except PermissionError:
        alt = path.with_name(path.stem + "-new" + path.suffix)
        tmp.replace(alt)
        print(f"  note: {path.name} is locked; wrote {alt.name} instead", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
                        default=MELBOURNE_BBOX)
    parser.add_argument(
        "--no-urban-clip",
        action="store_true",
        help="Keep every bore in the rectangular bbox (skip urban/road clip).",
    )
    parser.add_argument(
        "--corridor-m",
        type=float,
        default=DEFAULT_CORRIDOR_M,
        help=f"Half-width (metres) around major roads (default {DEFAULT_CORRIDOR_M:g}).",
    )
    parser.add_argument(
        "--no-road-corridors",
        action="store_true",
        help="Clip to urban footprints only (no major-road buffers).",
    )
    args = parser.parse_args()
    bbox = tuple(args.bbox)

    raw_bores = {}
    for name, layer_id in BORE_LAYERS.items():
        print(f"Downloading {name} bore details (layer {layer_id})...")
        raw_bores[name] = fetch_layer(layer_id, bbox)
    raw_lith = {}
    for name, layer_id in LITHOLOGY_LAYERS.items():
        print(f"Downloading {name} lithology (layer {layer_id})...")
        raw_lith[name] = fetch_layer(layer_id, bbox)

    bores = normalise_bores(raw_bores)
    lithology = normalise_lithology(raw_lith, bores)
    before = len(bores)
    urban_names: list[str] = []
    clip_stats = {"urban": 0, "corridor": 0}
    if not args.no_urban_clip:
        print("Clipping to ABS Urban Centres and Localities (Major/Other Urban)...")
        polygons, urban_names = fetch_urban_polygons(bbox)
        print(f"  {len(urban_names)} urban areas, {len(polygons)} polygon part(s)")
        road_segments: list = []
        road_index = None
        if not args.no_road_corridors:
            print(f"Downloading major-road corridors (+/- {args.corridor_m:g} m)...")
            road_segments = fetch_major_roads(bbox)
            road_index = build_road_index(road_segments)
            print(f"  {len(road_segments)} road segments indexed")
        bores, lithology, clip_stats = clip_bores_to_study_area(
            bores, lithology, polygons, road_segments, road_index, args.corridor_m,
        )
        print(
            f"  kept {len(bores)} of {before} "
            f"(urban {clip_stats['urban']}, road corridor {clip_stats['corridor']})"
        )

    logged = {r["key"] for r in lithology}
    for b in bores.values():
        b["has_log"] = "Y" if b["key"] in logged else "N"

    write_csv(DATA_DIR / "bores.csv", list(bores.values()))
    write_csv(DATA_DIR / "lithology.csv", lithology)
    (DATA_DIR / "fetch-info.json").write_text(json.dumps({
        "service": SERVICE,
        "bbox": bbox,
        "urban_clip": not args.no_urban_clip,
        "road_corridors": not args.no_urban_clip and not args.no_road_corridors,
        "corridor_m": args.corridor_m if not args.no_road_corridors else None,
        "urban_areas": urban_names,
        "urban_source": "ABS ASGS 2021 Urban Centres and Localities",
        "road_source": "Vicmap Transport TR_ROAD (freeway/highway/numbered arterial)",
        "downloaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bores_before_clip": before,
        "bores_urban": clip_stats["urban"],
        "bores_road_corridor": clip_stats["corridor"],
        "bores": len(bores),
        "bores_with_log": len(logged),
        "lithology_intervals": len(lithology),
    }, indent=2), encoding="utf-8")

    print(f"Bores: {len(bores)} ({len(logged)} with a soil/rock log)")
    print(f"Lithology intervals: {len(lithology)}")
    print(f"Saved to {DATA_DIR}")


if __name__ == "__main__":
    main()
