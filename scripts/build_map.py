"""Build a self-contained HTML map from data/bores.csv and data/lithology.csv.

Usage:
    python build_map.py
    python build_map.py --out ../output/my-map.html --max-depth 30
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from fetch_bores import MELBOURNE_BBOX, SERVICE, fetch_layer
from location_flags import fetch_parish_polygons, flag_bore

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TEMPLATE = Path(__file__).resolve().parent / "map_template.html"
DEFAULT_OUT = ROOT / "output" / "melbourne-bore-map.html"

CATEGORIES = [
    ("Fill / pavement", "#8c6d62"),
    ("Topsoil", "#4e7d3a"),
    ("Clay", "#d98c1f"),
    ("Silt", "#c9b458"),
    ("Sand", "#f2df7b"),
    ("Gravel", "#a3a3a3"),
    ("Organic / peat / lignite", "#3b2a20"),
    ("Weathered rock", "#9c7fb5"),
    ("Rock", "#4a5a8c"),
    ("Not described", "#e0e0e0"),
]
CAT = {name: i for i, (name, _) in enumerate(CATEGORIES)}

FILL_WORDS = {"FILL", "FILLING", "FIL", "BACKFILL", "CONCRETE", "CONC", "ASPHALT", "BITUMEN", "RUBBLE",
              "RUBBISH", "BRICK", "BRICKS", "PAVEMENT", "FCR", "SLAG", "BALLAST", "ROADBASE"}
TOPSOIL_WORDS = {"TOPSOIL", "LOAM"}
ORGANIC_WORDS = {"PEAT", "PEATY", "ORGANIC", "ORGANICS", "LIGNITE", "LIGNITIC", "LIGNIOUS", "COAL", "WOOD"}
ROCK_NOUNS = {"BASALT", "BLUESTONE", "SILTSTONE", "MUDSTONE", "SANDSTONE", "SANDSTONES", "SHALE",
              "GRANITE", "GRANODIORITE", "SLATE", "LIMESTONE", "ROCK", "ROCKS", "BEDROCK", "SCORIA",
              "IRONSTONE", "QUARTZITE", "DACITE", "RHYODACITE", "HORNFELS", "MARL", "MARLE", "CLAYSTONE",
              "CONGLOMERATE", "TUFF", "SCHIST", "GNEISS", "DOLERITE", "CALCARENITE", "DOLOMITE",
              "GREYWACKE", "WACKE", "STONE", "STONES", "METAMORPHIC",
              # common driller misspellings
              "BASLAT", "BASAL", "SOSALT", "SILSTONE", "MUDSOTNE", "LIMESTINE"}
WEATHERED_WORDS = {"WEATHERED", "DECOMPOSED", "DECOM", "DECOMP", "XW", "HW", "EW", "RESIDUAL"}
SOIL_NOUNS = {
    "CLAY": "Clay", "CLAYS": "Clay",
    "SILT": "Silt", "SILTS": "Silt",
    "SAND": "Sand", "SANDS": "Sand",
    "GRAVEL": "Gravel", "GRAVELS": "Gravel", "PEBBLES": "Gravel", "COBBLES": "Gravel",
    "BOULDERS": "Gravel", "SHELLS": "Sand", "SNAD": "Sand",
}
# Fallback for run-together words such as "SILTYCLAY" or "CLAYGREY".
SOIL_SUBSTRINGS = (("CLAY", "Clay"), ("SILT", "Silt"), ("SAND", "Sand"), ("GRAVEL", "Gravel"))
UNKNOWN_PHRASES = ("NOT KNOWN", "UNKNOWN", "NO SAMPLE", "NO RETURN", "NOT LOGGED", "NO LOG")

_SPLIT_STONE = re.compile(r"\b(BLUE|MUD|SAND|SILT|IRON|LIME|CLAY)\s+STONE\b")


def classify(description: str) -> int:
    text = description.upper()
    if not text.strip() or any(p in text for p in UNKNOWN_PHRASES):
        return CAT["Not described"]
    text = _SPLIT_STONE.sub(r"\1STONE", text)
    text = text.replace("TOP SOIL", "TOPSOIL").replace("SURFACE SOIL", "TOPSOIL")
    tokens = re.findall(r"[A-Z]+", text)
    tokset = set(tokens)

    if tokset & FILL_WORDS or "CRUSHED ROCK" in text or "ROAD BASE" in text:
        return CAT["Fill / pavement"]
    if tokset & TOPSOIL_WORDS or tokens == ["SOIL"]:
        return CAT["Topsoil"]
    if tokset & ORGANIC_WORDS:
        return CAT["Organic / peat / lignite"]
    if "COFFEE" in tokset:
        return CAT["Sand"]

    soil_nouns = [SOIL_NOUNS[t] for t in tokens if t in SOIL_NOUNS]
    rock_hits = tokset & ROCK_NOUNS
    if soil_nouns and rock_hits <= {"STONE", "STONES", "ROCK", "ROCKS"}:
        return CAT[soil_nouns[0]]  # e.g. "SANDY CLAY WITH STONES"
    if rock_hits:
        if tokset & WEATHERED_WORDS or any(n != "Gravel" for n in soil_nouns):
            return CAT["Weathered rock"]
        return CAT["Rock"]
    if soil_nouns:
        return CAT[soil_nouns[0]]
    if "COODE" in tokset:
        return CAT["Silt"]
    if "SOIL" in tokset or "SOILS" in tokset or "SUBSOIL" in tokset:
        return CAT["Topsoil"]
    for fragment, name in SOIL_SUBSTRINGS:
        if fragment in text:
            return CAT[name]
    return CAT["Not described"]


def _num(value: str) -> float | None:
    try:
        return round(float(value), 2) if value not in ("", None) else None
    except ValueError:
        return None


def _load_bores() -> dict[str, dict]:
    candidates = [p for p in (DATA_DIR / "bores.csv", DATA_DIR / "bores-new.csv") if p.exists()]
    path = max(candidates, key=lambda p: p.stat().st_mtime)
    print(f"Loading bores from {path.name}")
    bores = {r["key"]: r for r in csv.DictReader(path.open(encoding="utf-8"))}
    if any(b.get("parish") for b in bores.values()):
        return bores
    print("Parish column missing — downloading parish from DEECA bore layers...")
    for layer_id, dataset in ((42, "historic"), (12, "monitoring")):
        for r in fetch_layer(layer_id, MELBOURNE_BBOX):
            bore_id = (r.get("boreid") or "").strip().strip('"')
            if not bore_id:
                continue
            key = f"VGB-{bore_id}"
            if key in bores and not bores[key].get("parish"):
                bores[key]["parish"] = (r.get("parish") or "").strip()
    return bores


def build(out_path: Path, max_depth: float) -> None:
    bores = _load_bores()
    layers: dict[str, list] = {}
    log_source: dict[str, str] = {}
    cat_counts: Counter = Counter()
    lith_path = DATA_DIR / "lithology-new.csv"
    if not lith_path.exists():
        lith_path = DATA_DIR / "lithology.csv"
    for r in csv.DictReader(lith_path.open(encoding="utf-8")):
        top, bottom = _num(r["depth_from_m"]), _num(r["depth_to_m"])
        if top is None or top >= max_depth:
            continue
        cat = classify(r["description"])
        cat_counts[CATEGORIES[cat][0]] += 1
        layers.setdefault(r["key"], []).append([top, bottom, cat, r["description"][:90]])
        log_source[r["key"]] = r["log_source"]

    datasets = ["historic", "monitoring", "register"]
    mapped = []
    for key, logs in layers.items():
        b = bores.get(key)
        if not b:
            continue
        logs.sort(key=lambda x: x[0])
        for prev, layer in zip(logs, logs[1:]):
            if layer[2] == CAT["Not described"] and "AS ABOVE" in layer[3].upper():
                layer[2] = prev[2]
        mapped.append((key, b, logs))

    parish_names = { (b.get("parish") or "").strip() for _, b, _ in mapped }
    parish_names.discard("")
    print(f"Downloading Vicmap parish boundaries for {len(parish_names)} parishes...")
    parish_polys = fetch_parish_polygons(parish_names)

    rows = []
    n_water = n_parish = 0
    for key, b, logs in mapped:
        lat, lon = float(b["lat"]), float(b["lon"])
        parish = (b.get("parish") or "").strip()
        in_water, out_parish = flag_bore(lon, lat, parish, parish_polys)
        if in_water:
            n_water += 1
        if out_parish:
            n_parish += 1
        rows.append([
            key,
            b["bore_id"],
            datasets.index(b["dataset"]),
            round(lat, 6),
            round(lon, 6),
            _num(b["depth_m"]),
            b["drilled"],
            b["position_accuracy"],
            log_source.get(key, ""),
            logs,
            b.get("wmis_url", ""),
            parish,
            1 if in_water else 0,
            1 if out_parish else 0,
        ])

    info_path = DATA_DIR / "fetch-info.json"
    info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
    payload = {
        "meta": {
            "downloaded": info.get("downloaded_utc", ""),
            "total_bores": info.get("bores", len(bores)),
            "max_depth": max_depth,
            "source": "DEECA Victorian Groundwater Bores (CC BY 4.0)",
            "service": SERVICE,
            "datasets": ["Historic bore", "State monitoring bore", "Water Register bore (2017+)"],
            "dataset_pages": [
                "https://data.water.vic.gov.au/groundwater-monitoring-statewide",
                "https://data.water.vic.gov.au/groundwater-monitoring-statewide",
                "https://discover.data.vic.gov.au/dataset/victorian-water-register-bore-lithology",
            ],
            "location_flags": {
                "in_water": n_water,
                "outside_parish": n_parish,
            },
        },
        "categories": [{"name": n, "color": c} for n, c in CATEGORIES],
        "bores": rows,
    }

    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__DATA__*/null", json.dumps(payload, separators=(",", ":"))
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    print(f"Bores on map: {len(rows)}")
    print(f"  Location flags: {n_water} in open water, {n_parish} outside recorded parish")
    for name, n in cat_counts.most_common():
        print(f"  {name:<26} {n}")
    print(f"Wrote {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-depth", type=float, default=30.0,
                        help="Drop log intervals starting deeper than this (m). Default 30.")
    args = parser.parse_args()
    build(args.out, args.max_depth)


if __name__ == "__main__":
    main()
