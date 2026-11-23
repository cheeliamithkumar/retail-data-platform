-- Flag returned orders. Flags are never cleared.
UPDATE fact_sales f
JOIN stg_returns r ON r.order_id = f.order_id
SET f.is_returned = 1
WHERE r.etl_run_id = @run_id
  AND r.returned = 1
  AND f.is_returned = 0;
