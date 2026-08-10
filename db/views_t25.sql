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
-- Source: cats.airports.faa.gov "Individual Airports" Form 127 search, bulk
-- CSV export (exportToCSV=true with no single airport selected returns every
-- airport that filed for that year - see ADR-004 for the verified URL and
-- the national-rollup dead end hit first). FY2023-2024, 884 airport-year
-- reports. net_rev_per_enplanement is computed at ingestion time
-- ((op_revenue - op_expenses) / enplanements), not an FAA-published field.
-- ============================================================================
CREATE TABLE airport_financials (
    locid                     TEXT NOT NULL,
    fy                        INTEGER NOT NULL,
    op_revenue                NUMERIC(14, 2),
    op_expenses               NUMERIC(14, 2),
    enplanements              NUMERIC(12, 0),
    net_rev_per_enplanement   NUMERIC(10, 2),
    PRIMARY KEY (locid, fy)
);

-- ESTIMATE. roi_proxy = est_unmet_pax (from v_unmet_demand_est, Tier 1 -
-- not recomputed here) * net_rev_per_enplanement. Reads as "if the
-- passengers this airport is estimated to be turning away today flew here
-- instead, at this airport's current net revenue per enplanement, what
-- would that be worth" - a proxy for expansion ROI, not a real financial
-- projection (ignores capacity cost, fare mix shift, induced demand
-- elasticity). locid is assumed == iata for the tracked airport set - true
-- for every major/medium hub checked (LAX, SFO, ANC, BOS, BDL, PVD, MHT,
-- BGR, BTV) but not guaranteed for every small field nationally; a locid
-- that doesn't match its airports.iata simply won't join and is silently
-- absent from this view; it is not treated as an error to fix here.
CREATE VIEW v_roi_proxy AS
SELECT
    u.iata,
    u.year,
    ROUND(u.est_unmet_pax * f.net_rev_per_enplanement, 0) AS roi_proxy
FROM v_unmet_demand_est u
JOIN airport_financials f ON f.locid = u.iata AND f.fy = u.year
WHERE f.net_rev_per_enplanement IS NOT NULL;

COMMENT ON VIEW v_roi_proxy IS
    'ESTIMATE built on an ESTIMATE: est_unmet_pax (v_unmet_demand_est, itself '
    'labeled ESTIMATE) times net_rev_per_enplanement (FAA Form 127, computed '
    'not FAA-published). A rough expansion-value proxy, not a financial '
    'projection - ignores capacity cost, fare-mix shift, demand elasticity. '
    'NULL/absent net_rev_per_enplanement (zero enplanements that year) rows '
    'are excluded, not zeroed - a real "cannot compute" case.';
