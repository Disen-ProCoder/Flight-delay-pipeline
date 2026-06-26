-- ============================================================
-- sql/queries/01_carrier_performance.sql
-- Carrier on-time performance analysis
-- These are the queries that make your portfolio impressive.
-- Run these in psql or connect via a BI tool like Metabase.
-- ============================================================


-- ─── 1. Overall carrier ranking by on-time performance ────────

SELECT
    f.carrier_code,
    c.carrier_name,
    COUNT(*)                                                    AS total_flights,
    COUNT(*) FILTER (WHERE f.is_cancelled)                      AS cancelled_flights,
    ROUND(AVG(f.arrival_delay_min) FILTER (
        WHERE NOT f.is_cancelled), 2)                           AS avg_arrival_delay_min,
    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE f.is_delayed AND NOT f.is_cancelled
        ) / NULLIF(COUNT(*) FILTER (WHERE NOT f.is_cancelled), 0),
    2)                                                          AS pct_delayed,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE f.is_cancelled)
        / COUNT(*),
    2)                                                          AS pct_cancelled,
    ROUND(AVG(f.weather_delay_min) FILTER (
        WHERE f.weather_delay_min > 0), 2)                      AS avg_weather_delay,
    ROUND(AVG(f.carrier_delay_min) FILTER (
        WHERE f.carrier_delay_min > 0), 2)                      AS avg_carrier_delay
FROM warehouse.fact_flights f
LEFT JOIN warehouse.dim_carriers c USING (carrier_code)
WHERE f.year = 2023
GROUP BY f.carrier_code, c.carrier_name
ORDER BY pct_delayed ASC;


-- ─── 2. Delay trends by month (seasonality analysis) ──────────

SELECT
    f.year,
    f.month,
    d.month_name,
    COUNT(*)                                                    AS total_flights,
    ROUND(AVG(f.arrival_delay_min) FILTER (
        WHERE NOT f.is_cancelled), 2)                           AS avg_delay_min,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE f.is_delayed)
        / NULLIF(COUNT(*) FILTER (WHERE NOT f.is_cancelled), 0),
    2)                                                          AS pct_delayed,
    COUNT(*) FILTER (WHERE f.cancellation_code = 'B')           AS weather_cancellations,
    COUNT(*) FILTER (WHERE f.cancellation_code = 'A')           AS carrier_cancellations
FROM warehouse.fact_flights f
JOIN warehouse.dim_date d ON d.date_id = f.date_id
GROUP BY f.year, f.month, d.month_name
ORDER BY f.year, f.month;


-- ─── 3. Worst routes by average arrival delay ─────────────────

SELECT
    f.route,
    f.origin_airport,
    f.dest_airport,
    oa.city                                                     AS origin_city,
    da.city                                                     AS dest_city,
    COUNT(*)                                                    AS total_flights,
    ROUND(AVG(f.arrival_delay_min), 2)                          AS avg_delay_min,
    ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (
        ORDER BY f.arrival_delay_min), 2)                       AS p90_delay_min,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE f.is_delayed)
        / NULLIF(COUNT(*), 0),
    2)                                                          AS pct_delayed
FROM warehouse.fact_flights f
LEFT JOIN warehouse.dim_airports oa ON oa.iata_code = f.origin_airport
LEFT JOIN warehouse.dim_airports da ON da.iata_code = f.dest_airport
WHERE f.year = 2023
  AND NOT f.is_cancelled
GROUP BY f.route, f.origin_airport, f.dest_airport, oa.city, da.city
HAVING COUNT(*) >= 100                                          -- Only routes with enough data
ORDER BY avg_delay_min DESC
LIMIT 20;


-- ─── 4. Day-of-week delay patterns ────────────────────────────

SELECT
    d.day_of_week,
    d.day_name,
    COUNT(*)                                                    AS total_flights,
    ROUND(AVG(f.departure_delay_min) FILTER (
        WHERE NOT f.is_cancelled), 2)                           AS avg_dep_delay_min,
    ROUND(AVG(f.arrival_delay_min) FILTER (
        WHERE NOT f.is_cancelled), 2)                           AS avg_arr_delay_min,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE f.is_delayed)
        / NULLIF(COUNT(*) FILTER (WHERE NOT f.is_cancelled), 0),
    2)                                                          AS pct_delayed
FROM warehouse.fact_flights f
JOIN warehouse.dim_date d ON d.date_id = f.date_id
WHERE f.year = 2023
GROUP BY d.day_of_week, d.day_name
ORDER BY d.day_of_week;


-- ─── 5. Delay cause breakdown (carrier vs weather vs NAS) ─────

SELECT
    f.carrier_code,
    ROUND(AVG(NULLIF(f.carrier_delay_min, 0)), 2)               AS avg_carrier_delay,
    ROUND(AVG(NULLIF(f.weather_delay_min, 0)), 2)               AS avg_weather_delay,
    ROUND(AVG(NULLIF(f.nas_delay_min, 0)), 2)                   AS avg_nas_delay,
    ROUND(AVG(NULLIF(f.security_delay_min, 0)), 2)              AS avg_security_delay,
    ROUND(AVG(NULLIF(f.late_aircraft_delay_min, 0)), 2)         AS avg_late_aircraft_delay,

    -- Proportion of delay attributed to each cause
    ROUND(100.0 * SUM(COALESCE(f.carrier_delay_min, 0)) /
        NULLIF(SUM(COALESCE(f.carrier_delay_min, 0) +
                   COALESCE(f.weather_delay_min, 0) +
                   COALESCE(f.nas_delay_min, 0) +
                   COALESCE(f.late_aircraft_delay_min, 0)), 0), 1) AS pct_carrier_caused
FROM warehouse.fact_flights f
WHERE f.year = 2023
  AND f.arrival_delay_min >= 15
GROUP BY f.carrier_code
ORDER BY avg_carrier_delay DESC;


-- ─── 6. Window function: running delay total per carrier ───────
-- (Shows your SQL window function skills — interviewers love this)

SELECT
    f.year,
    f.month,
    f.carrier_code,
    COUNT(*)                                                    AS monthly_flights,
    ROUND(AVG(f.arrival_delay_min), 2)                          AS avg_delay,
    -- Cumulative average delay across months (running average)
    ROUND(AVG(AVG(f.arrival_delay_min)) OVER (
        PARTITION BY f.carrier_code
        ORDER BY f.year, f.month
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ), 2)                                                       AS cumulative_avg_delay,
    -- Rank carriers by on-time performance per month
    RANK() OVER (
        PARTITION BY f.year, f.month
        ORDER BY AVG(f.arrival_delay_min) ASC
    )                                                           AS monthly_rank
FROM warehouse.fact_flights f
WHERE NOT f.is_cancelled
GROUP BY f.year, f.month, f.carrier_code
ORDER BY f.year, f.month, monthly_rank;


-- ─── 7. Busiest airport hubs and their delay profiles ─────────

SELECT
    f.origin_airport                                            AS airport,
    ap.airport_name,
    ap.city,
    ap.state_code,
    COUNT(*)                                                    AS total_departures,
    ROUND(AVG(f.departure_delay_min) FILTER (
        WHERE NOT f.is_cancelled), 2)                           AS avg_dep_delay,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE f.is_cancelled)
        / COUNT(*),
    2)                                                          AS cancellation_rate_pct,
    COUNT(DISTINCT f.carrier_code)                              AS carrier_count
FROM warehouse.fact_flights f
LEFT JOIN warehouse.dim_airports ap ON ap.iata_code = f.origin_airport
WHERE f.year = 2023
GROUP BY f.origin_airport, ap.airport_name, ap.city, ap.state_code
HAVING COUNT(*) >= 10000
ORDER BY total_departures DESC
LIMIT 25;
