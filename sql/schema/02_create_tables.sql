-- ============================================================
-- sql/schema/02_create_tables.sql
-- Full warehouse schema: staging + production tables
-- Run as pipeline_user against flight_warehouse:
--   psql -U pipeline_user -d flight_warehouse -f sql/schema/02_create_tables.sql
-- ============================================================

-- ─────────────────────────────────────────
-- SCHEMA ORGANISATION
-- ─────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS staging;   -- raw ingested data, not yet validated
CREATE SCHEMA IF NOT EXISTS warehouse; -- clean, production-ready tables
CREATE SCHEMA IF NOT EXISTS audit;     -- pipeline run logs and data quality results

GRANT ALL ON SCHEMA staging   TO pipeline_user;
GRANT ALL ON SCHEMA warehouse  TO pipeline_user;
GRANT ALL ON SCHEMA audit      TO pipeline_user;


-- ─────────────────────────────────────────
-- DIMENSION: carriers
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS warehouse.dim_carriers (
    carrier_id      SERIAL PRIMARY KEY,
    carrier_code    VARCHAR(10)  NOT NULL UNIQUE,  -- e.g. 'AA', 'DL', 'UA'
    carrier_name    VARCHAR(200),
    carrier_group   VARCHAR(100),                  -- 'Major', 'National', 'Regional'
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE warehouse.dim_carriers IS
    'Airline carrier reference dimension. One row per carrier.';


-- ─────────────────────────────────────────
-- DIMENSION: airports
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS warehouse.dim_airports (
    airport_id      SERIAL PRIMARY KEY,
    iata_code       CHAR(3)      NOT NULL UNIQUE,  -- e.g. 'JFK', 'LAX'
    airport_name    VARCHAR(300),
    city            VARCHAR(200),
    state_code      CHAR(2),
    state_name      VARCHAR(100),
    country_code    CHAR(2) DEFAULT 'US',
    latitude        NUMERIC(9, 6),
    longitude       NUMERIC(9, 6),
    utc_offset_hrs  NUMERIC(4, 1),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE warehouse.dim_airports IS
    'Airport reference dimension. Enriched from BTS airport lookup and AviationStack.';


-- ─────────────────────────────────────────
-- DIMENSION: date (calendar table)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS warehouse.dim_date (
    date_id         INTEGER PRIMARY KEY,           -- YYYYMMDD format, e.g. 20230115
    full_date       DATE         NOT NULL UNIQUE,
    year            SMALLINT     NOT NULL,
    quarter         SMALLINT     NOT NULL,
    month           SMALLINT     NOT NULL,
    month_name      VARCHAR(12)  NOT NULL,
    week_of_year    SMALLINT     NOT NULL,
    day_of_month    SMALLINT     NOT NULL,
    day_of_week     SMALLINT     NOT NULL,          -- 1=Monday, 7=Sunday (ISO)
    day_name        VARCHAR(12)  NOT NULL,
    is_weekend      BOOLEAN      NOT NULL,
    is_holiday      BOOLEAN DEFAULT FALSE,
    holiday_name    VARCHAR(100),
    season          VARCHAR(10)                     -- 'Winter','Spring','Summer','Fall'
);

COMMENT ON TABLE warehouse.dim_date IS
    'Pre-populated calendar dimension. Date range: 2018-01-01 to 2030-12-31.';


-- ─────────────────────────────────────────
-- FACT: flights (core table, partitioned by year)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS warehouse.fact_flights (
    flight_id               BIGSERIAL,
    flight_date             DATE         NOT NULL,
    date_id                 INTEGER      REFERENCES warehouse.dim_date(date_id),
    carrier_id              INTEGER      REFERENCES warehouse.dim_carriers(carrier_id),
    carrier_code            VARCHAR(10)  NOT NULL,
    flight_number           VARCHAR(10),
    origin_airport_id       INTEGER      REFERENCES warehouse.dim_airports(airport_id),
    dest_airport_id         INTEGER      REFERENCES warehouse.dim_airports(airport_id),
    origin_airport          CHAR(3)      NOT NULL,
    dest_airport            CHAR(3)      NOT NULL,

    -- Schedule
    scheduled_departure     INTEGER,               -- HHMM format, e.g. 1435
    actual_departure        INTEGER,
    scheduled_arrival       INTEGER,
    actual_arrival          INTEGER,

    -- Delays (minutes; positive = late, negative = early)
    departure_delay_min     NUMERIC(7,2),
    arrival_delay_min       NUMERIC(7,2),
    carrier_delay_min       NUMERIC(7,2),
    weather_delay_min       NUMERIC(7,2),
    nas_delay_min           NUMERIC(7,2),
    security_delay_min      NUMERIC(7,2),
    late_aircraft_delay_min NUMERIC(7,2),

    -- Status flags
    is_cancelled            BOOLEAN DEFAULT FALSE,
    cancellation_code       CHAR(1),               -- A=Carrier, B=Weather, C=NAS, D=Security
    is_diverted             BOOLEAN DEFAULT FALSE,

    -- Flight metrics
    scheduled_duration_min  NUMERIC(7,2),
    actual_duration_min     NUMERIC(7,2),
    air_time_min            NUMERIC(7,2),
    distance_miles          NUMERIC(8,2),

    -- Derived / enriched columns (added during transform)
    is_delayed              BOOLEAN,               -- arrival_delay >= 15 min (FAA def.)
    delay_category          VARCHAR(20),           -- 'On Time','Minor','Major','Severe'
    route                   VARCHAR(8),            -- e.g. 'JFK-LAX'

    -- Audit columns
    year                    SMALLINT     NOT NULL,
    month                   SMALLINT     NOT NULL,
    loaded_at               TIMESTAMP    DEFAULT NOW(),
    source_file             VARCHAR(500),

    PRIMARY KEY (flight_id, year)
) PARTITION BY RANGE (year);

COMMENT ON TABLE warehouse.fact_flights IS
    'Central fact table. Partitioned by year for query performance on 7M+ rows.';

-- Create yearly partitions (add more as needed)
CREATE TABLE IF NOT EXISTS warehouse.fact_flights_2019
    PARTITION OF warehouse.fact_flights FOR VALUES FROM (2019) TO (2020);
CREATE TABLE IF NOT EXISTS warehouse.fact_flights_2020
    PARTITION OF warehouse.fact_flights FOR VALUES FROM (2020) TO (2021);
CREATE TABLE IF NOT EXISTS warehouse.fact_flights_2021
    PARTITION OF warehouse.fact_flights FOR VALUES FROM (2021) TO (2022);
CREATE TABLE IF NOT EXISTS warehouse.fact_flights_2022
    PARTITION OF warehouse.fact_flights FOR VALUES FROM (2022) TO (2023);
CREATE TABLE IF NOT EXISTS warehouse.fact_flights_2023
    PARTITION OF warehouse.fact_flights FOR VALUES FROM (2023) TO (2024);
CREATE TABLE IF NOT EXISTS warehouse.fact_flights_2024
    PARTITION OF warehouse.fact_flights FOR VALUES FROM (2024) TO (2025);


-- ─────────────────────────────────────────
-- STAGING: raw_flights
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS staging.raw_flights (
    id              BIGSERIAL PRIMARY KEY,
    source_file     VARCHAR(500),
    raw_data        JSONB,                         -- entire row as JSON for debugging
    flight_date     VARCHAR(20),                   -- kept as text until validated
    carrier_code    VARCHAR(20),
    flight_number   VARCHAR(20),
    origin_airport  VARCHAR(10),
    dest_airport    VARCHAR(10),
    departure_delay VARCHAR(20),
    arrival_delay   VARCHAR(20),
    is_cancelled    VARCHAR(10),
    distance        VARCHAR(20),
    loaded_at       TIMESTAMP DEFAULT NOW(),
    is_processed    BOOLEAN DEFAULT FALSE,
    error_message   TEXT
);

COMMENT ON TABLE staging.raw_flights IS
    'Landing zone for raw BTS CSV data. Rows are moved to warehouse after validation.';


-- ─────────────────────────────────────────
-- AUDIT: pipeline_runs
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit.pipeline_runs (
    run_id          BIGSERIAL PRIMARY KEY,
    dag_id          VARCHAR(200),
    run_type        VARCHAR(50),                   -- 'scheduled','manual','backfill'
    year            SMALLINT,
    month           SMALLINT,
    source_file     VARCHAR(500),
    status          VARCHAR(20),                   -- 'running','success','failed'
    rows_extracted  INTEGER DEFAULT 0,
    rows_validated  INTEGER DEFAULT 0,
    rows_loaded     INTEGER DEFAULT 0,
    rows_rejected   INTEGER DEFAULT 0,
    started_at      TIMESTAMP DEFAULT NOW(),
    completed_at    TIMESTAMP,
    duration_sec    NUMERIC(10,2),
    error_message   TEXT,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS audit.data_quality_results (
    result_id       BIGSERIAL PRIMARY KEY,
    run_id          INTEGER REFERENCES audit.pipeline_runs(run_id),
    check_name      VARCHAR(200),
    check_type      VARCHAR(100),
    table_name      VARCHAR(200),
    column_name     VARCHAR(200),
    rows_checked    INTEGER,
    rows_failed     INTEGER,
    pass_rate       NUMERIC(6,4),                  -- 0.0 to 1.0
    threshold       NUMERIC(6,4),
    passed          BOOLEAN,
    checked_at      TIMESTAMP DEFAULT NOW(),
    details         JSONB
);
