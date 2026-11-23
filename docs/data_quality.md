# Data Quality Framework

## How it works

1. **Ingestion** separates *malformed* lines (wrong number of fields, broken quoting) with their
   line numbers. Reason: `MALFORMED_RECORD`.
2. **Transformation** removes *exact duplicates* (every source field identical, including Row ID)
   and records values that cannot be typed in a `_parse_errors` column.
3. **Validation** applies a declarative rule set (`src/validation/rules.py`):
   * `ERROR` rules reject the row (it is never loaded);
   * `WARNING` rules keep the row but flag and count it.
   A row can fail several rules; all reasons are recorded (`NULL_CUSTOMER_ID; NON_POSITIVE_QUANTITY`).
4. **Reconciliation** proves nothing was lost:
   `extracted = malformed + removed + rejected + valid` per source, and after the load
   `valid order lines = inserted + updated + unchanged`.
5. **Warehouse checks** after the load: orphan foreign keys, duplicate source keys, duplicate
   transactions.

Every run writes:
* `data/rejected/run_NNNNNN_<source>_rejected.csv` - **original raw values** + `rejection_reasons`
  + source file + line number;
* `reports/run_NNNNNN_dq_report.md` and `.json` - every check, counts, breakdowns;
* `etl_data_quality_results` and `etl_rejected_records` rows in MySQL (for Power BI).

## Rule catalogue

### Orders

| Rule | Severity | Category | Fails when |
|---|---|---|---|
| `MALFORMED_RECORD` | reject | Structure | line has the wrong number of fields (ingestion) |
| `EXACT_DUPLICATE_RECORD` | reject | Duplicate | identical to an earlier line in every field (transformation) |
| `INVALID_FORMAT` | ERROR | Data type | number/date could not be parsed (e.g. `12,34x`, `31/31/2019`) |
| `NULL_<COLUMN>` | ERROR | Null check | mandatory column empty: row_id, order_id, order_date, ship_date, customer_id, product_id, region, sales, quantity, profit |
| `FUTURE_ORDER_DATE` | ERROR | Invalid date | order date after today |
| `ORDER_DATE_OUT_OF_RANGE` | ERROR | Invalid date | order date before 2000-01-01 |
| `SHIP_BEFORE_ORDER` | ERROR | Invalid date | ship date earlier than order date |
| `NON_POSITIVE_QUANTITY` | ERROR | Negative quantity | quantity <= 0 |
| `NON_POSITIVE_SALES` | ERROR | Invalid financial value | sales <= 0 |
| `INVALID_DISCOUNT` | ERROR | Invalid financial value | discount < 0 or >= 1 |
| `PROFIT_EXCEEDS_SALES` | ERROR | Invalid financial value | profit > sales (impossible) |
| `UNKNOWN_REGION` | ERROR | Referential integrity | region not in the region/manager reference data |
| `DUPLICATE_PRIMARY_KEY` | ERROR | Primary key | (order_id, row_id) repeated in the batch - first kept |
| `DUPLICATE_TRANSACTION` | ERROR | Duplicate transaction | same business content under a different row id - first kept |
| `DUPLICATE_TRANSACTION_IN_WAREHOUSE` | ERROR | Duplicate transaction | same business content already loaded under another key |
| `PRODUCT_ID_MULTIPLE_NAMES` | WARNING | Consistency | a Product ID is used for more than one product name |
| `POSTAL_CODE_UNKNOWN` | WARNING | Null check | postal code missing and not imputable |
| `LOSS_EXCEEDS_SALES` | WARNING | Business rule | loss larger than the sale value (pricing/discount review) |

### Returns
`INVALID_FORMAT` (Returned flag not yes/no), `NULL_ORDER_ID`, `NULL_RETURNED`,
`ORPHAN_RETURN` (order not in the batch or the warehouse - referential integrity),
`DUPLICATE_PRIMARY_KEY`. Repeated lines for the same order are *collapsed* to one order-level
flag; this is expected and not counted as a rejection.

### People
`NULL_REGIONAL_MANAGER`, `NULL_REGION`, `DUPLICATE_PRIMARY_KEY` (region assigned to two managers).

### Warehouse (post-load)
`FACT_DIMENSION_KEY_RESOLUTION`, `LOAD_ROW_RECONCILIATION`, `WAREHOUSE_REFERENTIAL_INTEGRITY`,
`WAREHOUSE_PRIMARY_KEY_UNIQUENESS`, `WAREHOUSE_DUPLICATE_TRANSACTIONS`.

## Cleaning applied before validation

| Issue | Handling |
|---|---|
| Leading/trailing/multiple spaces | trimmed and collapsed; empty strings -> missing |
| Inconsistent case (`south`, `CONSUMER`) | title-case for region, segment, ship mode, category, sub-category; IDs upper-cased |
| Dates in several formats | `%m/%d/%Y`, `%Y-%m-%d`, `%m-%d-%Y`, `%Y/%m/%d`, `%d %b %Y`, `%d-%b-%Y` -> ISO date |
| Thousands separators / currency symbols | stripped before numeric conversion (`$1,234.50` -> 1234.5) |
| ZIP codes losing leading zeros | restored to 5 digits |
| Missing postal code | imputed from other rows of the same city/state, else `UNKNOWN` (+ warning) |
| Missing discount | 0 (business definition: no discount recorded = no discount) |
| Missing descriptive attribute | `Unknown`; missing keys/measures are left missing so validation rejects them |

## Results on the real Superstore data (run 1)

From `docs/sample_outputs/run_000001_dq_report.md`:

* 10,798 records extracted across 3 files, 0 malformed.
* **1 order line rejected** - `DUPLICATE_TRANSACTION`: Row ID 3407 is an exact copy of Row ID 3406
  (order US-2015-150119) except for the row id. Its raw values are in
  `docs/sample_outputs/run_000001_orders_rejected.csv`.
* **Warnings:** 337 lines use a Product ID shared by different product names; 11 lines
  (Burlington, VT) have no postal code; 349 lines lose more than their sale value.
* 504 return lines collapsed into 296 returned orders; 0 orphan returns.
* All 41 checks other than the four above passed, including every reconciliation and warehouse
  integrity check.

## Demonstrating rejections: the synthetic increment

The real file is quite clean, so `scripts/generate_demo_increment.py` builds a **clearly labelled
synthetic** batch (fixed seed, written to `data/demo_increment/`, real files untouched) with one
defect per rule. Loading it on top of the real data produced:

| Outcome | Count |
|---|---|
| New lines inserted | 200 |
| Existing line updated (corrected quantity, detected by `row_hash`) | 1 |
| Re-sent line unchanged | 1 |
| Malformed line (ingestion) | 1 |
| Exact duplicate removed | 1 |
| Rejected by rules (10 planted defects + 1 duplicate transaction) | 11 |
| Orphan return rejected | 1 |

Note that this adds synthetic January-2019 rows to the warehouse; reset with
`python scripts/setup_database.py --reset --yes` and rerun the pipeline to go back to real data only.
