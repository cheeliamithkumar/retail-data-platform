-- Upsert products. Keyed on id + name because the source reuses some product ids.
INSERT INTO dim_product (product_id, product_name, category, sub_category, etl_run_id)
SELECT src.product_id, src.product_name, src.category, src.sub_category, src.etl_run_id
FROM (
    SELECT product_id, product_name, category, sub_category, etl_run_id,
           ROW_NUMBER() OVER (PARTITION BY product_id, product_name
                              ORDER BY order_date DESC, row_id DESC) AS rn
    FROM stg_orders
    WHERE etl_run_id = @run_id
) AS src
WHERE src.rn = 1
ON DUPLICATE KEY UPDATE
    -- etl_run_id first: MySQL evaluates assignments left to right
    etl_run_id   = IF(dim_product.category <> src.category
                      OR dim_product.sub_category <> src.sub_category,
                      src.etl_run_id, dim_product.etl_run_id),
    category     = src.category,
    sub_category = src.sub_category;
