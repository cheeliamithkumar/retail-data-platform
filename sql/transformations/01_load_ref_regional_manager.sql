-- =============================================================================
-- 01_load_ref_regional_manager.sql
-- Upsert region -> manager reference data from this run's People extract.
-- Requires session variable @run_id.
-- =============================================================================
INSERT INTO ref_regional_manager (region, regional_manager, etl_run_id)
SELECT src.region, src.regional_manager, src.etl_run_id
FROM (
    SELECT region, regional_manager, etl_run_id
    FROM stg_people
    WHERE etl_run_id = @run_id
) AS src
ON DUPLICATE KEY UPDATE
    regional_manager = src.regional_manager,
    etl_run_id       = src.etl_run_id;
