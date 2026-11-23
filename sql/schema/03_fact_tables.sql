-- =============================================================================
-- 03_fact_tables.sql
-- fact_sales: grain = one order line (one product on one order).
-- The source key (order_id, source_row_id) is UNIQUE, which makes every load
-- idempotent: a re-sent line updates (if changed) instead of duplicating.
-- =============================================================================

CREATE TABLE IF NOT EXISTS fact_sales (
    sales_key        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    order_id         VARCHAR(25)     NOT NULL,
    source_row_id    INT             NOT NULL,
    order_date_key   INT             NOT NULL,
    ship_date_key    INT             NOT NULL,
    customer_key     INT UNSIGNED    NOT NULL,
    product_key      INT UNSIGNED    NOT NULL,
    region_key       INT UNSIGNED    NOT NULL,
    ship_mode        VARCHAR(30)     NOT NULL,
    quantity         INT             NOT NULL,
    sales            DECIMAL(12,4)   NOT NULL,
    discount         DECIMAL(5,4)    NOT NULL,
    profit           DECIMAL(12,4)   NOT NULL,
    unit_price       DECIMAL(12,4)   NULL,
    ship_days        INT             NULL,
    is_returned      TINYINT(1)      NOT NULL DEFAULT 0,
    row_hash         CHAR(64)        NOT NULL COMMENT 'SHA-256 of all source fields; detects changed records',
    business_hash    CHAR(64)        NOT NULL COMMENT 'SHA-256 excluding row id; detects duplicate transactions',
    etl_run_id       BIGINT UNSIGNED NOT NULL COMMENT 'Run that last inserted/updated the row',
    created_at       TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (sales_key),
    UNIQUE KEY uq_fact_sales_source (order_id, source_row_id),
    KEY ix_fact_sales_order_date (order_date_key),
    KEY ix_fact_sales_ship_date (ship_date_key),
    KEY ix_fact_sales_customer (customer_key, order_date_key),
    KEY ix_fact_sales_product (product_key),
    KEY ix_fact_sales_region (region_key),
    KEY ix_fact_sales_business_hash (business_hash),
    CONSTRAINT fk_fact_sales_order_date FOREIGN KEY (order_date_key) REFERENCES dim_date (date_key),
    CONSTRAINT fk_fact_sales_ship_date  FOREIGN KEY (ship_date_key)  REFERENCES dim_date (date_key),
    CONSTRAINT fk_fact_sales_customer   FOREIGN KEY (customer_key)   REFERENCES dim_customer (customer_key),
    CONSTRAINT fk_fact_sales_product    FOREIGN KEY (product_key)    REFERENCES dim_product (product_key),
    CONSTRAINT fk_fact_sales_region     FOREIGN KEY (region_key)     REFERENCES dim_region (region_key),
    CONSTRAINT ck_fact_sales_quantity CHECK (quantity > 0),
    CONSTRAINT ck_fact_sales_sales    CHECK (sales > 0),
    CONSTRAINT ck_fact_sales_discount CHECK (discount >= 0 AND discount < 1),
    CONSTRAINT ck_fact_sales_profit   CHECK (profit <= sales)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
