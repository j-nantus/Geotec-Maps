"""Fetch enabled regions into the national bore / lithology template.

Usage:
    python fetch_regions.py
    python fetch_regions.py --region melbourne
    python fetch_regions.py --all-defined   # include enabled:false only if bbox+adapter set
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from adapters import get_adapter
from road_corridors import DEFAULT_CORRIDOR_M, build_road_index, fetch_major_roads
from template import BORE_FIELDS, LITHOLOGY_FIELDS
from urban_areas import clip_bores_to_study_area, fetch_urban_polygons

ROOT = Path(__file__).resolve().parent.parent
REGIONS_DIR = ROOT / "regions"
DATA_DIR = ROOT / "data"


def load_region_configs(region_ids: list[str] | None = None) -> list[dict]:
    paths = sorted(REGIONS_DIR.glob("*.json"))
    if not paths:
        raise FileNotFoundError(f"No region configs in {REGIONS_DIR}")
    configs = []
    for path in paths:
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if region_ids is not None and cfg.get("id") not in region_ids:
            continue
        configs.append(cfg)
    if region_ids is not None:
        found = {c["id"] for c in configs}
        missing = set(region_ids) - found
        if missing:
            raise ValueError(f"Unknown region id(s): {', '.join(sorted(missing))}")
    return configs


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") if row.get(k) is not None else "" for k in fieldnames})
    try:
        tmp.replace(path)
    except PermissionError:
        alt = path.with_name(path.stem + "-new" + path.suffix)
        tmp.replace(alt)
        print(f"  note: {path.name} is locked; wrote {alt.name} instead", file=sys.stderr)


def _tag_bores(bores: dict[str, dict], region: dict) -> None:
    region_id = region["id"]
    jurisdiction = region.get("jurisdiction") or ""
    for b in bores.values():
        b["region_id"] = region_id
        b["jurisdiction"] = jurisdiction


def fetch_one(region: dict) -> tuple[dict[str, dict], list[dict], dict]:
    adapter_name = region.get("adapter")
    if not adapter_name:
        raise ValueError(f"Region {region.get('id')!r} has no adapter")
    if not region.get("bbox"):
        raise ValueError(f"Region {region.get('id')!r} has no bbox")

    adapter = get_adapter(adapter_name)
    print(f"\n=== {region['id']} ({region.get('name', '')}) via {adapter_name} ===")
    bores, lithology, source_meta = adapter(region)
    _tag_bores(bores, region)
    before = len(bores)
    urban_names: list[str] = []
    clip_stats = {"urban": 0, "corridor": 0}
    road_source = None

    urban_clip = bool(region.get("urban_clip", True))
    road_corridors = bool(region.get("road_corridors", True)) and urban_clip
    corridor_m = float(region.get("corridor_m", DEFAULT_CORRIDOR_M))
    abs_state = region.get("abs_state_name") or ""

    if urban_clip:
        if not abs_state:
            raise ValueError(f"Region {region['id']!r} needs abs_state_name for urban clip")
        bbox = tuple(region["bbox"])
        print(f"Clipping to ABS UCL Major/Other Urban ({abs_state})...")
        polygons, urban_names = fetch_urban_polygons(bbox, state_name=abs_state)
        print(f"  {len(urban_names)} urban areas, {len(polygons)} polygon part(s)")

        road_segments: list = []
        road_index = None
        if road_corridors and source_meta.get("supports_road_corridors"):
            print(f"Downloading major-road corridors (+/- {corridor_m:g} m)...")
            road_segments = fetch_major_roads(bbox)
            road_index = build_road_index(road_segments)
            road_source = source_meta.get("road_source")
            print(f"  {len(road_segments)} road segments indexed")
        elif road_corridors:
            print("  skipping road corridors (adapter has no road source yet)")

        bores, lithology, clip_stats = clip_bores_to_study_area(
            bores, lithology, polygons, road_segments, road_index, corridor_m,
        )
        print(
            f"  kept {len(bores)} of {before} "
            f"(urban {clip_stats['urban']}, road corridor {clip_stats['corridor']})"
        )

    logged = {r["key"] for r in lithology}
    for b in bores.values():
        b["has_log"] = "Y" if b["key"] in logged else "N"

    region_meta = {
        "id": region["id"],
        "name": region.get("name", ""),
        "adapter": adapter_name,
        "jurisdiction": region.get("jurisdiction"),
        "bbox": region["bbox"],
        "urban_clip": urban_clip,
        "road_corridors": bool(road_source),
        "corridor_m": corridor_m if road_source else None,
        "urban_areas": urban_names,
        "urban_source": "ABS ASGS 2021 Urban Centres and Localities",
        "road_source": road_source,
        "service": source_meta.get("service"),
        "licence": source_meta.get("licence"),
        "source_label": source_meta.get("source_label"),
        "bores_before_clip": before,
        "bores_urban": clip_stats["urban"],
        "bores_road_corridor": clip_stats["corridor"],
        "bores": len(bores),
        "bores_with_log": len(logged),
        "lithology_intervals": len(lithology),
    }
    return bores, lithology, region_meta


def run(region_ids: list[str] | None = None, include_disabled: bool = False) -> None:
    configs = load_region_configs(region_ids)
    if include_disabled:
        to_fetch = [c for c in configs if c.get("adapter") and c.get("bbox")]
    else:
        to_fetch = [c for c in configs if c.get("enabled")]

    if not to_fetch:
        print("No enabled regions to fetch.", file=sys.stderr)
        sys.exit(1)

    all_bores: dict[str, dict] = {}
    all_lith: list[dict] = []
    region_metas: list[dict] = []

    for region in to_fetch:
        bores, lithology, meta = fetch_one(region)
        overlap = set(bores) & set(all_bores)
        if overlap:
            print(
                f"  warning: {len(overlap)} bore key(s) already present; later region wins",
                file=sys.stderr,
            )
        all_bores.update(bores)
        all_lith.extend(lithology)
        region_metas.append(meta)

    # Stable column order; sort for reproducible diffs.
    bore_rows = sorted(all_bores.values(), key=lambda b: b["key"])
    all_lith.sort(key=lambda r: (r["key"], r["depth_from_m"] if r["depth_from_m"] is not None else 0))

    write_csv(DATA_DIR / "bores.csv", bore_rows, BORE_FIELDS)
    write_csv(DATA_DIR / "lithology.csv", all_lith, LITHOLOGY_FIELDS)

    logged = {r["key"] for r in all_lith}
    info = {
        "downloaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "urban_source": "ABS ASGS 2021 Urban Centres and Localities",
        "regions": region_metas,
        "bores": len(all_bores),
        "bores_with_log": len(logged),
        "lithology_intervals": len(all_lith),
    }
    (DATA_DIR / "fetch-info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")

    print(f"\nCombined: {len(all_bores)} bores ({len(logged)} with a soil/rock log)")
    print(f"Lithology intervals: {len(all_lith)}")
    print(f"Saved to {DATA_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--region",
        action="append",
        dest="regions",
        metavar="ID",
        help="Fetch only this region id (repeatable). Still requires enabled unless --force.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fetch named --region even if enabled is false (requires adapter + bbox).",
    )
    args = parser.parse_args()

    if args.regions and args.force:
        configs = load_region_configs(args.regions)
        for c in configs:
            c["enabled"] = True
        # Write temporarily via run's filter: pass ids and include_disabled path
        # by marking enabled above then calling run with those ids.
        run(region_ids=args.regions, include_disabled=False)
        return

    run(region_ids=args.regions, include_disabled=False)


if __name__ == "__main__":
    main()
