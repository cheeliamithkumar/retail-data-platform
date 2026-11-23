-- ETL run history, file registry, DQ results and rejected records.

CREATE TABLE IF NOT EXISTS etl_pipeline_runs (
    run_id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_uuid           CHAR(36)        NOT NULL,
    pipeline_name      VARCHAR(100)    NOT NULL,
    start_ts           DATETIME(3)     NOT NULL,
    end_ts             DATETIME(3)     NULL,
    status             ENUM('RUNNING','SUCCESS','SUCCESS_WITH_WARNINGS','NO_NEW_DATA','FAILED') NOT NULL,
    records_extracted  INT             NOT NULL DEFAULT 0,
    records_valid      INT             NOT NULL DEFAULT 0,
    records_rejected   INT             NOT NULL DEFAULT 0,
    records_loaded     INT             NOT NULL DEFAULT 0 COMMENT 'New fact rows inserted',
    records_updated    INT             NOT NULL DEFAULT 0 COMMENT 'Existing fact rows changed',
    records_unchanged  INT             NOT NULL DEFAULT 0 COMMENT 'Re-sent rows identical to warehouse',
    checks_failed      INT             NOT NULL DEFAULT 0,
    checks_warning     INT             NOT NULL DEFAULT 0,
    triggered_by       VARCHAR(100)    NULL,
    error_message      TEXT            NULL,
    PRIMARY KEY (run_id),
    UNIQUE KEY uq_etl_runs_uuid (run_uuid),
    KEY ix_etl_runs_start (start_ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- One row per distinct source file content; enables file-level incremental loads.
CREATE TABLE IF NOT EXISTS etl_file_registry (
    file_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_id             BIGINT UNSIGNED NOT NULL,
    source_name        VARCHAR(50)     NOT NULL,
    file_name          VARCHAR(255)    NOT NULL,
    file_checksum      CHAR(64)        NOT NULL,
    file_size_bytes    BIGINT          NOT NULL,
    records_extracted  INT             NOT NULL,
    records_valid      INT             NOT NULL,
    records_rejected   INT             NOT NULL,
    processed_at       DATETIME        NOT NULL,
    PRIMARY KEY (file_id),
    UNIQUE KEY uq_file_registry (source_name, file_checksum),
    CONSTRAINT fk_file_registry_run FOREIGN KEY (run_id) REFERENCES etl_pipeline_runs (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS etl_data_quality_results (
    result_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_id           BIGINT UNSIGNED NOT NULL,
    source_name      VARCHAR(50)     NOT NULL,
    check_name       VARCHAR(100)    NOT NULL,
    check_category   VARCHAR(50)     NOT NULL,
    severity         VARCHAR(10)     NOT NULL,
    records_checked  INT             NOT NULL,
    records_failed   INT             NOT NULL,
    check_status     VARCHAR(10)     NOT NULL,
    created_at       TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (result_id),
    KEY ix_dq_results_run (run_id),
    CONSTRAINT fk_dq_results_run FOREIGN KEY (run_id) REFERENCES etl_pipeline_runs (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS etl_rejected_records (
    rejected_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_id             BIGINT UNSIGNED NOT NULL,
    source_name        VARCHAR(50)     NOT NULL,
    source_file        VARCHAR(255)    NOT NULL,
    source_line        INT             NULL,
    rejection_reasons  VARCHAR(1000)   NOT NULL,
    raw_record         JSON            NOT NULL,
    created_at         TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (rejected_id),
    KEY ix_rejected_run (run_id),
    CONSTRAINT fk_rejected_run FOREIGN KEY (run_id) REFERENCES etl_pipeline_runs (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
