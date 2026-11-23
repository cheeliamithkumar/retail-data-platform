-- Margin by discount band.
SELECT
    CASE
        WHEN f.discount = 0     THEN '0% (no discount)'
        WHEN f.discount <= 0.10 THEN '1-10%'
        WHEN f.discount <= 0.20 THEN '11-20%'
        WHEN f.discount <= 0.40 THEN '21-40%'
        ELSE '41%+'
    END                                                         AS discount_band,
    COUNT(*)                                                    AS order_lines,
    ROUND(SUM(f.sales), 2)                                      AS revenue,
    ROUND(SUM(f.profit), 2)                                     AS profit,
    ROUND(100 * SUM(f.profit) / NULLIF(SUM(f.sales), 0), 2)     AS profit_margin_pct,
    ROUND(100 * AVG(f.profit < 0), 1)                           AS pct_lines_loss_making
FROM fact_sales f
GROUP BY discount_band
ORDER BY MIN(f.discount);
