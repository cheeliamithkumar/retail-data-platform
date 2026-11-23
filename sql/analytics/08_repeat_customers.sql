-- =============================================================================
-- 08_repeat_customers.sql
-- Repeat-purchase behaviour: customers bucketed by number of orders, with the
-- overall repeat-customer rate computed in a scalar subquery.
-- =============================================================================
WITH customer_orders AS (
    SELECT
        f.customer_key,
        COUNT(DISTINCT f.order_id) AS order_count,
        SUM(f.sales)               AS revenue
    FROM fact_sales f
    GROUP BY f.customer_key
)
SELECT
    CASE
        WHEN order_count = 1 THEN '1 order (one-time)'
        WHEN order_count BETWEEN 2 AND 4 THEN '2-4 orders'
        WHEN order_count BETWEEN 5 AND 9 THEN '5-9 orders'
        ELSE '10+ orders'
    END                                                         AS order_frequency_band,
    COUNT(*)                                                    AS customers,
    ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)            AS pct_of_customers,
    ROUND(SUM(revenue), 2)                                      AS revenue,
    ROUND(100 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2)    AS pct_of_revenue,
    ROUND(AVG(revenue), 2)                                      AS avg_revenue_per_customer,
    (SELECT ROUND(100 * SUM(order_count > 1) / COUNT(*), 2)
       FROM customer_orders)                                    AS overall_repeat_customer_rate_pct
FROM customer_orders
GROUP BY order_frequency_band
ORDER BY MIN(order_count);
