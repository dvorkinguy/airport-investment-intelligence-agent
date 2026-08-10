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

*[Pending - filled in once source URLs are verified live. Do not trust a URL here that wasn't
confirmed with a real HTTP request; dead ends are recorded below, not silently dropped.]*

## 3. BTS on-time performance (congestion signal)

*[Pending - filled in once source URLs are verified live.]*

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

*[Pending final run once BTS snapshots are built. Partial results already confirmed against the
live Neon database (`airport-intel`, eu-central-1) during the schema/views smoke test:]*

- `schema.sql` and `views.sql` both apply cleanly end-to-end (0 errors after the ROUND cast fix
  above).
- `airports` table: 679 rows loaded, matches section 1 exactly.
- New England join sanity check (`airports JOIN regions ON state`, `WHERE region = 'new_england'`):
  **24 airports**, including all 6 named in the exam brief (BOS, BDL, PVD, MHT, BGR, BTV) - ran
  and verified live, full result list available in the load session.

*LAX vs SNA row existence, ANC long_haul_pct, and SFO load_factor/delay_rate checks require
`bts_t100`/`bts_ontime` loaded - pending sections 2-3.*
