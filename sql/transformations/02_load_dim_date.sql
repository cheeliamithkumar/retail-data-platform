-- Fill dim_date with every day of the years covered by this batch.
SET SESSION cte_max_recursion_depth = 100000;

INSERT IGNORE INTO dim_date (
    date_key, full_date, day_of_month, day_name, day_of_week, day_of_year,
    week_of_year, month_number, month_name, month_short, quarter_number,
    quarter_name, calendar_year, year_month_label, year_quarter_label,
    first_day_of_month, is_weekend
)
WITH RECURSIVE bounds AS (
    SELECT MAKEDATE(YEAR(MIN(order_date)), 1)                       AS start_date,
           LAST_DAY(DATE_FORMAT(MAX(ship_date), '%Y-12-01'))         AS end_date
    FROM stg_orders
    WHERE etl_run_id = @run_id
),
calendar (d, end_date) AS (
    SELECT start_date, end_date FROM bounds WHERE start_date IS NOT NULL
    UNION ALL
    SELECT d + INTERVAL 1 DAY, end_date FROM calendar WHERE d < end_date
)
SELECT
    CAST(DATE_FORMAT(d, '%Y%m%d') AS UNSIGNED)          AS date_key,
    d                                                   AS full_date,
    DAYOFMONTH(d)                                       AS day_of_month,
    DAYNAME(d)                                          AS day_name,
    WEEKDAY(d) + 1                                      AS day_of_week,
    DAYOFYEAR(d)                                        AS day_of_year,
    WEEK(d, 3)                                          AS week_of_year,
    MONTH(d)                                            AS month_number,
    MONTHNAME(d)                                        AS month_name,
    DATE_FORMAT(d, '%b')                                AS month_short,
    QUARTER(d)                                          AS quarter_number,
    CONCAT('Q', QUARTER(d))                             AS quarter_name,
    YEAR(d)                                             AS calendar_year,
    DATE_FORMAT(d, '%Y-%m')                             AS year_month_label,
    CONCAT(YEAR(d), '-Q', QUARTER(d))                   AS year_quarter_label,
    DATE_FORMAT(d, '%Y-%m-01')                          AS first_day_of_month,
    WEEKDAY(d) >= 5                                     AS is_weekend
FROM calendar;
