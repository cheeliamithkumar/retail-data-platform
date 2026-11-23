-- Region scorecard with manager and best state.
WITH region_totals AS (
    SELECT
        r.region,
        MAX(r.regional_manager)        AS regional_manager,
        SUM(f.sales)                   AS revenue,
        SUM(f.profit)                  AS profit,
        COUNT(DISTINCT f.order_id)     AS orders,
        COUNT(DISTINCT f.customer_key) AS customers
    FROM fact_sales f
    JOIN dim_region r ON r.region_key = f.region_key
    GROUP BY r.region
),
state_rank AS (
    SELECT
        r.region,
        r.state,
        SUM(f.sales) AS state_revenue,
        ROW_NUMBER() OVER (PARTITION BY r.region ORDER BY SUM(f.sales) DESC) AS rn
    FROM fact_sales f
    JOIN dim_region r ON r.region_key = f.region_key
    GROUP BY r.region, r.state
)
SELECT
    RANK() OVER (ORDER BY rt.revenue DESC)                     AS revenue_rank,
    rt.region,
    rt.regional_manager,
    ROUND(rt.revenue, 2)                                       AS revenue,
    ROUND(rt.profit, 2)                                        AS profit,
    ROUND(100 * rt.profit / NULLIF(rt.revenue, 0), 2)          AS profit_margin_pct,
    ROUND(100 * rt.revenue / SUM(rt.revenue) OVER (), 2)       AS revenue_share_pct,
    rt.orders,
    rt.customers,
    ROUND(rt.revenue / NULLIF(rt.orders, 0), 2)                AS average_order_value,
    sr.state                                                   AS top_state,
    ROUND(sr.state_revenue, 2)                                 AS top_state_revenue
FROM region_totals rt
JOIN state_rank sr ON sr.region = rt.region AND sr.rn = 1
ORDER BY revenue_rank;
