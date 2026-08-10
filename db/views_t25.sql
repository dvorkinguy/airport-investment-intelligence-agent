-- T2.5 differentiators - ADDITIVE ONLY. Never touches db/schema.sql or
-- db/views.sql (airports, regions, bts_t100, bts_ontime, v_airport_metrics,
-- v_congestion, v_opportunity_score, v_unmet_demand_est) - those are
-- gate-critical Tier 1 artifacts, already verified, frozen.
-- See docs/adr/ADR-004-t25-differentiators.md for sources + sanity checks.

DROP VIEW IF EXISTS v_roi_proxy CASCADE;
DROP TABLE IF EXISTS airport_financials CASCADE;
DROP VIEW IF EXISTS v_carrier_concentration CASCADE;

-- ============================================================================
-- v_carrier_concentration: Herfindahl-Hirschman Index of each tracked
-- airport's carrier mix, per year. Airline concentration is a named factor
-- in Moody's US airport revenue bond rating methodology (a single-carrier-
-- dependent airport carries more credit/investment risk than a diversified
-- one) - this is a real, cited-elsewhere metric, not an invented one.
--
-- Source: bts_t100 only (no new data). That table is ALREADY filtered to
-- CLASS='F' (scheduled passenger service) at ingestion time - see
-- ADR-001-appendix-data-validation.md section 2 - so "passenger service
-- only, cargo excluded" is inherited from the existing table, not a filter
-- applied here. Worth stating explicitly so a reader doesn't go looking for
-- a missing WHERE clause.
--
-- HHI = sum of each carrier's (share * 100)^2, standard 0-10,000 scale.
-- DOJ/FTC merger-guideline bands (used here as an interpretation aid, not a
-- regulatory claim about airports): <1500 unconcentrated, 1500-2500
-- moderately concentrated, >2500 highly concentrated - i.e. how much of
-- this airport's air service rides on a single carrier's decisions.
-- ============================================================================
CREATE VIEW v_carrier_concentration AS
WITH carrier_pax AS (
    SELECT origin_iata AS iata, year, carrier, SUM(passengers) AS passengers
    FROM bts_t100
    GROUP BY origin_iata, year, carrier
),
totals AS (
    SELECT iata, year, SUM(passengers) AS total_passengers
    FROM carrier_pax
    GROUP BY iata, year
),
shares AS (
    SELECT c.iata, c.year, c.carrier, c.passengers,
           c.passengers::numeric / NULLIF(t.total_passengers, 0) AS share
    FROM carrier_pax c
    JOIN totals t ON t.iata = c.iata AND t.year = c.year
),
hhi_calc AS (
    SELECT iata, year, SUM(POWER(share * 100, 2)) AS hhi
    FROM shares
    GROUP BY iata, year
),
top AS (
    SELECT DISTINCT ON (iata, year)
        iata, year, carrier AS top_carrier, share AS top_carrier_share
    FROM shares
    ORDER BY iata, year, share DESC
)
SELECT
    h.iata,
    h.year,
    ROUND(h.hhi, 1) AS hhi,
    t.top_carrier,
    ROUND(t.top_carrier_share, 4) AS top_carrier_share
FROM hhi_calc h
JOIN top t ON t.iata = h.iata AND t.year = h.year;

COMMENT ON VIEW v_carrier_concentration IS
    'HHI on a 0-10,000 scale (share as percentage, squared, summed across '
    'carriers). Scope is CLASS=F passenger service only - inherited from '
    'bts_t100, cargo deliberately excluded. Interpretation bands (DOJ/FTC '
    'merger-guideline convention): <1500 unconcentrated, 1500-2500 '
    'moderately concentrated, >2500 highly concentrated - named as a factor '
    'in Moody''s US airport revenue bond rating methodology.';

-- ============================================================================
-- airport_financials + v_roi_proxy: FAA Form 127 (CATS) financial data.
-- ESTIMATE / conditional - see ADR-004 for whether this landed or was
-- dropped at the research timebox. If dropped, this section is absent and
-- v_roi_proxy does not exist; callers must check for it.
-- ============================================================================
