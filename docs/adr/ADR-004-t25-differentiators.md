# ADR-004: T2.5 Differentiators - Carrier Concentration (HHI) + Form 127 ROI Proxy

Status: accepted | Date: 2026-08-11 | Additive only - does not modify db/schema.sql or
db/views.sql (Tier 1, gate-critical, frozen).

## Verdict

Both halves shipped. Neither needed the fallback timebox - HHI required no new data (built
straight from `bts_t100`), and Form 127's bulk CSV export was found and verified within the
research window, faster than the ASP.NET-form path T-100 needed in the Tier 1 build.

## 1. v_carrier_concentration (HHI)

No new source - computed entirely from `bts_t100` (already CLASS='F' passenger-only, see
ADR-001-appendix-data-validation.md section 2). HHI = sum of each carrier's (passenger share
* 100)^2 per airport-year, standard 0-10,000 scale. Airline concentration is a named factor in
Moody's US airport revenue bond rating methodology - a single-carrier-dependent airport carries
more credit/investment risk than a diversified one.

**Sanity check, cross-referenced against known real-world airline market structure:**

| Airport | HHI (2023-2025 range) | Top carrier | Reads as |
|---|---|---|---|
| ANC | ~4,010-4,290 | Alaska Airlines, 61-63% | Highly concentrated (>2500) - correct, ANC is Alaska's historic hub |
| BOS | ~1,340-1,450 | JetBlue, 25-27% | Right at the unconcentrated boundary - correct, Boston is famously carrier-fragmented |
| LAX | ~856-893 | Delta, 17% | Very unconcentrated - correct, LAX has no dominant carrier |

1,921 total airport-year rows.

## 2. Form 127 financials -> ROI proxy

**Source, verified live 2026-08-11:** FAA CATS (cats.airports.faa.gov). No API - a ColdFusion
form, but simpler than T-100's ASP.NET viewstate flow.

**Dead end hit first:** the "All Airports" Form 127 report
(`/reports/form_127_all_airports/?year=2023`) looked like the obvious bulk endpoint but is a
**national rollup** - one row per line item, one column per year (e.g. "5.0 Total Operating
Revenue: $28,672,202,696" for the whole country) - not per-airport data. Useful for national
context, useless for this table.

**What actually worked:** the "Individual Airports" search form's own copy says the airport
field is "Required unless exporting to CSV." Confirmed live: a GET against
`/reports/form_127/?year={YEAR}&yearToCompare=&region=&state=&loc_id=&airportID=&exportToCSV=true`
with every selector left blank returns a bulk CSV of **every airport that filed for that year**,
not one. No hidden tokens or auth needed. 83 columns; the 5 that matter (0-indexed, confirmed
live, not guaranteed stable across FAA form versions): `Year` (0), `Location ID` (4),
`Total Operating Revenue` (32), `Total Operating Expenses` (41), `Enplanements` (73).

**Data quality finding:** one exact-duplicate `(locid, fy)` row (DBQ/2023) in the raw export -
same filing appearing twice, byte-identical. Consistent with **GAO-26-107938 "Airport Financial
Reporting: FAA Should Implement Controls to Improve Data Quality"** (found during research, not
guessed at) - this is a documented, known issue with this exact data source, not a bug in our
parsing. Handled by keeping first occurrence, dropping the rest (1 row dropped of 447).

**Result:** FY2023-2024, 883 airport-financial-report rows (445 + 438, after dedup) ->
`data/airport_financials.csv` -> `airport_financials` table. `net_rev_per_enplanement` is
computed at ingestion time (`(op_revenue - op_expenses) / enplanements`), not FAA-published;
NULL (not zero) when enplanements is 0/blank for that airport-year - a real "cannot compute"
case, occurs for very small GA-heavy fields.

**v_roi_proxy** joins this to Tier 1's `v_unmet_demand_est.est_unmet_pax` (already labeled
ESTIMATE) - `roi_proxy = est_unmet_pax * net_rev_per_enplanement`. This is **an estimate built
on an estimate**: a rough expansion-value proxy, not a financial projection. It ignores capacity
cost, fare-mix shift, and demand elasticity - stated here and in the view's `COMMENT ON VIEW`.
600 rows (narrower than either source alone, since it requires both `v_unmet_demand_est`
2023-2025 coverage AND `airport_financials` 2023-2024 coverage to overlap).

**Sanity check, all 10 brief-named airports, both years, non-null:**

| Airport | 2023 roi_proxy | 2024 roi_proxy | Why |
|---|---|---|---|
| LAX | $14,963,375 | $17,195,415 | Large, financially healthy hub - strongly positive |
| SFO | $10,476,321 | $29,002,086 | Same - positive and growing |
| BOS | $10,208,122 | $12,049,364 | Same - positive |
| SNA, PVD | positive, smaller | positive, smaller | Smaller but financially sound |
| ANC, BDL, BGR, BTV, MHT | **negative** | **negative** | `net_rev_per_enplanement` is negative at these airports (operating at a loss per enplanement) - unmet demand there is not unambiguously good news for the airport's *current* finances, a genuinely interesting wrinkle the raw estimate surfaces rather than hides |

**locid == iata assumption:** FAA's Location ID and BTS/OurAirports IATA code are treated as the
same value for the join. Verified true for every airport checked above (all 10 brief-named
airports). Not independently verified for the full national set - a locid that doesn't match its
`airports.iata` simply fails to join and is silently absent from `v_roi_proxy`, not treated as an
error requiring a fix.

## Design decisions

- Additive-only files (`db/views_t25.sql`, `ingestion/build_faa_form127.py`,
  `ingestion/load_t25.py`) - Tier 1's `db/schema.sql`, `db/views.sql`, `ingestion/load.py` are
  untouched, per the safety rule in the Terminal 4 prompt.
- `airport_financials` PK is `(locid, fy)` - matches the grain FAA actually files at (one report
  per airport per fiscal year).
- Scope is FY2023-2024 only (not through 2025) - FAA Form 127 filings lag the fiscal year they
  cover (confirmed: FY2024 filings still arriving as late as 2026-02-26 in the raw data), so a
  FY2025 pull today would be incomplete, not just "not yet available."
