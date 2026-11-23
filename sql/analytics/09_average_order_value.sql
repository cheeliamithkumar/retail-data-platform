-- =============================================================================
-- 09_average_order_value.sql
-- Average order value by year and customer segment, computed at ORDER grain
-- (line items are first rolled up to orders in a CTE).
-- =============================================================================
WITH orders AS (
    SELECT
        f.order_id,
        MIN(d.calendar_year) AS order_year,
        MIN(c.segment)       AS segment,
        SUM(f.sales)         AS order_value,
        SUM(f.quantity)      AS order_units,
        COUNT(*)             AS order_lines
    FROM fact_sales f
    JOIN dim_date d     ON d.date_key = f.order_date_key
    JOIN dim_customer c ON c.customer_key = f.customer_key
    GROUP BY f.order_id
)
SELECT
    order_year,
    segment,
    COUNT(*)                     AS orders,
    ROUND(AVG(order_value), 2)   AS average_order_value,
    ROUND(AVG(order_units), 2)   AS avg_units_per_order,
    ROUND(AVG(order_lines), 2)   AS avg_lines_per_order,
    ROUND(MAX(order_value), 2)   AS largest_order
FROM orders
GROUP BY order_year, segment
ORDER BY order_year, segment;
