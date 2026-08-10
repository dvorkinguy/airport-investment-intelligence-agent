# ADR-001 Appendix: Data Validation

Companion to [ADR-001-data-sources.md](ADR-001-data-sources.md). That ADR states the source
decision; this appendix is the evidence trail - verified URLs, real row counts, gotchas and
dead ends, and the SQL sanity-check results from the loaded Neon database. Written by
Terminal B (data layer) during the build, 2026-08-10/11.

## 1. Airport identity/location - OurAirports

Verified live 2026-08-10 (also documented in
[../research/apify-evaluation.md](../research/apify-evaluation.md) section 1, which pre-dates
this build and answered the "does this need a scraper" question - it doesn't).

| File | URL | Rows downloaded |
|---|---|---|
| `airports.csv` | https://davidmegginson.github.io/ourairports-data/airports.csv | 85,860 airports worldwide; 32,598 with `iso_country = US` |
| `runways.csv` | https://davidmegginson.github.io/ourairports-data/runways.csv | 48,148 runway rows worldwide |

**Filter applied** (`ingestion/build_airports.py`): `iso_country = 'US'` AND `iata_code` non-empty
AND `scheduled_service = 'yes'` - the realistic commercial-passenger universe, and the same
population BTS T-100/on-time data actually covers. Result: **679 airports** (of 32,598 US rows;
699 have `scheduled_service = yes` alone, so ~20 of those lack an IATA code and were correctly
excluded).

**Field mapping decisions** (stated here per ADR-000 principle #4 - assumptions always stated):

- `city` = OurAirports `municipality` (no dedicated "city" field exists in the source).
- `state` = OurAirports `iso_region` with the `US-` prefix stripped (`US-CA` -> `CA`). Verified
  clean: exactly 50 states + DC (51 values), no US territories in the filtered set (Puerto Rico
  etc. are not `iso_country = US` in OurAirports) and no parsing artifacts.
- `runways_count` / `max_runway_length_ft` = count / max(`length_ft`) of `runways.csv` rows
  joined on `airport_ident = ident`, **excluding `closed = '1'` runways** (a closed runway isn't
  real capacity). 4 of 679 airports joined zero runway rows (small commuter fields not in the
  runways table) - `max_runway_length_ft` is NULL for those, `runways_count` is 0.

**Verified present:** all 4 exam-named airports (LAX, SNA, ANC, SFO) and all 6 named New England
airports (BOS, BDL, PVD, MHT, BGR, BTV) - full New England set is 24 airports once joined through
`regions` (see section 3).

## 2. BTS T-100 Segment (demand + capacity history)

**No static prezip URL exists for current-year T-100 data** (unlike on-time performance, section
3). The selection UI is a classic ASP.NET WebForms page - confirmed live 2026-08-10, scripted
successfully:

| Step | Detail |
|---|---|
| Form URL | https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FMG&QO_fu146_anzr=Nv4%20Pn44vr45 |
| Method | GET the page, harvest `__VIEWSTATE`/`__VIEWSTATEGENERATOR`/`__EVENTVALIDATION` hidden fields, POST back with `cboYear=<year>`, `cboPeriod=All`, `cboGeography=All`, all 50 data-column checkboxes `on`, `chkDownloadZip=on` |
| Response | The POST response body **is** the zip directly (`Content-Type: application/zip`) - no follow-up link needed. Gotcha hit and fixed: reading the response as `.text` corrupts the binary zip; must save `.content` (raw bytes) and verify the `PK\x03\x04` magic bytes before writing. |
| Coverage per request | **One submission per year** (`cboPeriod=All`) returns all 12 months. **One file covers both domestic and international** - `DATA_SOURCE` values `DU`/`DF` (domestic) and `IU`/`IF` (international) all present in the same download; no separate geography submission needed. |

**Downloaded and CRC-verified** (`zipfile.testzip()` clean on all three):

| Year | Raw rows | File |
|---|---|---|
| 2023 | 529,559 | `data/raw/t100_segment_2023.zip` (17,915,354 bytes) |
| 2024 | 549,731 | `data/raw/t100_segment_2024.zip` (18,478,250 bytes) |
| 2025 | 571,097 | `data/raw/t100_segment_2025.zip` (19,546,687 bytes) |

**CLASS filter - a real data-quality finding, not a formality.** T-100's `CLASS` field splits
scheduled passenger service (`F`) from scheduled all-cargo (`G`), nonscheduled cargo (`P`), and
nonscheduled/charter passenger (`L`). Measured on the full 2023 file: `CLASS=F` carries
1,062,293,854 of ~1,067,000,000 total passengers (99.6%) across 9,305,434 departures; `CLASS=G`
carries 601,564 departures on **249 total passengers** - essentially pure cargo. Anchorage (ANC)
is a major cargo hub - including `CLASS=G`/`P` would have injected large cargo-only departure
volume into `long_haul_pct` and flight-growth metrics with zero passenger signal behind it, most
visibly distorting exactly the airport the exam asks about. **Filtered to `CLASS='F'` only**,
consistent with `data/airports.csv`'s own `scheduled_service` scoping.

**Origin filter:** kept only if `ORIGIN` is one of the 679 tracked airports in `data/airports.csv`
- `v_airport_metrics` measures activity as origin-based segments (section 4), so a row only
matters if its origin is tracked; the destination can be anything (foreign airport, small
non-tracked US field) and still correctly counts as outbound activity. This does not undercount
inbound international service: a foreign carrier serving a tracked US airport also reports the
reverse (outbound) leg from that same US airport on its own row, which survives this filter.

**Grain fix:** raw rows are year/month/origin/dest/carrier/`AIRCRAFT_TYPE` (a carrier flying two
aircraft types on the same route in the same month reports two rows). `bts_t100`'s primary key
has no aircraft_type column, so duplicates are **summed** (passengers/seats/departures) into one
row; `distance_miles` takes MAX across duplicates (physically the same route - should already be
identical, MAX is a defensive tie-break, not a real choice).

**Result:** 529,559 + 549,731 + 571,097 = 1,650,387 raw rows -> 1,124,393 kept (CLASS=F, origin
tracked) -> **584,498 rows** in `data/bts_t100.csv` after aircraft-type aggregation. Spot-checked
non-empty for every exam-named airport: LAX 14,259 rows, SFO 9,385, BOS 9,635, BDL 2,741, SNA
2,352, ANC 2,363 (route-carrier-month combinations, 2023-2025 combined).

Dead ends hit while scripting the form (recorded for anyone re-running this later):
- `PREZIP/T_T100_SEGMENT_ALL_CARRIER.zip` (no-prefix guess) - 404.
- Live cached prefixed files under `/PREZIP/` (e.g. `896816367_T_T100_SEGMENT_ALL_CARRIER.zip`) -
  return HTTP 200 but are stale (Last-Modified 2015), not current data - schema reference only.
- `data.bts.gov` / `data.transportation.gov` Socrata catalog search for "T-100 segment" - zero
  true BTS-table hits (only a third-party derived dataset on a different portal).
- `bts.gov/airline-data-downloads` - HTTP 403 (Akamai block), consistent across tools.
- First scripted POST attempt returned a corrupted zip - root cause was reading the httpx/requests
  response as decoded text instead of raw bytes before writing to disk, not a server-side issue.

## 3. BTS on-time performance (congestion signal)

The pre-aggregated "Airline Delay Cause" product (`OT_DelayCause1.asp`) is **not directly
scriptable** - confirmed live 2026-08-10: it's a POST-to-self form with JS-cascading dropdowns,
same family of obstacle as T-100 above but without a clean hidden-field contract to script
against in the time available. Fell back to the raw per-flight On-Time Performance prezip
(instructed fallback path), which has a fully static, predictable URL - no form needed:

```
https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{YEAR}_{MONTH}.zip
```

(`MONTH` has no leading zero.) Verified working for all of 2023-2025 (36 files, ~25-31MB each).
Real column set confirmed by downloading and inspecting one file live (2023-01) before writing
the aggregation script - 110 columns, of which 6 matter here: `Year`, `Month`, `Dest`,
`ArrDel15`, `ArrDelayMinutes`, `Cancelled`.

**This is ARRIVAL data - grouped by `Dest`, not `Origin`.** A flight lands (arrives) at its `Dest`
airport; that's the airport whose congestion this measures. Filter applied per raw row: skip if
`Cancelled == '1.00'` or `ArrDel15 == ''` (cancelled flights never arrived, so have no meaningful
delay figure; verified on the 2023-01 sample that all 10,295 cancelled rows are a subset of the
11,640 empty-`ArrDel15` rows, i.e. the empty-string check alone would have been sufficient, but
both are checked defensively). `arr_delay_min` sums `ArrDelayMinutes` (already floored at 0 for
on-time/early arrivals), not the signed `ArrDelay` field (which goes negative for early arrivals
and would let early arrivals silently cancel out real delay elsewhere in the sum).

*[Final row count + all-36-months confirmation to be added once the aggregation run completes -
see section 5.]*

## 4. Schema and view design decisions

Full DDL: [../../db/schema.sql](../../db/schema.sql), [../../db/views.sql](../../db/views.sql).
Decisions not obvious from the SQL comments alone:

- **Regions = US Census Bureau divisions (9-way), not the coarser 4-way regions.** The exam's
  own tool contract needs a `region` value literally called `new_england` - that's Census
  *division* vocabulary, not Census *region* vocabulary (which would only have "Northeast"). All
  50 states + DC mapped; New England = CT, ME, MA, NH, RI, VT exactly as specified.
- **Airport activity = origin-based T-100 segments.** `v_airport_metrics` counts passengers/
  seats/departures where the airport is the segment ORIGIN. T-100 already reports both
  directions of a route as separate rows when both operate, so origin-only counting captures
  "activity at this airport" without double-counting the reverse leg. Stated explicitly because
  a destination-based or origin+destination-summed definition would give different (still
  defensible) numbers - this is a modeling choice, not the only correct one.
- **Long-haul threshold:** the exam-stated >=1500 mile assumption, applied to `departures`
  count (not passengers) - i.e. long_haul_pct answers "what share of flights out of here are
  long-haul," not "what share of travelers."
- **`v_opportunity_score` is a single current-state score (latest year only), not a time
  series** - matches the exact column list Terminal A's tool contract specified (no `year`
  column). Normalization population is airports with >=100k annual passengers in that latest
  year, per the exam brief; missing growth/delay data defaults to neutral (0) rather than
  excluding the airport from ranking.
- **`c_infra` is inverted:** fewer/shorter runways -> higher score, because that reads as
  *physically constrained -> stronger expansion-investment signal*, per the exam brief's own
  framing of the metric.
- **`v_unmet_demand_est` calibration constants are judgment calls, not fitted:** an 0.80 load
  factor "comfort threshold" (planes fuller than that are assumed to be turning away marginal
  demand) and a 0.10 weight on the delay-suppression term (the weakest/most indirect of the
  three signals). Documented here and in the view's `COMMENT ON VIEW` so a reviewer can
  challenge the numbers - this is explicitly an ESTIMATE per ADR-001 mitigation #3, not an
  observed figure.
- **Postgres gotcha:** `PERCENT_RANK()` returns `double precision`; the two-argument form of
  `ROUND()` only has a `numeric` overload. Every `PERCENT_RANK()` call in `v_opportunity_score`
  needs an explicit `::numeric` cast before rounding, or the view fails to create with
  `UndefinedFunction: function round(double precision, integer) does not exist`. Hit this live
  against Neon during the smoke test; fixed by casting.
- **No FK from `airports.state` to `regions.state`:** Postgres FKs require a unique constraint
  on the referenced column; `airports.state` is not unique per row (many airports share a
  state). `regions` is a small, fully-enumerated (51-row) static lookup table joined by value -
  correctness comes from the enumeration being complete and verified (section 1), not from a
  DB-level constraint.

## 5. Load + sanity check results

Full load run 2026-08-10/11 against Neon (`airport-intel`, eu-central-1), `uv run ingestion/load.py`:

```
Applied db\schema.sql
Loaded airports: 679 rows from data\airports.csv
Loaded bts_t100: 584498 rows from data\bts_t100.csv
Loaded bts_ontime: 12164 rows from data\bts_ontime.csv
Applied db\views.sql
Load complete.
```

All required sanity checks run live against the loaded database and PASS:

- **New England join** (`airports JOIN regions ON state`, `WHERE region = 'new_england'`): **24
  airports**, including all 6 named in the exam brief (BOS, BDL, PVD, MHT, BGR, BTV).
- **LAX vs SNA rows exist** in both `v_airport_metrics` and `v_congestion`, all 3 years each.
  Real, plausible numbers: LAX 2025 - 36.7M passengers, 81.7% load factor, 48.3% long-haul
  departures, 18.8% delay rate. SNA 2025 - 5.5M passengers, 79.9% load factor, **only 13.1%
  long-haul** - consistent with SNA's well-known historical noise-ordinance flight-length/slot
  restrictions, a real-world cross-check that the data and long-haul definition behave sensibly.
- **ANC long_haul_pct plausible**: 14.0% (2023) -> 14.5% (2024) -> 18.5% (2025), all non-null,
  reasonable for a passenger-only (CLASS=F) view of a cargo-dominant airport.
- **SFO load_factor + delay_rate populated**: load factor 82-83% across all 3 years; delay rate
  22.9% (2023) -> 29.8% (2024) -> 24.1% (2025) with 16.7-21.0 min average delay - consistent with
  SFO's well-documented weather-driven congestion.
- **`v_opportunity_score`**: 225 airports scored (>=100k annual passengers, latest year = 2025).
  New England spread is internally coherent: Bangor (BGR) top-ranked at 68.4 (high growth +
  high infra-constraint - a small, growing, physically limited field); Worcester (ORH) lowest at
  18.3 (very low congestion component - genuinely underused capacity, a real "not yet" signal
  rather than a scoring artifact).
- **`v_unmet_demand_est`** for SFO: ~1.4-1.7M estimated unmet passengers/year across 2023-2025,
  `driver_load_factor` ~82-83% (the dominant term, well above the 0.80 threshold),
  `driver_growth_gap` slightly negative in 2024/2025 (seat growth outpaced passenger growth those
  years, correctly floored to contribute ~0 rather than a negative estimate) - the three driver
  columns make the estimate auditable exactly as intended, not a black-box number.

No blockers, no silent failures. All 4 exam-question-relevant checks the command center specified
(LAX/SNA, ANC, SFO, New England) pass against real data end to end.
