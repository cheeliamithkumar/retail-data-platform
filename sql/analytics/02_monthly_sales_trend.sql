-- Monthly sales with MoM growth, 3-month moving average and YTD.
WITH monthly AS (
    SELECT
        d.calendar_year,
        d.month_number,
        d.year_month_label,
        SUM(f.sales)               AS revenue,
        SUM(f.profit)              AS profit,
        COUNT(DISTINCT f.order_id) AS orders
    FROM fact_sales f
    JOIN dim_date d ON d.date_key = f.order_date_key
    GROUP BY d.calendar_year, d.month_number, d.year_month_label
)
SELECT
    year_month_label,
    ROUND(revenue, 2)                                              AS revenue,
    ROUND(profit, 2)                                               AS profit,
    orders,
    ROUND(100 * (revenue - LAG(revenue) OVER w)
              / NULLIF(LAG(revenue) OVER w, 0), 2)                 AS mom_growth_pct,
    ROUND(AVG(revenue) OVER (ORDER BY calendar_year, month_number
                             ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS revenue_3m_moving_avg,
    ROUND(SUM(revenue) OVER (PARTITION BY calendar_year ORDER BY month_number), 2) AS revenue_ytd
FROM monthly
WINDOW w AS (ORDER BY calendar_year, month_number)
ORDER BY calendar_year, month_number;
