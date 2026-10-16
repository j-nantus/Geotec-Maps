# Geotec Maps

Shallow geotech bore map for Australian metros and large cities we define — not a
full-country fill. Coverage is driven by region configs under `regions/`; adapters
normalise each jurisdiction into a standard template; the map builder only reads that
template. See [docs/national-map.md](docs/national-map.md).

**Current coverage:** Greater Melbourne and linked towns (Ballarat to Warragul, Sunbury
to Anglesea / Western Port), from Victorian government bore logs. Bores are kept inside
ABS Urban Centres and Localities, plus a buffer along major roads linking those towns.
Other capitals ship as disabled stubs until you define their envelopes and adapters.

Open `output/australia-bore-map.html` in a browser (needs an internet connection for the
basemap and address search). Right-click the map to search at any point. Results can be
downloaded as CSV. The earlier Melbourne PoC file
`output/melbourne-bore-map.html` may still be present from previous builds.

If an address matches several places (for example "Smith Street"), the map lists every match
with a numbered pin and the number of logged bores nearby, and you pick the one to search.

Bores with suspect coordinates are marked with a **red outline** (soil colour is unchanged):

- plotted in open Port Phillip Bay, or
- coordinates fall outside the Vicmap parish named on the bore record.

Use **Hide from map** above the colour dropdown to temporarily remove either group. Warnings
also appear in the bore popup and in the search results list.

Each bore's popup links back to its source:

- **Original log record** and **Bore details record**: the bore's entries in the DEECA
  database, which can be used to check the map's copy of the log.
- **WMIS bore page**: for State Observation Bore Network bores.
- **Request completion report**: for Water Register bores, a pre-filled email to the Water
  Register. The lodged driller's reports are not published online.
- Scanned original logs for historic bores are not published online.

## Data source

DEECA *Victorian Groundwater Bores* map service (historic bores, State Observation Bore
Network, and Victorian Water Register bores since 2017), licensed CC BY 4.0.

- Download uses a coarse box wide enough for full town footprints (including western
  Ballarat), then keeps bores inside ABS ASGS 2021 urban footprints or within ~2 km of
  major Vicmap roads linking those centres.
- Logs are mostly driller descriptions from water and monitoring bores, not geotechnical logs.
  No SPT, moisture or strength data.
- Many older bores have position accuracy "NOT KNOWN"; these are flagged in the map.

Desk-study use only – not a substitute for site investigation.

## Rebuild / refresh

Python 3.10+ only; no extra packages.

```powershell
cd scripts
python fetch_regions.py   # enabled regions → data/ (Melbourne ~40 s)
python build_map.py       # → output/australia-bore-map.html
```

Options:

- `fetch_regions.py --region melbourne` to fetch one region by id.
- `fetch_regions.py --region melbourne --force` to fetch a disabled region that already has adapter + bbox.
- `fetch_bores.py` — Melbourne-oriented wrapper (supports `--bbox`, `--no-urban-clip`, `--no-road-corridors`, `--corridor-m`).
- `build_map.py --max-depth 30` drops log intervals starting deeper than this.
- `build_map.py --out ../output/melbourne-bore-map.html` to write the old PoC filename.

## How soil descriptions are classified

`build_map.py` sorts each log interval into Fill/pavement, Topsoil, Clay, Silt, Sand, Gravel,
Organic/peat/lignite, Weathered rock, Rock, or Not described using keywords in the driller's
description (for example "SANDY CLAY" is Clay, "CLAYEY SAND" is Sand, "DECOMPOSED BASALT" is
Weathered rock). About 3% of intervals end up as Not described (blank, "UNKNOWN", typos).
