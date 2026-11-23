# Power BI setup

There's no `.pbix` in the repo yet. I built the project on Linux, and Power BI Desktop only runs on
Windows, so these are the steps for building the report yourself. Once it's built, save it as a
template (File > Export > Power BI template) and commit the `.pbit`. The `.pbix` is git-ignored
because it contains the data.

## What you need

1. Power BI Desktop (free).
2. MySQL Connector/NET. Power BI's MySQL connector won't work without it. Download it from
   dev.mysql.com/downloads/connector/net/, install it, and restart Power BI.
3. The warehouse loaded (`python run_pipeline.py`).
4. A read-only MySQL user for Power BI, so the report can't change anything:

```sql
CREATE USER 'powerbi_reader'@'localhost' IDENTIFIED BY 'your_password';
GRANT SELECT ON retail_dw.* TO 'powerbi_reader'@'localhost';
```

## Connecting

1. Home > Get data > More... > MySQL database.
2. Server `localhost:3306`, database `retail_dw`.
3. Choose Database credentials and sign in as `powerbi_reader`.
4. If it asks about encryption on a local server, just continue without it.
5. Tick these tables:
   - `fact_sales`, `dim_customer`, `dim_product`, `dim_region`, `dim_date`
   - `vw_pipeline_run_history`, `vw_dq_check_results`, `vw_rejection_summary`
6. Click Transform Data rather than Load.

Use Import mode. With about 10k rows it's fast, and you just hit Refresh after each pipeline run.

## Cleaning up in Power Query

- `fact_sales`: remove `row_hash`, `business_hash`, `created_at` and `updated_at`. Make `sales`,
  `profit` and `unit_price` fixed decimal, `discount` a percentage and `is_returned` true/false.
- Dimensions: remove `etl_run_id`, `created_at` and `updated_at`.
- `dim_date`: make `full_date` a Date.
- Views: make the timestamp columns Date/Time.

Then Close & Apply.

## Model

Relationships (all many-to-one, single direction):

- `fact_sales[order_date_key]` -> `dim_date[date_key]` (active)
- `fact_sales[ship_date_key]` -> `dim_date[date_key]` (**inactive**, used with `USERELATIONSHIP`)
- `fact_sales[customer_key]` -> `dim_customer[customer_key]`
- `fact_sales[product_key]` -> `dim_product[product_key]`
- `fact_sales[region_key]` -> `dim_region[region_key]`
- `vw_dq_check_results[run_id]` -> `vw_pipeline_run_history[run_id]`
- `vw_rejection_summary[run_id]` -> `vw_pipeline_run_history[run_id]`

Then:

- Mark `dim_date` as the date table, using `full_date`.
- Sort `month_name` and `month_short` by `month_number`, and `day_name` by `day_of_week`.
- Hide the `*_key` columns and `source_row_id`.
- On `dim_region`, set the data category of `country`, `state`, `city` and `postal_code` so the map
  visual works.
- Add hierarchies: year > quarter > month > date; category > sub-category > product;
  region > state > city.
- Keep all the measures in an empty `_Measures` table.

## DAX measures

Sales:

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

Time comparisons (these need `dim_date` marked as the date table):

```DAX
Revenue PY = CALCULATE ( [Total Revenue], SAMEPERIODLASTYEAR ( dim_date[full_date] ) )
Revenue YoY % = DIVIDE ( [Total Revenue] - [Revenue PY], [Revenue PY] )
Profit PY = CALCULATE ( [Total Profit], SAMEPERIODLASTYEAR ( dim_date[full_date] ) )
Profit YoY % = DIVIDE ( [Total Profit] - [Profit PY], [Profit PY] )
Revenue YTD = TOTALYTD ( [Total Revenue], dim_date[full_date] )
Revenue PM = CALCULATE ( [Total Revenue], DATEADD ( dim_date[full_date], -1, MONTH ) )
Revenue MoM % = DIVIDE ( [Total Revenue] - [Revenue PM], [Revenue PM] )

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

(The 3-month average always divides by 3, so ignore it for Jan and Feb 2015.)

Customers and returns:

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

Ranking:

```DAX
Product Revenue Rank =
IF (
    ISINSCOPE ( dim_product[product_name] ),
    RANKX ( ALLSELECTED ( dim_product[product_name] ), [Total Revenue], , DESC, DENSE )
)

Region Revenue Share % =
DIVIDE ( [Total Revenue], CALCULATE ( [Total Revenue], ALLSELECTED ( dim_region ) ) )
```

Pipeline monitoring:

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

Formatting: currency for the money measures, percentages with one decimal place, and whole numbers
for counts.

## Pages

I'd keep the same layout on every page: title at the top, a row of KPI cards, two or three main
charts, and slicers down the left. Sync the Year, Region, Segment and Category slicers across the
five business pages.

**1. Executive Overview**
- Cards: Revenue, Profit, Margin %, Orders, AOV, Revenue YoY %, Return Rate %
- Line chart of revenue and profit by month
- Bar chart of revenue by region
- Donut of revenue by category
- Slicers: year, region, segment

**2. Sales Performance**
- Columns for revenue with a line for YoY % by month
- Revenue YTD by month, one line per year
- Matrix (year > quarter > month) with Revenue, Revenue PY, YoY % and Margin %
- Revenue by ship mode, and average ship days
- Slicers: date range, ship mode, segment

**3. Product Analysis**
- Top 10 products table (using a Top N filter on revenue)
- Profit by sub-category, sorted lowest first, with negatives in red. Tables, Bookcases and
  Supplies show up straight away.
- Scatter of average discount against margin by sub-category; the higher the discount, the lower
  the margin
- Decomposition tree: profit by category > sub-category > product
- Slicers: category, sub-category, year

**4. Customer Analysis**
- Cards: Customers, Repeat Customers, Repeat Rate %, Revenue per Customer
- Revenue by segment
- Top 15 customers table
- Active customers per year
- Optionally, RFM segments (make a view from `sql/analytics/06_customer_segmentation_rfm.sql`)
- Slicers: segment, region, year

**5. Regional Analysis**
- Filled map of revenue by state, with margin in the tooltip
- Matrix of region > state > city with revenue, profit, margin and share
- Margin by region (Central is the weakest at about 7.9%, West the best at about 14.9%)
- Revenue per regional manager
- Slicers: region, year, category

**6. Data Quality & Pipeline Monitoring**
- Cards: Last Run Status (coloured green / amber / red), Last Run Time, Success Rate %,
  Rejection Rate %, DQ Pass Rate %
- Table of the run history
- Rows loaded vs rejected per run
- Matrix of checks by source with status columns, filtered to one run
- Rejected rows by reason
- Slicers: run_id, source, severity

## Refreshing

Run `python run_pipeline.py`, then hit Refresh in Power BI. The new run shows up on page 6.

## Checking the numbers

With no filters, the cards should match what the SQL gives (real data, first load):

| Measure | Expected |
|---|---|
| Total Revenue | 2,296,919.49 |
| Total Profit | 286,409.08 |
| Profit Margin % | 12.47% |
| Total Orders | 5,009 |
| Total Customers | 793 |
| Average Order Value | 458.56 |
| Return Rate % | 5.91% |
| Revenue YoY % for 2018 | 20.36% |
