-- =============================================================================
-- 01_kpi_overview.sql
-- Headline KPIs: total revenue, total profit, profit margin, orders, customers,
-- units, average order value and return rate.
-- =============================================================================
SELECT
    ROUND(SUM(f.sales), 2)                                         AS total_revenue,
    ROUND(SUM(f.profit), 2)                                        AS total_profit,
    ROUND(100 * SUM(f.profit) / NULLIF(SUM(f.sales), 0), 2)        AS profit_margin_pct,
    COUNT(DISTINCT f.order_id)                                     AS total_orders,
    COUNT(DISTINCT f.customer_key)                                 AS total_customers,
    SUM(f.quantity)                                                AS units_sold,
    ROUND(SUM(f.sales) / NULLIF(COUNT(DISTINCT f.order_id), 0), 2) AS average_order_value,
    ROUND(100 * COUNT(DISTINCT CASE WHEN f.is_returned = 1 THEN f.order_id END)
              / NULLIF(COUNT(DISTINCT f.order_id), 0), 2)          AS order_return_rate_pct
FROM fact_sales f;
