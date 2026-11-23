-- RFM segmentation (recency / frequency / monetary quartiles).
WITH ref AS (
    SELECT MAX(d.full_date) AS as_of_date
    FROM fact_sales f JOIN dim_date d ON d.date_key = f.order_date_key
),
customer_metrics AS (
    SELECT
        c.customer_key,
        c.customer_id,
        c.customer_name,
        c.segment,
        DATEDIFF((SELECT as_of_date FROM ref), MAX(d.full_date)) AS recency_days,
        COUNT(DISTINCT f.order_id)                               AS frequency,
        SUM(f.sales)                                             AS monetary
    FROM fact_sales f
    JOIN dim_customer c ON c.customer_key = f.customer_key
    JOIN dim_date d     ON d.date_key = f.order_date_key
    GROUP BY c.customer_key, c.customer_id, c.customer_name, c.segment
),
scored AS (
    SELECT
        cm.*,
        NTILE(4) OVER (ORDER BY recency_days DESC) AS r_score,   -- 4 = most recent
        NTILE(4) OVER (ORDER BY frequency ASC)     AS f_score,   -- 4 = most frequent
        NTILE(4) OVER (ORDER BY monetary ASC)      AS m_score    -- 4 = highest spend
    FROM customer_metrics cm
),
segmented AS (
    SELECT
        s.*,
        CASE
            WHEN r_score >= 3 AND f_score >= 3 AND m_score >= 3 THEN 'Champions'
            WHEN r_score >= 3 AND f_score >= 2                  THEN 'Loyal'
            WHEN r_score >= 3                                    THEN 'Recent / Promising'
            WHEN r_score = 2 AND (f_score >= 3 OR m_score >= 3)  THEN 'Needs Attention'
            WHEN r_score <= 2 AND m_score >= 3                   THEN 'At Risk (High Value)'
            ELSE 'Hibernating'
        END AS rfm_segment
    FROM scored s
)
SELECT
    rfm_segment,
    COUNT(*)                                                AS customers,
    ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)        AS pct_of_customers,
    ROUND(SUM(monetary), 2)                                 AS revenue,
    ROUND(100 * SUM(monetary) / SUM(SUM(monetary)) OVER (), 1) AS pct_of_revenue,
    ROUND(AVG(recency_days), 0)                             AS avg_recency_days,
    ROUND(AVG(frequency), 1)                                AS avg_orders,
    ROUND(AVG(monetary), 2)                                 AS avg_customer_value
FROM segmented
GROUP BY rfm_segment
ORDER BY revenue DESC;
