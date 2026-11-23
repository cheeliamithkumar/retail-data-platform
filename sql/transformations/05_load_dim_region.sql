-- =============================================================================
-- 05_load_dim_region.sql
-- Ship-to locations (country/state/city/postal code) with their sales region,
-- then (re)apply regional managers from the reference table.
-- =============================================================================
INSERT INTO dim_region (country, region, state, city, postal_code, etl_run_id)
SELECT src.country, src.region, src.state, src.city, src.postal_code, src.etl_run_id
FROM (
    SELECT country, region, state, city, postal_code, etl_run_id,
           ROW_NUMBER() OVER (PARTITION BY country, state, city, postal_code
                              ORDER BY order_date DESC, row_id DESC) AS rn
    FROM stg_orders
    WHERE etl_run_id = @run_id
) AS src
WHERE src.rn = 1
ON DUPLICATE KEY UPDATE
    -- etl_run_id first: MySQL evaluates assignments left to right
    etl_run_id = IF(dim_region.region <> src.region, src.etl_run_id, dim_region.etl_run_id),
    region     = src.region;

UPDATE dim_region d
JOIN ref_regional_manager m ON m.region = d.region
SET d.regional_manager = m.regional_manager
WHERE NOT (d.regional_manager <=> m.regional_manager);
