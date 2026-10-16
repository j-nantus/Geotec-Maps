# National geotech map

Single Australia-wide map product, built from a **standardised data template**. Jurisdiction-specific adapters fill that template; the map builder only reads the template.

## Scope (not all of Australia)

Only **metros and large cities we explicitly define**. Coverage is a curated region list in `regions/*.json`, not a national fill. Regions with `"enabled": false` are ignored by the fetch pipeline.

When adding a city or metro, create a region config with at least:

- `id` / `name` (e.g. `sydney`, `brisbane`)
- `enabled`: set `true` when ready to fetch
- `adapter`: jurisdiction fetcher id (currently `vic_deeca` only)
- `bbox`: download envelope `[min_lon, min_lat, max_lon, max_lat]`
- `abs_state_name`: ABS ASGS 2021 state name for UCL clip (e.g. `Victoria`)
- `urban_clip`, `road_corridors`, `corridor_m`: study-area rules

## Architecture

```
regions/*.json  →  fetch_regions.py  →  data/bores.csv + lithology.csv  →  build_map.py
                         ↑
              adapters (vic_deeca, …)
```

- **Template:** stable CSV schema (below).
- **Adapters:** one per jurisdiction (data APIs differ by state).
- **Regions:** config only — which cities/metros to keep.
- **Map:** one Australia-wide HTML viewer over the standardised rows.

## Standard template

### `data/bores.csv`

| Column | Description |
|--------|-------------|
| `key` | Stable unique id (e.g. `VGB-12345`, `REG-BCR000052`) |
| `region_id` | Region config id (e.g. `melbourne`) |
| `jurisdiction` | State/territory code (`VIC`, `NSW`, …) |
| `bore_id` | Source system bore / station id |
| `dataset` | Source dataset label (`historic`, `monitoring`, `register`, …) |
| `lat`, `lon` | WGS84 coordinates |
| `depth_m` | Total bore depth (metres), if known |
| `drilled` | Drill end date `YYYY-MM-DD`, if known |
| `use` | Recorded bore use |
| `position_accuracy` | Source accuracy note |
| `driller` | Driller name, if known |
| `source_url` | Primary online link for the bore (e.g. WMIS), if any |
| `parish` | Parish / locality name used for Vic location checks |
| `has_log` | `Y` / `N` — whether lithology intervals exist |

### `data/lithology.csv`

| Column | Description |
|--------|-------------|
| `key` | Matches `bores.key` |
| `log_source` | Log type label (e.g. `Drillers Log`) |
| `depth_from_m`, `depth_to_m` | Interval depths (metres) |
| `description` | Raw lithology text from the source |

### `data/fetch-info.json`

Per-run metadata: enabled regions fetched, counts, sources, timestamps.

## Region config schema

JSON files in `regions/`. Example (Melbourne):

```json
{
  "id": "melbourne",
  "name": "Greater Melbourne and linked towns",
  "enabled": true,
  "adapter": "vic_deeca",
  "jurisdiction": "VIC",
  "bbox": [143.70, -38.60, 146.10, -37.25],
  "abs_state_name": "Victoria",
  "urban_clip": true,
  "road_corridors": true,
  "corridor_m": 2000
}
```

Capital stubs ship with `"enabled": false` and empty `bbox` / `adapter` placeholders until you define them.

## Adapter contract

Each adapter module under `scripts/adapters/` exposes:

```python
def fetch(region: dict) -> tuple[dict[str, dict], list[dict], dict]:
    """Return (bores_by_key, lithology_rows, source_meta).

    Bore rows must use the standard template columns (region_id / jurisdiction
    filled by the caller if the adapter omits them). Lithology rows use the
    lithology template. source_meta holds licence / service URLs for fetch-info.
    """
```

Registered adapters are selected by the region's `adapter` field.

## Rebuild

```powershell
cd scripts
python fetch_regions.py   # enabled regions → data/
python build_map.py       # → output/australia-bore-map.html
```

`fetch_bores.py` remains as a thin Melbourne-oriented wrapper around the same pipeline.

## Road corridors

Vicmap Transport roads are available for the `vic_deeca` adapter only. Non-Vic regions skip road corridors until a national or state road source is wired.
