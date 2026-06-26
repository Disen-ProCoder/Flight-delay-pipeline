-- ============================================================
-- sql/schema/03_create_indexes.sql
-- Performance indexes for the warehouse tables.
-- Run AFTER 02_create_tables.sql and after loading initial data.
-- Creating indexes on empty tables is fine; just remember that
-- adding indexes post-load on 7M rows takes a few minutes.
-- ============================================================

-- ─── fact_flights indexes ────────────────────────────────────

-- Most queries filter by date range
CREATE INDEX IF NOT EXISTS idx_flights_date
    ON warehouse.fact_flights (flight_date);

-- Carrier analysis queries
CREATE INDEX IF NOT EXISTS idx_flights_carrier
    ON warehouse.fact_flights (carrier_code, flight_date);

-- Route analysis (most common query pattern)
CREATE INDEX IF NOT EXISTS idx_flights_route
    ON warehouse.fact_flights (origin_airport, dest_airport, flight_date);

-- Delay analysis queries
CREATE INDEX IF NOT EXISTS idx_flights_arrival_delay
    ON warehouse.fact_flights (arrival_delay_min)
    WHERE arrival_delay_min IS NOT NULL;

-- Cancelled flights filter
CREATE INDEX IF NOT EXISTS idx_flights_cancelled
    ON warehouse.fact_flights (is_cancelled, flight_date)
    WHERE is_cancelled = TRUE;

-- Year/month partitioning support
CREATE INDEX IF NOT EXISTS idx_flights_year_month
    ON warehouse.fact_flights (year, month);

-- FK-style lookups
CREATE INDEX IF NOT EXISTS idx_flights_carrier_id
    ON warehouse.fact_flights (carrier_id);

CREATE INDEX IF NOT EXISTS idx_flights_origin_id
    ON warehouse.fact_flights (origin_airport_id);

CREATE INDEX IF NOT EXISTS idx_flights_dest_id
    ON warehouse.fact_flights (dest_airport_id);


-- ─── dim_airports indexes ────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_airports_state
    ON warehouse.dim_airports (state_code);

CREATE INDEX IF NOT EXISTS idx_airports_city
    ON warehouse.dim_airports (city);


-- ─── dim_date indexes ────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_date_year_month
    ON warehouse.dim_date (year, month);

CREATE INDEX IF NOT EXISTS idx_date_day_of_week
    ON warehouse.dim_date (day_of_week);


-- ─── staging indexes ─────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_staging_processed
    ON staging.raw_flights (is_processed, loaded_at);

CREATE INDEX IF NOT EXISTS idx_staging_source_file
    ON staging.raw_flights (source_file);


-- ─── audit indexes ───────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_runs_status
    ON audit.pipeline_runs (status, started_at);

CREATE INDEX IF NOT EXISTS idx_dq_run_id
    ON audit.data_quality_results (run_id);
