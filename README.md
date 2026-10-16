# Geotec Maps

Proof-of-concept shallow geotech bore map (Melbourne region first).

A snapshot map of publicly available shallow ground data for towns and cities from Ballarat
to Warragul and Sunbury to Anglesea / Western Port, built from Victorian government bore
logs. Bores are kept inside ABS Urban Centres and Localities, plus a buffer along major
roads (freeway / highway / numbered arterial) that link those towns — not a plain square
box. Search an address, pick a radius, and get a summary of nearby bores: main material in
the top 3 m, fill thickness, depth to rock, and any soft/organic layers.

**National direction:** one Australia-wide map from a standardised data template, covering
only metros and large cities we define (not a full-country fill). See
[docs/national-map.md](docs/national-map.md).

Open `output/melbourne-bore-map.html` in a browser (needs an internet connection for the
basemap and address search). Right-click the map to search at any point. Results can be
downloaded as CSV.

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
cd "Geotech data map\scripts"
python fetch_bores.py      # downloads to data/ (about 40 s)
python build_map.py        # writes output/melbourne-bore-map.html
```

Options:

- `fetch_bores.py --bbox MIN_LON MIN_LAT MAX_LON MAX_LAT` for a different area.
- `fetch_bores.py --no-urban-clip` to keep every bore in the rectangular box.
- `fetch_bores.py --no-road-corridors` for urban footprints only.
- `fetch_bores.py --corridor-m 3000` to widen the road buffer (default 2000 m).
- `build_map.py --max-depth 30` drops log intervals starting deeper than this.

## How soil descriptions are classified

`build_map.py` sorts each log interval into Fill/pavement, Topsoil, Clay, Silt, Sand, Gravel,
Organic/peat/lignite, Weathered rock, Rock, or Not described using keywords in the driller's
description (for example "SANDY CLAY" is Clay, "CLAYEY SAND" is Sand, "DECOMPOSED BASALT" is
Weathered rock). About 3% of intervals end up as Not described (blank, "UNKNOWN", typos).
