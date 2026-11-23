-- Return rate by category and region.
SELECT
    p.category,
    r.region,
    COUNT(DISTINCT f.order_id)                                              AS orders,
    COUNT(DISTINCT CASE WHEN f.is_returned = 1 THEN f.order_id END)         AS returned_orders,
    ROUND(100 * COUNT(DISTINCT CASE WHEN f.is_returned = 1 THEN f.order_id END)
              / NULLIF(COUNT(DISTINCT f.order_id), 0), 2)                   AS return_rate_pct,
    ROUND(SUM(CASE WHEN f.is_returned = 1 THEN f.sales ELSE 0 END), 2)      AS returned_revenue
FROM fact_sales f
JOIN dim_product p ON p.product_key = f.product_key
JOIN dim_region  r ON r.region_key = f.region_key
GROUP BY p.category, r.region
ORDER BY return_rate_pct DESC;
