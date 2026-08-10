-- Airport Investment Intelligence Agent - deterministic scoring views
-- Every formula is plain SQL, auditable, reproducible (ADR-000 principle #2).
-- Estimates are labeled ESTIMATE in-line (ADR-000 principle #4).

DROP VIEW IF EXISTS v_unmet_demand_est CASCADE;
DROP VIEW IF EXISTS v_opportunity_score CASCADE;
DROP VIEW IF EXISTS v_congestion CASCADE;
DROP VIEW IF EXISTS v_airport_metrics CASCADE;

-- ============================================================================
-- v_airport_metrics: demand + capacity history per airport per year.
-- Basis: BTS T-100 segments where this airport is the ORIGIN (outbound legs).
-- A round-trip route reports both directions as separate segment rows, so
-- origin-only counting captures departures FROM this airport without double
-- counting the reverse leg under the same airport.
-- ============================================================================
CREATE VIEW v_airport_metrics AS
WITH yearly AS (
    SELECT
        origin_iata AS iata,
        year,
        SUM(passengers) AS passengers,
        SUM(seats) AS seats,
        SUM(departures) AS departures,
        SUM(departures) FILTER (WHERE distance_miles >= 1500) AS long_haul_departures
    FROM bts_t100
    GROUP BY origin_iata, year
)
SELECT
    iata,
    year,
    passengers,
    seats,
    departures,
    ROUND(passengers::numeric / NULLIF(seats, 0), 4) AS load_factor,
    ROUND(long_haul_departures::numeric / NULLIF(departures, 0), 4) AS long_haul_pct,
    ROUND(
        (passengers - LAG(passengers) OVER w)::numeric
        / NULLIF(LAG(passengers) OVER w, 0), 4
    ) AS pax_growth_yoy,
    ROUND(
        (seats - LAG(seats) OVER w)::numeric
        / NULLIF(LAG(seats) OVER w, 0), 4
    ) AS seat_growth_yoy,
    ROUND(
        (departures - LAG(departures) OVER w)::numeric
        / NULLIF(LAG(departures) OVER w, 0), 4
    ) AS flight_growth_yoy
FROM yearly
WINDOW w AS (PARTITION BY iata ORDER BY year);

COMMENT ON VIEW v_airport_metrics IS
    'YoY growth is NULL for an airport''s first year in the data (no prior-year base) - '
    'that is a real "no comparison available" signal, not zero growth. Long-haul threshold '
    'is the exam-stated >=1500mi assumption, applied to departures (not passengers).';

-- ============================================================================
-- v_congestion: arrival delay signal per airport per year.
-- Source rows are pre-aggregated to airport/month at load time (carrier summed away).
-- ============================================================================
CREATE VIEW v_congestion AS
SELECT
    airport_iata AS iata,
    year,
    ROUND(SUM(arr_del15)::numeric / NULLIF(SUM(arr_flights), 0), 4) AS delay_rate,
    ROUND(SUM(arr_delay_min) / NULLIF(SUM(arr_flights), 0), 2) AS avg_delay_min
FROM bts_ontime
GROUP BY airport_iata, year;

COMMENT ON VIEW v_congestion IS
    'avg_delay_min spreads TOTAL arrival delay minutes across ALL arrivals that month '
    '(not just the delayed ones) - it is a per-operation congestion severity figure, not '
    'the average lateness of a delayed flight alone. delay_rate is the classic >=15min metric.';

-- ============================================================================
-- v_opportunity_score: single current-state ranking score per airport (latest
-- year with data only - a "where to look now" score, not a time series).
-- Weights .30 pax growth / .25 load factor / .20 congestion / .15 flight growth /
-- .10 infra constraint, each a 0-100 percentile rank WITHIN the population of
-- airports at >=100k annual passengers in that latest year (the exam-stated
-- normalization population - tiny airports don't distort the percentile scale).
-- ============================================================================
CREATE VIEW v_opportunity_score AS
WITH latest_year AS (
    SELECT MAX(year) AS year FROM v_airport_metrics
),
base AS (
    SELECT
        m.iata,
        COALESCE(m.pax_growth_yoy, 0) AS pax_growth_yoy,
        COALESCE(m.load_factor, 0) AS load_factor,
        COALESCE(m.flight_growth_yoy, 0) AS flight_growth_yoy,
        COALESCE(c.delay_rate, 0) AS delay_rate,
        a.runways_count,
        COALESCE(a.max_runway_length_ft, 0) AS max_runway_length_ft
    FROM v_airport_metrics m
    JOIN latest_year ly ON m.year = ly.year
    JOIN airports a ON a.iata = m.iata
    LEFT JOIN v_congestion c ON c.iata = m.iata AND c.year = m.year
    WHERE m.passengers >= 100000
),
ranked AS (
    SELECT
        iata,
        ROUND((PERCENT_RANK() OVER (ORDER BY pax_growth_yoy ASC))::numeric * 100, 1) AS c_pax_growth,
        ROUND((PERCENT_RANK() OVER (ORDER BY load_factor ASC))::numeric * 100, 1) AS c_load_factor,
        ROUND((PERCENT_RANK() OVER (ORDER BY delay_rate ASC))::numeric * 100, 1) AS c_congestion,
        ROUND((PERCENT_RANK() OVER (ORDER BY flight_growth_yoy ASC))::numeric * 100, 1) AS c_flight_growth,
        ROUND(
            100 - (
                (PERCENT_RANK() OVER (ORDER BY runways_count ASC))::numeric
                + (PERCENT_RANK() OVER (ORDER BY max_runway_length_ft ASC))::numeric
            ) / 2.0 * 100,
        1) AS c_infra
    FROM base
)
SELECT
    iata,
    ROUND(
        0.30 * c_pax_growth + 0.25 * c_load_factor + 0.20 * c_congestion
        + 0.15 * c_flight_growth + 0.10 * c_infra,
    1) AS score_0_100,
    c_pax_growth,
    c_load_factor,
    c_congestion,
    c_flight_growth,
    c_infra
FROM ranked;

COMMENT ON VIEW v_opportunity_score IS
    'c_infra is INVERTED (100 - avg percentile of runway count/length): fewer/shorter '
    'runways = more physically constrained = higher expansion-investment signal. All '
    'other components are ascending (higher metric = higher score). Missing growth/delay '
    'data is treated as neutral (0), not excluded, so a new-to-the-data airport still ranks '
    'on its other four components instead of disappearing from the ranking.';

-- ============================================================================
-- v_unmet_demand_est: ESTIMATE. No public source reports unmet demand directly;
-- this is max(0, modeled demand pressure) per ADR-001 mitigation #3, built from
-- three independently-reasoned signals, each already non-negative by construction
-- (so one weak signal cannot be dragged further negative by another). Calibration
-- constants (0.80 load-factor comfort threshold, 0.10 delay weight) are stated
-- judgment calls, not fitted to data - see the design doc for the same language.
-- ============================================================================
CREATE VIEW v_unmet_demand_est AS
SELECT
    m.iata,
    m.year,
    ROUND(
        -- signal 1: planes already flying fuller than a comfortable 80% load factor
        -- imply airlines are turning away marginal demand; expressed as implied seats.
        COALESCE(m.seats, 0) * GREATEST(m.load_factor - 0.80, 0)
        -- signal 2: passenger demand growing faster than seat supply; the gap in
        -- growth rates, applied to the current passenger base, approximates riders
        -- who wanted to fly but capacity didn't grow to carry them.
        + COALESCE(m.passengers, 0) * GREATEST(
            COALESCE(m.pax_growth_yoy, 0) - COALESCE(m.seat_growth_yoy, 0), 0)
        -- signal 3: chronic delay suppresses marginal (esp. business) demand - a
        -- deliberately small weight since this is the most indirect of the three.
        + COALESCE(m.passengers, 0) * COALESCE(c.delay_rate, 0) * 0.10
    , 0) AS est_unmet_pax,
    m.load_factor AS driver_load_factor,
    ROUND(COALESCE(m.pax_growth_yoy, 0) - COALESCE(m.seat_growth_yoy, 0), 4) AS driver_growth_gap,
    COALESCE(c.delay_rate, 0) AS driver_delay_rate
FROM v_airport_metrics m
LEFT JOIN v_congestion c ON c.iata = m.iata AND c.year = m.year;

COMMENT ON VIEW v_unmet_demand_est IS
    'ESTIMATE, not an observed figure - no public source reports true unmet demand. '
    'Three additive pressure signals (load-factor headroom, growth-vs-capacity gap, '
    'delay-driven suppression). driver_* columns expose the raw inputs so the estimate '
    'is auditable, not a black box - see docs/adr/ADR-001-appendix-data-validation.md '
    'for a worked example against a real airport.';
