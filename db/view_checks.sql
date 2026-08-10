-- Deterministic SQL view checks - the scoring core's automated guard.
-- Convention: every check is a SELECT that returns ZERO ROWS on pass.
-- Any returned row IS a violation, self-describing (columns name what's
-- wrong). Parsed and run by ingestion/run_view_checks.py, split on the
-- "-- CHECK: <name>" marker lines below - keep that exact format if adding
-- checks (marker on its own line, name is everything after the colon).

-- CHECK: score_bounds_0_100
SELECT iata, score_0_100
FROM v_opportunity_score
WHERE score_0_100 < 0 OR score_0_100 > 100;

-- CHECK: component_bounds_0_100
SELECT iata, 'c_pax_growth' AS component, c_pax_growth AS value
FROM v_opportunity_score WHERE c_pax_growth < 0 OR c_pax_growth > 100
UNION ALL
SELECT iata, 'c_load_factor', c_load_factor
FROM v_opportunity_score WHERE c_load_factor < 0 OR c_load_factor > 100
UNION ALL
SELECT iata, 'c_congestion', c_congestion
FROM v_opportunity_score WHERE c_congestion < 0 OR c_congestion > 100
UNION ALL
SELECT iata, 'c_flight_growth', c_flight_growth
FROM v_opportunity_score WHERE c_flight_growth < 0 OR c_flight_growth > 100
UNION ALL
SELECT iata, 'c_infra', c_infra
FROM v_opportunity_score WHERE c_infra < 0 OR c_infra > 100;

-- CHECK: weights_reconstruct_composite_within_0_1
SELECT
    iata,
    score_0_100,
    ROUND(0.30 * c_pax_growth + 0.25 * c_load_factor + 0.20 * c_congestion
          + 0.15 * c_flight_growth + 0.10 * c_infra, 1) AS reconstructed
FROM v_opportunity_score
WHERE ABS(
    score_0_100 - (0.30 * c_pax_growth + 0.25 * c_load_factor + 0.20 * c_congestion
                   + 0.15 * c_flight_growth + 0.10 * c_infra)
) > 0.1;

-- CHECK: load_factor_in_0_to_1_2
-- Scoped to passengers > 0. Found live on first run: 7 airport-years with
-- load_factor exactly 0 - all true zero-passenger rows (a single CLASS=F
-- bts_t100 segment with 0 passengers but nonzero seats, at GA-heavy fields
-- like TEB/Teterboro and BED/Hanscom - almost certainly a repositioning/
-- ferry leg technically filed as scheduled). load_factor=0 is mathematically
-- correct there, not a computation bug, but not a meaningful ratio at zero
-- passenger volume either - same reasoning v_opportunity_score already uses
-- to scope its own population to passengers >= 100k. Verified against raw
-- bts_t100, not a parsing artifact.
SELECT iata, year, load_factor
FROM v_airport_metrics
WHERE passengers > 0 AND load_factor IS NOT NULL AND (load_factor <= 0 OR load_factor > 1.2);

-- CHECK: long_haul_pct_in_0_to_1
SELECT iata, year, long_haul_pct
FROM v_airport_metrics
WHERE long_haul_pct IS NOT NULL AND (long_haul_pct < 0 OR long_haul_pct > 1);

-- CHECK: unmet_demand_never_negative
SELECT iata, year, est_unmet_pax
FROM v_unmet_demand_est
WHERE est_unmet_pax < 0;

-- CHECK: new_england_exact_membership
-- Two failure shapes, both surfaced as rows: a state tagged new_england
-- that shouldn't be, or one of the required 6 missing from the tag.
SELECT state, region, 'UNEXPECTED_MEMBER' AS problem
FROM regions
WHERE region = 'new_england' AND state NOT IN ('CT','ME','MA','NH','RI','VT')
UNION ALL
SELECT required.state, 'new_england', 'MISSING_MEMBER'
FROM (VALUES ('CT'),('ME'),('MA'),('NH'),('RI'),('VT')) AS required(state)
WHERE required.state NOT IN (SELECT state FROM regions WHERE region = 'new_england');

-- CHECK: ground_truth_lax_2025_passengers
SELECT 'LAX' AS iata, 2025 AS year, 36707382 AS expected,
       (SELECT passengers FROM v_airport_metrics WHERE iata = 'LAX' AND year = 2025) AS actual
WHERE (SELECT passengers FROM v_airport_metrics WHERE iata = 'LAX' AND year = 2025)
      IS DISTINCT FROM 36707382;

-- CHECK: ground_truth_anc_2025_long_haul_pct
SELECT 'ANC' AS iata, 2025 AS year, 0.185 AS expected,
       (SELECT ROUND(long_haul_pct, 3) FROM v_airport_metrics WHERE iata = 'ANC' AND year = 2025) AS actual
WHERE (SELECT ROUND(long_haul_pct, 3) FROM v_airport_metrics WHERE iata = 'ANC' AND year = 2025)
      IS DISTINCT FROM 0.185;

-- CHECK: ground_truth_sfo_2025_est_unmet_pax
SELECT 'SFO' AS iata, 2025 AS year, 1381183 AS expected,
       (SELECT est_unmet_pax FROM v_unmet_demand_est WHERE iata = 'SFO' AND year = 2025) AS actual
WHERE (SELECT est_unmet_pax FROM v_unmet_demand_est WHERE iata = 'SFO' AND year = 2025)
      IS DISTINCT FROM 1381183;
