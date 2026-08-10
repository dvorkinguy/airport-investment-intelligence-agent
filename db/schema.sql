-- Airport Investment Intelligence Agent - core schema
-- Source: OurAirports (airports) + BTS T-100 Segment (bts_t100) + BTS on-time (bts_ontime).
-- Loaded idempotently by ingestion/load.py. See docs/adr/ADR-001-data-sources.md for source
-- rationale and docs/adr/ADR-001-appendix-data-validation.md for verified URLs + row counts.

DROP TABLE IF EXISTS bts_ontime CASCADE;
DROP TABLE IF EXISTS bts_t100 CASCADE;
DROP TABLE IF EXISTS regions CASCADE;
DROP TABLE IF EXISTS airports CASCADE;

-- Airport identity/location/infrastructure. Scope: US airports with an IATA code AND
-- scheduled_service = 'yes' in OurAirports (the realistic commercial-passenger universe).
CREATE TABLE airports (
    iata                  TEXT PRIMARY KEY,
    icao                  TEXT,
    name                  TEXT NOT NULL,
    city                  TEXT,
    state                 TEXT NOT NULL,
    lat                   NUMERIC(9, 6) NOT NULL,
    lon                   NUMERIC(9, 6) NOT NULL,
    runways_count         INTEGER NOT NULL DEFAULT 0,
    max_runway_length_ft  INTEGER
);

-- US Census Bureau divisions (9-way; the standard vocabulary that natively contains a
-- "New England" value, unlike the coarser 4-way Northeast/Midwest/South/West regions).
-- Plain lookup table joined by value (airports.state -> regions.state) - no FK, since
-- airports.state is not unique per row and Postgres FKs require a unique target.
CREATE TABLE regions (
    state   TEXT PRIMARY KEY,
    region  TEXT NOT NULL
);

-- BTS T-100 Segment (All Carriers): domestic + international, one row per
-- origin/destination/carrier/month. "Segment" = a single directional origin->dest leg;
-- a round trip route appears as two rows (X->Y and Y->X) when both directions operate.
CREATE TABLE bts_t100 (
    year              INTEGER NOT NULL,
    month             INTEGER NOT NULL,
    origin_iata       TEXT NOT NULL,
    dest_iata         TEXT NOT NULL,
    carrier           TEXT NOT NULL,
    passengers        INTEGER NOT NULL DEFAULT 0,
    seats             INTEGER NOT NULL DEFAULT 0,
    departures        INTEGER NOT NULL DEFAULT 0,
    distance_miles    NUMERIC(10, 2),
    PRIMARY KEY (year, month, origin_iata, dest_iata, carrier)
);
CREATE INDEX idx_bts_t100_origin_year ON bts_t100 (origin_iata, year);
CREATE INDEX idx_bts_t100_dest_year ON bts_t100 (dest_iata, year);

-- BTS on-time performance, aggregated to airport/month (source carrier dimension summed
-- away at load time - see ingestion/load.py). arr_delay_min is TOTAL arrival delay
-- minutes across all arrivals that month (not just delayed ones); v_congestion divides
-- by arr_flights for an average-minutes-of-delay-per-arrival figure.
CREATE TABLE bts_ontime (
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    airport_iata    TEXT NOT NULL,
    arr_flights     INTEGER NOT NULL DEFAULT 0,
    arr_del15       INTEGER NOT NULL DEFAULT 0,
    arr_delay_min   NUMERIC(12, 2) NOT NULL DEFAULT 0,
    PRIMARY KEY (year, month, airport_iata)
);
CREATE INDEX idx_bts_ontime_airport_year ON bts_ontime (airport_iata, year);

-- New England row set required by the exam's region filter, CT/ME/MA/NH/RI/VT ->
-- new_england. Full 9-division US Census Bureau mapping (50 states + DC).
INSERT INTO regions (state, region) VALUES
    ('CT', 'new_england'), ('ME', 'new_england'), ('MA', 'new_england'),
    ('NH', 'new_england'), ('RI', 'new_england'), ('VT', 'new_england'),
    ('NJ', 'middle_atlantic'), ('NY', 'middle_atlantic'), ('PA', 'middle_atlantic'),
    ('IL', 'east_north_central'), ('IN', 'east_north_central'), ('MI', 'east_north_central'),
    ('OH', 'east_north_central'), ('WI', 'east_north_central'),
    ('IA', 'west_north_central'), ('KS', 'west_north_central'), ('MN', 'west_north_central'),
    ('MO', 'west_north_central'), ('NE', 'west_north_central'), ('ND', 'west_north_central'),
    ('SD', 'west_north_central'),
    ('DE', 'south_atlantic'), ('FL', 'south_atlantic'), ('GA', 'south_atlantic'),
    ('MD', 'south_atlantic'), ('NC', 'south_atlantic'), ('SC', 'south_atlantic'),
    ('VA', 'south_atlantic'), ('DC', 'south_atlantic'), ('WV', 'south_atlantic'),
    ('AL', 'east_south_central'), ('KY', 'east_south_central'), ('MS', 'east_south_central'),
    ('TN', 'east_south_central'),
    ('AR', 'west_south_central'), ('LA', 'west_south_central'), ('OK', 'west_south_central'),
    ('TX', 'west_south_central'),
    ('AZ', 'mountain'), ('CO', 'mountain'), ('ID', 'mountain'), ('MT', 'mountain'),
    ('NV', 'mountain'), ('NM', 'mountain'), ('UT', 'mountain'), ('WY', 'mountain'),
    ('AK', 'pacific'), ('CA', 'pacific'), ('HI', 'pacific'), ('OR', 'pacific'), ('WA', 'pacific');
