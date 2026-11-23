# Power BI Guide

> **Status:** Power BI Desktop is a Windows application and was not available in the Linux
> environment where this project was built, so **no `.pbix` file is included**. This guide gives
> the exact manual steps to build the report on top of the warehouse. Once you have built it, save
> it as a template (`File > Export > Power BI template`, `.pbit`) and commit that instead of the
> `.pbix` (which contains data and is git-ignored).

## 1. Prerequisites

1. Power BI Desktop (free, Microsoft Store or microsoft.com/power-bi).
2. **MySQL Connector/NET** - Power BI's built-in *MySQL database* connector needs it installed.
   Download it from dev.mysql.com/downloads/connector/net/, install, and restart Power BI.
   (Alternative: MySQL Connector/ODBC + Power BI's *ODBC* connector.)
3. The warehouse loaded: `python run_pipeline.py`.
4. A **read-only** MySQL account for reporting (never use the ETL account in Power BI). Run as a
   MySQL admin, choosing your own password:

```sql
CREATE USER 'powerbi_reader'@'localhost' IDENTIFIED BY '<choose-a-strong-password>';
GRANT SELECT ON retail_dw.* TO 'powerbi_reader'@'localhost';
```

## 2. Connect

1. `Home > Get data > More... > Database > MySQL database > Connect`.
2. Server: `localhost:3306` (or `127.0.0.1:3306`). Database: `retail_dw`.
3. Credentials: choose **Database**, enter `powerbi_reader` and its password. Power BI stores them
   in its own credential store, not in the report.
4. If prompted about encryption on a local server, select *OK* to connect without encryption
   (local development only).
5. In the Navigator tick:
   * `fact_sales`, `dim_customer`, `dim_product`, `dim_region`, `dim_date`
   * `vw_pipeline_run_history`, `vw_dq_check_results`, `vw_rejection_summary`
6. Click **Transform Data** (not Load) and apply section 3.

**Storage mode:** use **Import**. The dataset is ~10k fact rows, so Import gives the fastest visuals;
refresh after each pipeline run (`Home > Refresh`). DirectQuery is only worth it for very large or
near-real-time data.

## 3. Power Query preparation

| Table | Steps |
|---|---|
| fact_sales | Remove `row_hash`, `business_hash`, `created_at`, `updated_at`. Set `sales`, `profit`, `unit_price` to *Fixed decimal number*, `discount` to *Percentage*, `is_returned` to *True/False*. |
| dim_customer / dim_product / dim_region | Remove `etl_run_id`, `created_at`, `updated_at`. |
| dim_date | Set `full_date` to *Date*. |
| vw_* | Set `start_ts`/`end_ts`/`run_start_ts` to *Date/Time*; `rejection_rate_pct` to *Decimal number*. |

Rename the queries to friendly names if you like (`Sales`, `Customer`, `Product`, `Location`, `Date`,
`Pipeline Runs`, `DQ Checks`, `Rejections`). The DAX below uses the original table names.

`Close & Apply`.

## 4. Model

In **Model view**:

| From (many) | To (one) | Cardinality | Active | Cross-filter |
|---|---|---|---|---|
| fact_sales[order_date_key] | dim_date[date_key] | *:1 | **Yes** | Single |
| fact_sales[ship_date_key] | dim_date[date_key] | *:1 | No (inactive) | Single |
| fact_sales[customer_key] | dim_customer[customer_key] | *:1 | Yes | Single |
| fact_sales[product_key] | dim_product[product_key] | *:1 | Yes | Single |
| fact_sales[region_key] | dim_region[region_key] | *:1 | Yes | Single |
| vw_dq_check_results[run_id] | vw_pipeline_run_history[run_id] | *:1 | Yes | Single |
| vw_rejection_summary[run_id] | vw_pipeline_run_history[run_id] | *:1 | Yes | Single |

Then:
1. Select `dim_date` > *Table tools* > **Mark as date table** > column `full_date`.
2. Sort `dim_date[month_name]` by `month_number` and `month_short` by `month_number`
   (*Column tools > Sort by column*); sort `day_name` by `day_of_week`.
3. Hide all `*_key` columns and `source_row_id` from report view.
4. Set data categories on `dim_region`: `country` = Country, `state` = State or Province,
   `city` = City, `postal_code` = Postal code (enables the map visual).
5. Create a hierarchy in `dim_date`: `calendar_year > quarter_name > month_name > full_date`; and
   in `dim_product`: `category > sub_category > product_name`; in `dim_region`:
   `region > state > city`.
6. Create an empty table **_Measures** (`Enter data`, one dummy column, then hide it) and put all
   measures in it.

## 5. DAX measures

### Core sales
```DAX
Total Revenue = SUM ( fact_sales[sales] )

Total Profit = SUM ( fact_sales[profit] )

Profit Margin % = DIVIDE ( [Total Profit], [Total Revenue] )

Total Orders = DISTINCTCOUNT ( fact_sales[order_id] )

Total Customers = DISTINCTCOUNT ( fact_sales[customer_key] )

Units Sold = SUM ( fact_sales[quantity] )

Average Order Value = DIVIDE ( [Total Revenue], [Total Orders] )

Average Discount % = AVERAGE ( fact_sales[discount] )

Average Ship Days = AVERAGE ( fact_sales[ship_days] )

Loss-Making Lines = CALCULATE ( COUNTROWS ( fact_sales ), fact_sales[profit] < 0 )
```

### Time intelligence (requires dim_date marked as date table)
```DAX
Revenue PY = CALCULATE ( [Total Revenue], SAMEPERIODLASTYEAR ( dim_date[full_date] ) )

Revenue YoY % = DIVIDE ( [Total Revenue] - [Revenue PY], [Revenue PY] )

Profit PY = CALCULATE ( [Total Profit], SAMEPERIODLASTYEAR ( dim_date[full_date] ) )

Profit YoY % = DIVIDE ( [Total Profit] - [Profit PY], [Profit PY] )

Revenue YTD = TOTALYTD ( [Total Revenue], dim_date[full_date] )

Revenue PM = CALCULATE ( [Total Revenue], DATEADD ( dim_date[full_date], -1, MONTH ) )

Revenue MoM % = DIVIDE ( [Total Revenue] - [Revenue PM], [Revenue PM] )

-- Trailing 3 months of revenue / 3 (use on a monthly axis)
Revenue 3M Moving Avg =
DIVIDE (
    CALCULATE (
        [Total Revenue],
        DATESINPERIOD ( dim_date[full_date], MAX ( dim_date[full_date] ), -3, MONTH )
    ),
    3
)

Revenue by Ship Date =
CALCULATE (
    [Total Revenue],
    USERELATIONSHIP ( fact_sales[ship_date_key], dim_date[date_key] )
)
```

> `Revenue 3M Moving Avg` divides by 3 even for the first two months of the data, so ignore
> it for Jan-Feb 2015 (the SQL version in `02_monthly_sales_trend.sql` averages the months
> available instead).

### Customers and returns
```DAX
Repeat Customers =
COUNTROWS (
    FILTER (
        VALUES ( fact_sales[customer_key] ),
        CALCULATE ( DISTINCTCOUNT ( fact_sales[order_id] ) ) > 1
    )
)

Repeat Customer Rate % = DIVIDE ( [Repeat Customers], [Total Customers] )

Revenue per Customer = DIVIDE ( [Total Revenue], [Total Customers] )

Returned Orders = CALCULATE ( [Total Orders], fact_sales[is_returned] = TRUE () )

Return Rate % = DIVIDE ( [Returned Orders], [Total Orders] )

Returned Revenue = CALCULATE ( [Total Revenue], fact_sales[is_returned] = TRUE () )
```

### Ranking
```DAX
Product Revenue Rank =
IF (
    ISINSCOPE ( dim_product[product_name] ),
    RANKX ( ALLSELECTED ( dim_product[product_name] ), [Total Revenue], , DESC, DENSE )
)

Region Revenue Share % =
DIVIDE ( [Total Revenue], CALCULATE ( [Total Revenue], ALLSELECTED ( dim_region ) ) )
```

### Pipeline monitoring
```DAX
Latest Run ID = MAX ( vw_pipeline_run_history[run_id] )

Last Run Status =
VAR _last = [Latest Run ID]
RETURN CALCULATE ( MAX ( vw_pipeline_run_history[status] ),
                   vw_pipeline_run_history[run_id] = _last )

Last Run Time =
VAR _last = [Latest Run ID]
RETURN CALCULATE ( MAX ( vw_pipeline_run_history[end_ts] ),
                   vw_pipeline_run_history[run_id] = _last )

Total Runs = COUNTROWS ( vw_pipeline_run_history )

Failed Runs = CALCULATE ( [Total Runs], vw_pipeline_run_history[status] = "FAILED" )

Run Success Rate % = DIVIDE ( [Total Runs] - [Failed Runs], [Total Runs] )

Records Extracted = SUM ( vw_pipeline_run_history[records_extracted] )

Records Rejected = SUM ( vw_pipeline_run_history[records_rejected] )

Rejection Rate % = DIVIDE ( [Records Rejected], [Records Extracted] )

Records Loaded = SUM ( vw_pipeline_run_history[records_loaded] )

Failed Checks = CALCULATE ( COUNTROWS ( vw_dq_check_results ), vw_dq_check_results[check_status] = "FAIL" )

Warning Checks = CALCULATE ( COUNTROWS ( vw_dq_check_results ), vw_dq_check_results[check_status] = "WARN" )

DQ Pass Rate % =
DIVIDE (
    CALCULATE ( COUNTROWS ( vw_dq_check_results ), vw_dq_check_results[check_status] = "PASS" ),
    COUNTROWS ( vw_dq_check_results )
)

Avg Run Duration (s) = AVERAGE ( vw_pipeline_run_history[duration_seconds] )
```

Formats: currency for revenue/profit/AOV measures (0 decimals on cards), percentage with 1 decimal
for every `%` measure, whole number for counts.

## 6. Report pages

Use one consistent layout: title + last refresh at the top, a row of KPI cards, two to three main
visuals, slicer panel on the left. Sync the common slicers (Year, Region, Segment, Category) across
the five business pages (*View > Sync slicers*).

### Page 1 - Executive Overview
* **KPI cards:** Total Revenue, Total Profit, Profit Margin %, Total Orders, Average Order Value,
  Revenue YoY %, Return Rate %.
* Line chart: Total Revenue and Total Profit by `year_month_label`.
* Clustered bar: Total Revenue by `region`.
* Donut: Total Revenue by `category`.
* **Slicers:** `calendar_year`, `region`, `segment`.

### Page 2 - Sales Performance
* Line + column combo: Total Revenue (columns) and Revenue YoY % (line) by month.
* Line chart: Revenue YTD by month with `calendar_year` as legend (year-over-year comparison).
* Matrix: rows `calendar_year > quarter_name > month_name`; values Revenue, Revenue PY,
  Revenue YoY %, Profit Margin %. Conditional formatting (icons) on Revenue YoY %.
* Column chart: Total Revenue by `ship_mode`; card: Average Ship Days.
* **Slicers:** date range (`full_date`, between), `ship_mode`, `segment`.

### Page 3 - Product Analysis
* Table: Top 10 products (`product_name`, Revenue, Profit, Profit Margin %, Units Sold) with a
  *Top N* visual-level filter on `product_name` by Total Revenue = 10.
* Bar chart: Total Profit by `sub_category`, sorted ascending (loss makers - Tables, Bookcases,
  Supplies - stand out in red via conditional formatting: Total Profit < 0).
* Scatter: Average Discount % (x) vs Profit Margin % (y), details `sub_category`, size Revenue -
  shows the discount/margin relationship found in `11_discount_impact.sql`.
* Decomposition tree: Total Profit by category > sub_category > product_name.
* **Slicers:** `category`, `sub_category`, `calendar_year`.

### Page 4 - Customer Analysis
* KPI cards: Total Customers, Repeat Customers, Repeat Customer Rate %, Revenue per Customer.
* Donut: Total Revenue by `segment`.
* Table: top 15 customers by revenue (`customer_name`, `segment`, Orders, Revenue, Profit).
* Column chart: Total Customers by `calendar_year` (active customers per year).
* Optional: import `docs/sample_outputs/analytics/06_customer_segmentation_rfm.csv` or, better,
  create a view from `sql/analytics/06_customer_segmentation_rfm.sql` and chart customers and
  revenue by RFM segment.
* **Slicers:** `segment`, `region`, `calendar_year`.

### Page 5 - Regional Analysis
* Filled map: Total Revenue by `state` (Location data category) with tooltip Profit Margin %.
* Matrix: `region > state > city`, Revenue, Profit, Profit Margin %, Region Revenue Share %, with
  data bars.
* Clustered bar: Profit Margin % by `region` (Central is the weakest, ~7.9% vs ~14.9% West).
* Card / table: `regional_manager` with Revenue for the selected region.
* **Slicers:** `region`, `calendar_year`, `category`.

### Page 6 - Data Quality & Pipeline Monitoring
* KPI cards: Last Run Status, Last Run Time, Run Success Rate %, Rejection Rate %, DQ Pass Rate %.
  Conditional colour on Last Run Status (green SUCCESS, amber SUCCESS_WITH_WARNINGS, red FAILED).
* Table: `vw_pipeline_run_history` - run_id, start_ts, status, records_extracted,
  records_loaded, records_updated, records_unchanged, records_rejected, duration_seconds.
* Clustered column: records_loaded vs records_rejected by `run_id`.
* Matrix: `vw_dq_check_results` - rows `source_name > check_name`, columns `check_status`, values
  sum of `records_failed`; filter to the latest run with a `run_id` slicer.
* Bar: `vw_rejection_summary` rejected_records by `rejection_reasons`.
* **Slicers:** `run_id`, `source_name`, `severity`.

## 7. Refresh workflow

1. `python run_pipeline.py` (loads new files; safe to run repeatedly).
2. In Power BI: `Home > Refresh`.
3. Page 6 immediately shows the new run, its checks and any rejections.

For scheduled refresh in the Power BI service you would need the on-premises data gateway
pointing at the MySQL server; that is out of scope for this local project.

## 8. Validating the report

After building, compare the cards with the SQL library to verify the model:

| Power BI measure (no filters) | SQL source | Value (real data, run 1) |
|---|---|---|
| Total Revenue | `01_kpi_overview.sql` | 2,296,919.49 |
| Total Profit | `01_kpi_overview.sql` | 286,409.08 |
| Profit Margin % | `01_kpi_overview.sql` | 12.47% |
| Total Orders | `01_kpi_overview.sql` | 5,009 |
| Total Customers | `01_kpi_overview.sql` | 793 |
| Average Order Value | `01_kpi_overview.sql` | 458.56 |
| Return Rate % | `01_kpi_overview.sql` | 5.91% |
| Revenue YoY % (2018) | `03_year_over_year_growth.sql` | 20.36% |
