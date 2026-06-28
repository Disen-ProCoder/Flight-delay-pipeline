-- ============================================================
-- sql/views/analytical_views.sql
-- Materialised views for fast dashboard queries.
-- Refresh these after each pipeline run.
-- ============================================================

-- ─── Monthly summary materialised view ────────────────────────
-- Refreshed nightly — powers any BI dashboard

CREATE MATERIALIZED VIEW IF NOT EXISTS warehouse.mv_monthly_summary AS
SELECT
    f.year,
    f.month,
    d.month_name,
    d.season,
    f.carrier_code,
    COUNT(*)                                                    AS total_flights,
    COUNT(*) FILTER (WHERE f.is_cancelled)                      AS cancelled_count,
    COUNT(*) FILTER (WHERE f.is_delayed AND NOT f.is_cancelled) AS delayed_count,
    COUNT(*) FILTER (
        WHERE NOT f.is_delayed AND NOT f.is_cancelled
    )                                                           AS ontime_count,
    ROUND(AVG(f.arrival_delay_min) FILTER (
        WHERE NOT f.is_cancelled), 2)                           AS avg_arrival_delay,
    ROUND(AVG(f.departure_delay_min) FILTER (
        WHERE NOT f.is_cancelled), 2)                           AS avg_departure_delay,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE f.is_delayed AND NOT f.is_cancelled)
        / NULLIF(COUNT(*) FILTER (WHERE NOT f.is_cancelled), 0),
    2)                                                          AS ontime_rate_pct,
    ROUND(AVG(f.distance_miles), 2)                             AS avg_distance_miles
FROM warehouse.fact_flights f
JOIN warehouse.dim_date d ON d.date_id = f.date_id
GROUP BY f.year, f.month, d.month_name, d.season, f.carrier_code
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_monthly_summary
    ON warehouse.mv_monthly_summary (year, month, carrier_code);


-- ─── Carrier performance materialised view ────────────────────

CREATE MATERIALIZED VIEW IF NOT EXISTS warehouse.mv_carrier_performance AS
SELECT
    f.carrier_code,
    c.carrier_name,
    f.year,
    COUNT(*)                                                    AS total_flights,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE NOT f.is_delayed AND NOT f.is_cancelled)
        / NULLIF(COUNT(*) FILTER (WHERE NOT f.is_cancelled), 0),
    2)                                                          AS ontime_pct,
    ROUND(AVG(f.arrival_delay_min) FILTER (
        WHERE NOT f.is_cancelled), 2)                           AS avg_delay_min,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE f.is_cancelled)
        / COUNT(*),
    2)                                                          AS cancellation_pct,
    COUNT(DISTINCT f.route)                                     AS routes_served,
    COUNT(DISTINCT f.origin_airport)                            AS airports_served
FROM warehouse.fact_flights f
LEFT JOIN warehouse.dim_carriers c USING (carrier_code)
GROUP BY f.carrier_code, c.carrier_name, f.year
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_carrier_perf
    ON warehouse.mv_carrier_performance (carrier_code, year);


-- ─── Route analysis materialised view ────────────────────────

CREATE MATERIALIZED VIEW IF NOT EXISTS warehouse.mv_route_analysis AS
SELECT
    f.route,
    f.origin_airport,
    f.dest_airport,
    oa.city                                                     AS origin_city,
    oa.state_code                                               AS origin_state,
    da.city                                                     AS dest_city,
    da.state_code                                               AS dest_state,
    f.year,
    COUNT(*)                                                    AS total_flights,
    ROUND(AVG(f.arrival_delay_min) FILTER (
        WHERE NOT f.is_cancelled), 2)                           AS avg_delay_min,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (
        ORDER BY f.arrival_delay_min)::numeric, 2)              AS median_delay_min,
    ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (
        ORDER BY f.arrival_delay_min)::numeric, 2)              AS p90_delay_min,
    ROUND(AVG(f.distance_miles), 0)                             AS avg_distance_miles,
    COUNT(DISTINCT f.carrier_code)                              AS carrier_count
FROM warehouse.fact_flights f
LEFT JOIN warehouse.dim_airports oa ON oa.iata_code = f.origin_airport
LEFT JOIN warehouse.dim_airports da ON da.iata_code = f.dest_airport
GROUP BY
    f.route, f.origin_airport, f.dest_airport,
    oa.city, oa.state_code, da.city, da.state_code, f.year
HAVING COUNT(*) >= 50
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_route_analysis
    ON warehouse.mv_route_analysis (route, year);


-- ─── Regular view: recent pipeline health ────────────────────
-- Use this to monitor your pipeline health — great for the portfolio

CREATE OR REPLACE VIEW audit.v_pipeline_health AS
SELECT
    run_id,
    year,
    month,
    status,
    rows_extracted,
    rows_loaded,
    rows_rejected,
    ROUND(
        100.0 * rows_rejected / NULLIF(rows_extracted, 0),
    2)                                                          AS rejection_rate_pct,
    ROUND(duration_sec, 1)                                      AS duration_sec,
    started_at,
    CASE
        WHEN status = 'success' AND rows_rejected::float / NULLIF(rows_extracted, 0) < 0.01
            THEN 'healthy'
        WHEN status = 'success'
            THEN 'warning'
        ELSE 'failed'
    END                                                         AS health_status
FROM audit.pipeline_runs
ORDER BY started_at DESC;
