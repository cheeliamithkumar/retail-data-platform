-- Yearly totals and YoY growth.
WITH yearly AS (
    SELECT
        d.calendar_year,
        SUM(f.sales)                   AS revenue,
        SUM(f.profit)                  AS profit,
        COUNT(DISTINCT f.order_id)     AS orders,
        COUNT(DISTINCT f.customer_key) AS customers
    FROM fact_sales f
    JOIN dim_date d ON d.date_key = f.order_date_key
    GROUP BY d.calendar_year
)
SELECT
    calendar_year,
    ROUND(revenue, 2)                                                      AS revenue,
    ROUND(LAG(revenue) OVER (ORDER BY calendar_year), 2)                   AS prior_year_revenue,
    ROUND(100 * (revenue / NULLIF(LAG(revenue) OVER (ORDER BY calendar_year), 0) - 1), 2) AS revenue_yoy_pct,
    ROUND(profit, 2)                                                       AS profit,
    ROUND(100 * (profit / NULLIF(LAG(profit) OVER (ORDER BY calendar_year), 0) - 1), 2)   AS profit_yoy_pct,
    ROUND(100 * profit / NULLIF(revenue, 0), 2)                            AS profit_margin_pct,
    orders,
    ROUND(100 * (orders / NULLIF(LAG(orders) OVER (ORDER BY calendar_year), 0) - 1), 2)   AS orders_yoy_pct,
    customers
FROM yearly
ORDER BY calendar_year;
