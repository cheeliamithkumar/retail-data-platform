-- Staging tables. Validated rows from Python land here before the star schema load.

CREATE TABLE IF NOT EXISTS stg_orders (
    stg_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    etl_run_id      BIGINT UNSIGNED NOT NULL,
    row_id          INT             NOT NULL,
    order_id        VARCHAR(25)     NOT NULL,
    order_date      DATE            NOT NULL,
    ship_date       DATE            NOT NULL,
    ship_mode       VARCHAR(30)     NOT NULL,
    customer_id     VARCHAR(20)     NOT NULL,
    customer_name   VARCHAR(100)    NOT NULL,
    segment         VARCHAR(30)     NOT NULL,
    country         VARCHAR(60)     NOT NULL,
    city            VARCHAR(100)    NOT NULL,
    state           VARCHAR(100)    NOT NULL,
    postal_code     VARCHAR(10)     NOT NULL,
    region          VARCHAR(30)     NOT NULL,
    product_id      VARCHAR(25)     NOT NULL,
    category        VARCHAR(50)     NOT NULL,
    sub_category    VARCHAR(50)     NOT NULL,
    product_name    VARCHAR(255)    NOT NULL,
    sales           DECIMAL(12,4)   NOT NULL,
    quantity        INT             NOT NULL,
    discount        DECIMAL(5,4)    NOT NULL,
    profit          DECIMAL(12,4)   NOT NULL,
    ship_days       INT             NULL,
    unit_price      DECIMAL(12,4)   NULL,
    row_hash        CHAR(64)        NOT NULL,
    business_hash   CHAR(64)        NOT NULL,
    source_file     VARCHAR(255)    NOT NULL,
    source_line     INT             NOT NULL,
    ingested_at     DATETIME        NOT NULL,
    PRIMARY KEY (stg_id),
    KEY ix_stg_orders_key (order_id, row_id),
    KEY ix_stg_orders_run (etl_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS stg_returns (
    stg_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    etl_run_id      BIGINT UNSIGNED NOT NULL,
    order_id        VARCHAR(25)     NOT NULL,
    returned        TINYINT(1)      NOT NULL,
    source_file     VARCHAR(255)    NOT NULL,
    source_line     INT             NOT NULL,
    ingested_at     DATETIME        NOT NULL,
    PRIMARY KEY (stg_id),
    KEY ix_stg_returns_order (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS stg_people (
    stg_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    etl_run_id       BIGINT UNSIGNED NOT NULL,
    regional_manager VARCHAR(100)    NOT NULL,
    region           VARCHAR(30)     NOT NULL,
    source_file      VARCHAR(255)    NOT NULL,
    source_line      INT             NOT NULL,
    ingested_at      DATETIME        NOT NULL,
    PRIMARY KEY (stg_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
