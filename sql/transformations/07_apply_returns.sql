-- =============================================================================
-- 07_apply_returns.sql
-- Flag every line of a returned order. Returns accumulate: a flag is never unset.
-- Runs after the fact load so returns for orders in the same batch are applied.
-- =============================================================================
UPDATE fact_sales f
JOIN stg_returns r ON r.order_id = f.order_id
SET f.is_returned = 1
WHERE r.etl_run_id = @run_id
  AND r.returned = 1
  AND f.is_returned = 0;
