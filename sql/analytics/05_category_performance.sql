-- Sub-categories ranked within each category, with loss-makers flagged.
SELECT
    p.category,
    p.sub_category,
    ROUND(SUM(f.sales), 2)                                          AS revenue,
    ROUND(SUM(f.profit), 2)                                         AS profit,
    ROUND(100 * SUM(f.profit) / NULLIF(SUM(f.sales), 0), 2)         AS profit_margin_pct,
    ROUND(AVG(f.discount) * 100, 1)                                 AS avg_discount_pct,
    DENSE_RANK() OVER (PARTITION BY p.category ORDER BY SUM(f.sales) DESC) AS revenue_rank_in_category,
    ROUND(100 * SUM(f.sales) / SUM(SUM(f.sales)) OVER (PARTITION BY p.category), 2) AS share_of_category_pct,
    CASE WHEN SUM(f.profit) < 0 THEN 'Loss-making' ELSE 'Profitable' END AS profitability
FROM fact_sales f
JOIN dim_product p ON p.product_key = f.product_key
GROUP BY p.category, p.sub_category
ORDER BY p.category, revenue_rank_in_category;
