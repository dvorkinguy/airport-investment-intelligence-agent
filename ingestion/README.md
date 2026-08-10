# Ingestion

Snapshot-first (per [ADR-001](../docs/adr/ADR-001-data-sources.md)): each `build_*.py` script
fetches a public source once and writes a processed CSV into `data/`; `load.py` applies the
schema + views and loads those CSVs into Neon. Re-run any build script to refresh its snapshot.

Full verification detail (URLs, row counts, filtering decisions, gotchas): see
[ADR-001-appendix-data-validation.md](../docs/adr/ADR-001-appendix-data-validation.md).

## Scripts

| Script | Source | Output |
|---|---|---|
| `build_airports.py` | OurAirports (`data/raw/airports.csv`, `runways.csv`) | `data/airports.csv` |
| `build_bts_t100.py` | BTS T-100 Segment (ASP.NET form, scripted) | `data/bts_t100.csv` |
| `build_bts_ontime.py` | BTS On-Time Performance (static prezip URLs) | `data/bts_ontime.csv` |
| `load.py` | the three CSVs above | Neon: schema + views + data |

## Run order

```
uv run python ingestion/build_airports.py
uv run --with requests python ingestion/build_bts_t100.py
uv run python ingestion/build_bts_ontime.py
uv run python ingestion/load.py
```

Requires `DATABASE_URL` in `.env` at repo root (see `.env.example`).

`build_bts_t100.py` needs the `requests` package - installed ad-hoc via `--with requests`, not
added to the shared `pyproject.toml`. The other three scripts are stdlib-only.

Raw downloads land in `data/raw/` (gitignored, several hundred MB); only the processed CSVs in
`data/` are committed. All four scripts are idempotent - safe to re-run, they skip
already-downloaded/complete files and rebuild their output CSV from whatever's in `data/raw/`.

`load.py` is also idempotent: `schema.sql` drops and recreates every table before loading, so
running the full chain twice in a row produces the same end state both times.
