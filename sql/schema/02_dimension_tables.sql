-- Dimension tables (SCD type 1) plus the region -> manager lookup.

-- Reference data: one manager per region (source: People sheet).
CREATE TABLE IF NOT EXISTS ref_regional_manager (
    region           VARCHAR(30)  NOT NULL,
    regional_manager VARCHAR(100) NOT NULL,
    etl_run_id       BIGINT UNSIGNED NOT NULL,
    updated_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (region)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Date dimension (role-playing: order date and ship date). Key = YYYYMMDD.
CREATE TABLE IF NOT EXISTS dim_date (
    date_key            INT          NOT NULL,
    full_date           DATE         NOT NULL,
    day_of_month        TINYINT      NOT NULL,
    day_name            VARCHAR(10)  NOT NULL,
    day_of_week         TINYINT      NOT NULL COMMENT '1 = Monday ... 7 = Sunday',
    day_of_year         SMALLINT     NOT NULL,
    week_of_year        TINYINT      NOT NULL COMMENT 'ISO week',
    month_number        TINYINT      NOT NULL,
    month_name          VARCHAR(10)  NOT NULL,
    month_short         CHAR(3)      NOT NULL,
    quarter_number      TINYINT      NOT NULL,
    quarter_name        CHAR(2)      NOT NULL,
    calendar_year       SMALLINT     NOT NULL,
    year_month_label    CHAR(7)      NOT NULL COMMENT 'YYYY-MM',
    year_quarter_label  CHAR(7)      NOT NULL COMMENT 'YYYY-Qn',
    first_day_of_month  DATE         NOT NULL,
    is_weekend          TINYINT(1)   NOT NULL,
    PRIMARY KEY (date_key),
    UNIQUE KEY uq_dim_date_full_date (full_date),
    KEY ix_dim_date_year_month (calendar_year, month_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dim_customer (
    customer_key    INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    customer_id     VARCHAR(20)   NOT NULL,
    customer_name   VARCHAR(100)  NOT NULL,
    segment         VARCHAR(30)   NOT NULL,
    etl_run_id      BIGINT UNSIGNED NOT NULL,
    created_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (customer_key),
    UNIQUE KEY uq_dim_customer_id (customer_id),
    KEY ix_dim_customer_segment (segment)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- The source re-uses some Product IDs for different products, so the natural
-- key is (product_id, product_name) to avoid mis-attributing sales.
CREATE TABLE IF NOT EXISTS dim_product (
    product_key     INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    product_id      VARCHAR(25)   NOT NULL,
    product_name    VARCHAR(255)  NOT NULL,
    category        VARCHAR(50)   NOT NULL,
    sub_category    VARCHAR(50)   NOT NULL,
    etl_run_id      BIGINT UNSIGNED NOT NULL,
    created_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (product_key),
    UNIQUE KEY uq_dim_product_nk (product_id, product_name),
    KEY ix_dim_product_category (category, sub_category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Geography at ship-to location grain, rolled up to region with its manager.
CREATE TABLE IF NOT EXISTS dim_region (
    region_key       INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    country          VARCHAR(60)   NOT NULL,
    region           VARCHAR(30)   NOT NULL,
    state            VARCHAR(100)  NOT NULL,
    city             VARCHAR(100)  NOT NULL,
    postal_code      VARCHAR(10)   NOT NULL,
    regional_manager VARCHAR(100)  NULL,
    etl_run_id       BIGINT UNSIGNED NOT NULL,
    created_at       TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (region_key),
    UNIQUE KEY uq_dim_region_nk (country, state, city, postal_code),
    KEY ix_dim_region_region (region),
    KEY ix_dim_region_state (state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
