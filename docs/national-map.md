# National geotech map (direction)

Single Australia-wide map product, built from a **standardised data template**. Jurisdiction-specific fetchers fill that template; the map builder only reads the template.

## Scope (not all of Australia)

Only **metros and large cities we explicitly define**, the same way the Melbourne PoC defines Greater Melbourne and linked towns (urban footprints + major-road corridors). Coverage is a curated region list, not a national fill.

When adding a city or metro, specify at least:

- Name / id (e.g. `sydney`, `brisbane`)
- Download envelope (or equivalent)
- Which urban centres to include (ABS UCL / SUA names, or a hand list)
- Whether major-road corridors between those centres are included, and corridor width
- Jurisdiction adapter (state bore source)

## Architecture

```
adapters (Vic DEECA, NSW, QLD, …)  →  standard bores + lithology tables  →  map builder
region configs (user-defined metros)  →  clip / corridor rules
```

- **Template:** stable schema (ids, coordinates, depths, raw lithology text, source links, licence).
- **Adapters:** one per jurisdiction (data APIs differ by state).
- **Regions:** config only — which cities/metros to keep.
- **Map:** one Australia-wide viewer over the standardised rows (prefer tiled or viewport loading over one giant static HTML as coverage grows).

## Melbourne PoC

The current scripts under `scripts/` and `output/melbourne-bore-map.html` are the Victoria / Melbourne-region proof of concept. National work generalises that pattern; it does not replace the need for per-state adapters.
