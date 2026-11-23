# Data quality checks

## How it works

Bad data gets caught at three points:

1. **Reading the file:** lines with the wrong number of fields (or broken quotes) are set aside as
   `MALFORMED_RECORD`, with their line number.
2. **Cleaning:** rows that are identical in every field, including Row ID, are dropped as
   `EXACT_DUPLICATE_RECORD`. Values that can't be converted to a number or date are noted, so
   validation can reject them.
3. **Validation:** the rules in `src/validation/rules.py`. An `ERROR` rule rejects the row. A
   `WARNING` rule keeps it but counts and flags it. A row can fail more than one rule, and all the
   reasons are kept (for example `NULL_CUSTOMER_ID; NON_POSITIVE_QUANTITY`).

After that, the counts have to add up for each file:
`rows read = malformed + dropped duplicates + rejected + valid`.
After the load: `valid order rows = inserted + updated + unchanged`.

Finally, a few checks run against the warehouse itself: no fact rows pointing at missing dimension
rows, no duplicate source keys, and no duplicate transactions.

Each run produces:
- `data/rejected/run_NNNNNN_<source>_rejected.csv`, with the original values, the reasons, and the
  source file and line
- `reports/run_NNNNNN_dq_report.md` (and `.json`), listing every check with its counts
- rows in `etl_data_quality_results` and `etl_rejected_records` for Power BI

## Rules

### Orders

| Rule | Type | Fails when |
|---|---|---|
| MALFORMED_RECORD | reject | wrong number of fields on the line |
| EXACT_DUPLICATE_RECORD | reject | exact copy of an earlier line |
| INVALID_FORMAT | error | a number or date couldn't be parsed (e.g. `12,34x`, `31/31/2019`) |
| NULL_<column> | error | a required field is empty (row_id, order_id, order_date, ship_date, customer_id, product_id, region, sales, quantity, profit) |
| FUTURE_ORDER_DATE | error | order date is after today |
| ORDER_DATE_OUT_OF_RANGE | error | order date before 2000 |
| SHIP_BEFORE_ORDER | error | shipped before it was ordered |
| NON_POSITIVE_QUANTITY | error | quantity is 0 or negative |
| NON_POSITIVE_SALES | error | sales is 0 or negative |
| INVALID_DISCOUNT | error | discount below 0 or 100% and above |
| PROFIT_EXCEEDS_SALES | error | profit is bigger than the sale |
| UNKNOWN_REGION | error | region isn't one of the regions in the people file |
| DUPLICATE_PRIMARY_KEY | error | same (order_id, row_id) twice in the file; the first is kept |
| DUPLICATE_TRANSACTION | error | same transaction under a different row id; the first is kept |
| DUPLICATE_TRANSACTION_IN_WAREHOUSE | error | same transaction already loaded under a different key |
| PRODUCT_ID_MULTIPLE_NAMES | warning | a product ID is used for more than one product name |
| POSTAL_CODE_UNKNOWN | warning | no postal code and nothing to fill it from |
| LOSS_EXCEEDS_SALES | warning | the loss is bigger than the sale (worth a look at pricing) |

### Returns

Returned flag not yes/no (`INVALID_FORMAT`), missing order ID or flag, a return for an order that
doesn't exist in the file or the warehouse (`ORPHAN_RETURN`), and the same order returned twice.
The file has one row per returned *line*, so multiple rows for the same order are just collapsed
into one. That's expected, not an error.

### People

Missing name or region, or a region assigned to two managers.

### After loading

`FACT_DIMENSION_KEY_RESOLUTION`, `LOAD_ROW_RECONCILIATION`, `WAREHOUSE_REFERENTIAL_INTEGRITY`,
`WAREHOUSE_PRIMARY_KEY_UNIQUENESS`, `WAREHOUSE_DUPLICATE_TRANSACTIONS`.

## Cleaning that happens before the checks

- Extra spaces are trimmed; empty strings count as missing.
- Casing is made consistent (`south` becomes `South`, `CONSUMER` becomes `Consumer`); IDs are
  upper-cased.
- Dates are accepted as `11/8/2017`, `2017-11-08`, `11-08-2017`, `2017/11/08`, `08 Nov 2017` or
  `08-Nov-2017`.
- `$` signs and thousands separators are stripped before converting numbers.
- ZIP codes that lost their leading zero get it back (`5401` becomes `05401`).
- A missing postal code is filled from another row for the same city and state if there is one,
  otherwise it's set to `UNKNOWN`.
- A missing discount is treated as 0.
- Missing text fields like ship mode become `Unknown`. Missing IDs and amounts are left empty on
  purpose so they get rejected.

## What happened with the real data

From the first full load (the report is in `docs/sample_outputs/run_000001_dq_report.md`):

- 10,798 rows read across the three files, no malformed lines.
- 1 order row rejected: Row ID 3407 is the same as Row ID 3406 (order US-2015-150119) apart from the
  row id. It's in `docs/sample_outputs/run_000001_orders_rejected.csv`.
- Warnings: 337 rows with a shared product ID, 11 rows without a postal code (Burlington, VT) and
  349 rows where the loss was bigger than the sale.
- The 800 return rows collapsed down to 296 returned orders, with no orphans.
- Everything else passed, including all the count reconciliations and warehouse checks.

## Testing the rules with fake data

Since the real file has so few problems, `scripts/generate_demo_increment.py` makes a small fake
batch (fixed random seed) with one bad row for each rule. It writes to `data/demo_increment/` so
the real files stay as they are. Loading it on top of the real data gave:

- 200 new rows inserted
- 1 existing row updated (I changed its quantity, and the hash picked it up)
- 1 re-sent row left unchanged
- 1 broken CSV line caught when reading
- 1 exact duplicate dropped
- 11 rows rejected (the 10 planted problems plus one duplicate transaction)
- 1 orphan return rejected

This adds fake January 2019 rows to the warehouse. Run
`python scripts/setup_database.py --reset --yes` and then the pipeline again to go back to just the
real data.
