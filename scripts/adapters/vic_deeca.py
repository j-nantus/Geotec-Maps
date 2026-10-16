"""Victoria DEECA groundwater bores → national template rows.

Source: DEECA "Victorian Groundwater Bores" ArcGIS map service (CC BY 4.0).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SERVICE = (
    "https://corp-gis.mapshare.vic.gov.au/arcgis/rest/services/"
    "GroundwaterBores/GWBores/MapServer"
)

# Download envelope used by the Melbourne PoC when no region bbox is supplied.
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

JURISDICTION = "VIC"


def _get_json(url: str, params: dict, retries: int = 4) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "geotec-maps/0.1"})
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
                "source_url": _s(r.get("wmis_url")),
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
            "source_url": "",
            "parish": "",
        }
    return bores


def normalise_lithology(raw: dict[str, list[dict]], bores: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []

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


def fetch(region: dict) -> tuple[dict[str, dict], list[dict], dict]:
    """Download and normalise DEECA bores for a region config."""
    bbox = tuple(region["bbox"])
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
    meta = {
        "service": SERVICE,
        "licence": "CC BY 4.0",
        "source_label": "DEECA Victorian Groundwater Bores",
        "road_source": "Vicmap Transport TR_ROAD (freeway/highway/numbered arterial)",
        "supports_road_corridors": True,
    }
    return bores, lithology, meta
