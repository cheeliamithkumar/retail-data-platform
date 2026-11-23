-- =============================================================================
-- 04_top_products.sql
-- Top 10 products by revenue, with profit rank and share of total revenue.
-- =============================================================================
WITH product_sales AS (
    SELECT
        p.product_key,
        p.product_id,
        p.product_name,
        p.category,
        p.sub_category,
        SUM(f.sales)    AS revenue,
        SUM(f.profit)   AS profit,
        SUM(f.quantity) AS units
    FROM fact_sales f
    JOIN dim_product p ON p.product_key = f.product_key
    GROUP BY p.product_key, p.product_id, p.product_name, p.category, p.sub_category
),
ranked AS (
    SELECT
        ps.*,
        RANK() OVER (ORDER BY revenue DESC)                   AS revenue_rank,
        RANK() OVER (ORDER BY profit DESC)                    AS profit_rank,
        100 * revenue / SUM(revenue) OVER ()                  AS revenue_share_pct
    FROM product_sales ps
)
SELECT
    revenue_rank,
    product_id,
    product_name,
    category,
    sub_category,
    units,
    ROUND(revenue, 2)                               AS revenue,
    ROUND(profit, 2)                                AS profit,
    ROUND(100 * profit / NULLIF(revenue, 0), 2)     AS profit_margin_pct,
    profit_rank,
    ROUND(revenue_share_pct, 3)                     AS revenue_share_pct
FROM ranked
WHERE revenue_rank <= 10
ORDER BY revenue_rank;
