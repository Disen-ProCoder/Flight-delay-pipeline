-- ============================================================
-- sql/schema/04_populate_dim_date.sql
-- Generates the full calendar dimension from 2018 to 2030.
-- Run once after creating the tables.
-- ============================================================

INSERT INTO warehouse.dim_date (
    date_id, full_date, year, quarter, month, month_name,
    week_of_year, day_of_month, day_of_week, day_name,
    is_weekend, season
)
SELECT
    TO_CHAR(d, 'YYYYMMDD')::INTEGER                    AS date_id,
    d                                                   AS full_date,
    EXTRACT(YEAR    FROM d)::SMALLINT                  AS year,
    EXTRACT(QUARTER FROM d)::SMALLINT                  AS quarter,
    EXTRACT(MONTH   FROM d)::SMALLINT                  AS month,
    TO_CHAR(d, 'Month')                                AS month_name,
    EXTRACT(WEEK    FROM d)::SMALLINT                  AS week_of_year,
    EXTRACT(DAY     FROM d)::SMALLINT                  AS day_of_month,
    EXTRACT(ISODOW  FROM d)::SMALLINT                  AS day_of_week,
    TO_CHAR(d, 'Day')                                  AS day_name,
    EXTRACT(ISODOW  FROM d) IN (6, 7)                  AS is_weekend,
    CASE
        WHEN EXTRACT(MONTH FROM d) IN (12, 1, 2)  THEN 'Winter'
        WHEN EXTRACT(MONTH FROM d) IN (3, 4, 5)   THEN 'Spring'
        WHEN EXTRACT(MONTH FROM d) IN (6, 7, 8)   THEN 'Summer'
        ELSE 'Fall'
    END                                                AS season
FROM GENERATE_SERIES(
    '2018-01-01'::DATE,
    '2030-12-31'::DATE,
    '1 day'::INTERVAL
) AS d
ON CONFLICT (date_id) DO NOTHING;

-- Mark major US holidays (expand as needed)
UPDATE warehouse.dim_date SET is_holiday = TRUE, holiday_name = 'New Year''s Day'
    WHERE month = 1  AND day_of_month = 1;
UPDATE warehouse.dim_date SET is_holiday = TRUE, holiday_name = 'Independence Day'
    WHERE month = 7  AND day_of_month = 4;
UPDATE warehouse.dim_date SET is_holiday = TRUE, holiday_name = 'Christmas Day'
    WHERE month = 12 AND day_of_month = 25;
UPDATE warehouse.dim_date SET is_holiday = TRUE, holiday_name = 'Christmas Eve'
    WHERE month = 12 AND day_of_month = 24;
UPDATE warehouse.dim_date SET is_holiday = TRUE, holiday_name = 'New Year''s Eve'
    WHERE month = 12 AND day_of_month = 31;

SELECT COUNT(*) AS rows_inserted FROM warehouse.dim_date;
