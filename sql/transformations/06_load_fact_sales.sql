-- Incremental fact load: update rows whose hash changed, insert new ones.
DROP TEMPORARY TABLE IF EXISTS tmp_fact_sales_resolved;

-- PK declared inline: ALTER TABLE would cause an implicit COMMIT mid-load.
CREATE TEMPORARY TABLE tmp_fact_sales_resolved (PRIMARY KEY (order_id, source_row_id))
SELECT
    s.order_id,
    s.row_id            AS source_row_id,
    od.date_key         AS order_date_key,
    sd.date_key         AS ship_date_key,
    c.customer_key,
    p.product_key,
    r.region_key,
    s.ship_mode,
    s.quantity,
    s.sales,
    s.discount,
    s.profit,
    s.unit_price,
    s.ship_days,
    s.row_hash,
    s.business_hash,
    s.etl_run_id
FROM stg_orders s
JOIN dim_date     od ON od.full_date = s.order_date
JOIN dim_date     sd ON sd.full_date = s.ship_date
JOIN dim_customer c  ON c.customer_id = s.customer_id
JOIN dim_product  p  ON p.product_id = s.product_id AND p.product_name = s.product_name
JOIN dim_region   r  ON r.country = s.country AND r.state = s.state
                    AND r.city = s.city AND r.postal_code = s.postal_code
WHERE s.etl_run_id = @run_id;

UPDATE fact_sales f
JOIN tmp_fact_sales_resolved t
  ON t.order_id = f.order_id AND t.source_row_id = f.source_row_id
SET f.order_date_key = t.order_date_key,
    f.ship_date_key  = t.ship_date_key,
    f.customer_key   = t.customer_key,
    f.product_key    = t.product_key,
    f.region_key     = t.region_key,
    f.ship_mode      = t.ship_mode,
    f.quantity       = t.quantity,
    f.sales          = t.sales,
    f.discount       = t.discount,
    f.profit         = t.profit,
    f.unit_price     = t.unit_price,
    f.ship_days      = t.ship_days,
    f.row_hash       = t.row_hash,
    f.business_hash  = t.business_hash,
    f.etl_run_id     = t.etl_run_id
WHERE f.row_hash <> t.row_hash;

INSERT INTO fact_sales (
    order_id, source_row_id, order_date_key, ship_date_key, customer_key,
    product_key, region_key, ship_mode, quantity, sales, discount, profit,
    unit_price, ship_days, row_hash, business_hash, etl_run_id
)
SELECT
    t.order_id, t.source_row_id, t.order_date_key, t.ship_date_key, t.customer_key,
    t.product_key, t.region_key, t.ship_mode, t.quantity, t.sales, t.discount, t.profit,
    t.unit_price, t.ship_days, t.row_hash, t.business_hash, t.etl_run_id
FROM tmp_fact_sales_resolved t
LEFT JOIN fact_sales f
  ON f.order_id = t.order_id AND f.source_row_id = t.source_row_id
WHERE f.sales_key IS NULL;
