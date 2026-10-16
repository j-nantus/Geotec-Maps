"""Melbourne-oriented wrapper around the national region fetch pipeline.

Prefer `python fetch_regions.py` for multi-region / national builds.

Usage:
    python fetch_bores.py
    python fetch_bores.py --bbox 144.8 -37.9 145.1 -37.7
    python fetch_bores.py --no-urban-clip
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adapters.vic_deeca import SERVICE
from road_corridors import DEFAULT_CORRIDOR_M

ROOT = Path(__file__).resolve().parent.parent
REGIONS_DIR = ROOT / "regions"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
                        default=None)
    parser.add_argument(
        "--no-urban-clip",
        action="store_true",
        help="Keep every bore in the rectangular bbox (skip urban/road clip).",
    )
    parser.add_argument(
        "--corridor-m",
        type=float,
        default=None,
        help=f"Half-width (metres) around major roads (default {DEFAULT_CORRIDOR_M:g}).",
    )
    parser.add_argument(
        "--no-road-corridors",
        action="store_true",
        help="Clip to urban footprints only (no major-road buffers).",
    )
    args = parser.parse_args()

    melbourne_path = REGIONS_DIR / "melbourne.json"
    if not melbourne_path.exists():
        print(f"Missing {melbourne_path}; cannot run Melbourne fetch.", file=sys.stderr)
        sys.exit(1)

    cfg = json.loads(melbourne_path.read_text(encoding="utf-8"))
    if args.bbox is not None:
        cfg["bbox"] = list(args.bbox)
    if args.no_urban_clip:
        cfg["urban_clip"] = False
        cfg["road_corridors"] = False
    if args.no_road_corridors:
        cfg["road_corridors"] = False
    if args.corridor_m is not None:
        cfg["corridor_m"] = args.corridor_m
    cfg["enabled"] = True

    from datetime import datetime, timezone

    from fetch_regions import DATA_DIR, fetch_one, write_csv
    from template import BORE_FIELDS, LITHOLOGY_FIELDS

    bores, lithology, meta = fetch_one(cfg)
    logged = {r["key"] for r in lithology}
    bore_rows = sorted(bores.values(), key=lambda b: b["key"])
    lithology.sort(key=lambda r: (r["key"], r["depth_from_m"] if r["depth_from_m"] is not None else 0))
    write_csv(DATA_DIR / "bores.csv", bore_rows, BORE_FIELDS)
    write_csv(DATA_DIR / "lithology.csv", lithology, LITHOLOGY_FIELDS)
    info = {
        "downloaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "urban_source": "ABS ASGS 2021 Urban Centres and Localities",
        "regions": [meta],
        "bores": len(bores),
        "bores_with_log": len(logged),
        "lithology_intervals": len(lithology),
        # Back-compat keys used by older notes / tooling
        "service": meta.get("service") or SERVICE,
        "bbox": cfg["bbox"],
    }
    (DATA_DIR / "fetch-info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"Bores: {len(bores)} ({len(logged)} with a soil/rock log)")
    print(f"Lithology intervals: {len(lithology)}")
    print(f"Saved to {DATA_DIR}")


if __name__ == "__main__":
    main()
