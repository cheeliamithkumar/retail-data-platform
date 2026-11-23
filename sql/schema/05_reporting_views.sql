-- =============================================================================
-- 05_reporting_views.sql
-- Views for Power BI and ad-hoc analysis. Power BI should import the star
-- schema tables directly; these views serve flat exports and the monitoring page.
-- =============================================================================

CREATE OR REPLACE VIEW vw_sales_enriched AS
SELECT
    f.sales_key,
    f.order_id,
    f.source_row_id,
    od.full_date          AS order_date,
    sd.full_date          AS ship_date,
    od.calendar_year      AS order_year,
    od.month_number       AS order_month,
    od.year_month_label   AS order_year_month,
    c.customer_id,
    c.customer_name,
    c.segment,
    p.product_id,
    p.product_name,
    p.category,
    p.sub_category,
    r.country,
    r.region,
    r.state,
    r.city,
    r.postal_code,
    r.regional_manager,
    f.ship_mode,
    f.ship_days,
    f.quantity,
    f.unit_price,
    f.discount,
    f.sales,
    f.profit,
    f.is_returned
FROM fact_sales f
JOIN dim_date     od ON od.date_key = f.order_date_key
JOIN dim_date     sd ON sd.date_key = f.ship_date_key
JOIN dim_customer c  ON c.customer_key = f.customer_key
JOIN dim_product  p  ON p.product_key = f.product_key
JOIN dim_region   r  ON r.region_key = f.region_key;

CREATE OR REPLACE VIEW vw_pipeline_run_history AS
SELECT
    run_id,
    pipeline_name,
    start_ts,
    end_ts,
    TIMESTAMPDIFF(SECOND, start_ts, end_ts) AS duration_seconds,
    status,
    records_extracted,
    records_valid,
    records_rejected,
    records_loaded,
    records_updated,
    records_unchanged,
    ROUND(100 * records_rejected / NULLIF(records_extracted, 0), 2) AS rejection_rate_pct,
    checks_failed,
    checks_warning,
    error_message
FROM etl_pipeline_runs;

CREATE OR REPLACE VIEW vw_dq_check_results AS
SELECT
    d.run_id,
    r.start_ts AS run_start_ts,
    d.source_name,
    d.check_name,
    d.check_category,
    d.severity,
    d.records_checked,
    d.records_failed,
    d.check_status
FROM etl_data_quality_results d
JOIN etl_pipeline_runs r ON r.run_id = d.run_id;

CREATE OR REPLACE VIEW vw_rejection_summary AS
SELECT
    run_id,
    source_name,
    rejection_reasons,
    COUNT(*) AS rejected_records
FROM etl_rejected_records
GROUP BY run_id, source_name, rejection_reasons;
