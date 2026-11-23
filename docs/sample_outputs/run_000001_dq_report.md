# Data Quality & Execution Report - Run 1

- **Status:** SUCCESS_WITH_WARNINGS
- **Started:** 2026-11-23T14:04:09
- **Finished:** 2026-11-23T14:04:13
- **Duration (s):** 4.84
- **Checks:** 41 total / 37 passed / 1 failed / 3 warnings

## Sources

| Source | File | Status | Extracted | Malformed | Removed (dedup) | Rejected | Valid | Warnings |
|---|---|---|---:|---:|---:|---:|---:|---:|
| people | superstore_people.csv | PROCESSED | 4 | 0 | 0 | 0 | 4 | 0 |
| orders | superstore_orders.csv | PROCESSED | 9,994 | 0 | 0 | 1 | 9,993 | 687 |
| returns | superstore_returns.csv | PROCESSED | 800 | 0 | 504 | 0 | 296 | 0 |

## Warehouse Load

| Metric | Value |
|---|---:|
| staged_stg_people | 4 |
| staged_stg_orders | 9,993 |
| staged_stg_returns | 296 |
| fact_rows_inserted | 9,993 |
| fact_rows_updated | 0 |
| fact_rows_unchanged | 0 |
| fact_rows_unresolved_keys | 0 |
| fact_lines_flagged_returned | 800 |
| dim_customer_total_rows | 793 |
| dim_product_total_rows | 1,894 |
| dim_region_total_rows | 632 |
| dim_date_total_rows | 1,826 |
| fact_sales_total_rows | 9,993 |

## Checks

| Source | Check | Category | Severity | Checked | Failed | Status |
|---|---|---|---|---:|---:|---|
| people | INVALID_FORMAT | Data type | ERROR | 4 | 0 | PASS |
| people | NULL_REGIONAL_MANAGER | Null check | ERROR | 4 | 0 | PASS |
| people | NULL_REGION | Null check | ERROR | 4 | 0 | PASS |
| people | DUPLICATE_PRIMARY_KEY | Primary key | ERROR | 4 | 0 | PASS |
| people | ROW_COUNT_RECONCILIATION | Row count reconciliation | ERROR | 4 | 0 | PASS |
| orders | INVALID_FORMAT | Data type | ERROR | 9,994 | 0 | PASS |
| orders | NULL_ROW_ID | Null check | ERROR | 9,994 | 0 | PASS |
| orders | NULL_ORDER_ID | Null check | ERROR | 9,994 | 0 | PASS |
| orders | NULL_ORDER_DATE | Null check | ERROR | 9,994 | 0 | PASS |
| orders | NULL_SHIP_DATE | Null check | ERROR | 9,994 | 0 | PASS |
| orders | NULL_CUSTOMER_ID | Null check | ERROR | 9,994 | 0 | PASS |
| orders | NULL_PRODUCT_ID | Null check | ERROR | 9,994 | 0 | PASS |
| orders | NULL_REGION | Null check | ERROR | 9,994 | 0 | PASS |
| orders | NULL_SALES | Null check | ERROR | 9,994 | 0 | PASS |
| orders | NULL_QUANTITY | Null check | ERROR | 9,994 | 0 | PASS |
| orders | NULL_PROFIT | Null check | ERROR | 9,994 | 0 | PASS |
| orders | FUTURE_ORDER_DATE | Invalid date | ERROR | 9,994 | 0 | PASS |
| orders | ORDER_DATE_OUT_OF_RANGE | Invalid date | ERROR | 9,994 | 0 | PASS |
| orders | SHIP_BEFORE_ORDER | Invalid date | ERROR | 9,994 | 0 | PASS |
| orders | NON_POSITIVE_QUANTITY | Negative quantity | ERROR | 9,994 | 0 | PASS |
| orders | NON_POSITIVE_SALES | Invalid financial value | ERROR | 9,994 | 0 | PASS |
| orders | INVALID_DISCOUNT | Invalid financial value | ERROR | 9,994 | 0 | PASS |
| orders | PROFIT_EXCEEDS_SALES | Invalid financial value | ERROR | 9,994 | 0 | PASS |
| orders | UNKNOWN_REGION | Referential integrity | ERROR | 9,994 | 0 | PASS |
| orders | PRODUCT_ID_MULTIPLE_NAMES | Consistency | WARNING | 9,994 | 337 | WARN |
| orders | POSTAL_CODE_UNKNOWN | Null check | WARNING | 9,994 | 11 | WARN |
| orders | LOSS_EXCEEDS_SALES | Business rule | WARNING | 9,994 | 349 | WARN |
| orders | DUPLICATE_PRIMARY_KEY | Primary key | ERROR | 9,994 | 0 | PASS |
| orders | DUPLICATE_TRANSACTION | Duplicate transaction | ERROR | 9,994 | 1 | FAIL |
| orders | ROW_COUNT_RECONCILIATION | Row count reconciliation | ERROR | 9,994 | 0 | PASS |
| returns | INVALID_FORMAT | Data type | ERROR | 296 | 0 | PASS |
| returns | NULL_ORDER_ID | Null check | ERROR | 296 | 0 | PASS |
| returns | NULL_RETURNED | Null check | ERROR | 296 | 0 | PASS |
| returns | ORPHAN_RETURN | Referential integrity | ERROR | 296 | 0 | PASS |
| returns | DUPLICATE_PRIMARY_KEY | Primary key | ERROR | 296 | 0 | PASS |
| returns | ROW_COUNT_RECONCILIATION | Row count reconciliation | ERROR | 800 | 0 | PASS |
| warehouse | FACT_DIMENSION_KEY_RESOLUTION | Referential integrity | ERROR | 9,993 | 0 | PASS |
| warehouse | LOAD_ROW_RECONCILIATION | Row count reconciliation | ERROR | 9,993 | 0 | PASS |
| warehouse | WAREHOUSE_REFERENTIAL_INTEGRITY | Warehouse integrity | ERROR | 9,993 | 0 | PASS |
| warehouse | WAREHOUSE_PRIMARY_KEY_UNIQUENESS | Warehouse integrity | ERROR | 9,993 | 0 | PASS |
| warehouse | WAREHOUSE_DUPLICATE_TRANSACTIONS | Warehouse integrity | ERROR | 9,993 | 0 | PASS |

### people: transformation statistics

- input_rows: 4
- exact_duplicates_removed: 0
- output_rows: 4

### orders: rejection / warning reasons

- REJECTED `DUPLICATE_TRANSACTION`: 1
- WARNING `LOSS_EXCEEDS_SALES`: 349
- WARNING `PRODUCT_ID_MULTIPLE_NAMES`: 337
- WARNING `POSTAL_CODE_UNKNOWN`: 11

### orders: transformation statistics

- input_rows: 9,994
- exact_duplicates_removed: 0
- postal_code_imputed: 0
- postal_code_unknown: 11
- discount_defaulted_to_zero: 0
- output_rows: 9,994
- rows_with_parse_errors: 0

### returns: transformation statistics

- input_rows: 800
- collapsed_to_order_level: 504
- output_rows: 296
