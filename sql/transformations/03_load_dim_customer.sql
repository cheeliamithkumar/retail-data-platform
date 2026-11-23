-- Upsert customers. If a customer shows up more than once, the latest order wins.
INSERT INTO dim_customer (customer_id, customer_name, segment, etl_run_id)
SELECT src.customer_id, src.customer_name, src.segment, src.etl_run_id
FROM (
    SELECT customer_id, customer_name, segment, etl_run_id,
           ROW_NUMBER() OVER (PARTITION BY customer_id
                              ORDER BY order_date DESC, row_id DESC) AS rn
    FROM stg_orders
    WHERE etl_run_id = @run_id
) AS src
WHERE src.rn = 1
ON DUPLICATE KEY UPDATE
    -- etl_run_id first: MySQL evaluates assignments left to right
    etl_run_id    = IF(dim_customer.customer_name <> src.customer_name
                       OR dim_customer.segment <> src.segment,
                       src.etl_run_id, dim_customer.etl_run_id),
    customer_name = src.customer_name,
    segment       = src.segment;
