"""Integration tests against a real MySQL 8 test database (marker: db)."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from src.analytics.runner import list_queries, run_query
from src.loading import WarehouseLoader
from src.pipeline import RetailPipeline
from src.utils.db import split_sql_statements
from tests.conftest import DEFAULT_PEOPLE, TODAY, order_row, sample_orders, write_sources

pytestmark = pytest.mark.db

RETURNS = [{"Returned": "Yes", "Order ID": "US-2017-200003"}]


def pipeline(engine, dirs, **kwargs):
    return RetailPipeline(engine=engine, raw_dir=dirs["raw"], processed_dir=dirs["processed"],
                          rejected_dir=dirs["rejected"], report_dir=dirs["reports"], today=TODAY,
                          triggered_by="pytest", **kwargs)


def scalar(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def test_split_sql_statements_handles_quotes_and_comments():
    sql = "-- c1\nSELECT ';' AS a; /* x; y */ SELECT 2 # z;\n; SELECT 'it''s';"
    assert split_sql_statements(sql) == ["SELECT ';' AS a", "SELECT 2", "SELECT 'it''s'"]


def test_schema_deployment_is_idempotent(db_engine):
    WarehouseLoader(db_engine).ensure_schema()  # second deployment must not fail
    with db_engine.connect() as conn:
        tables = {r[0] for r in conn.exec_driver_sql("SHOW TABLES")}
    expected = {"fact_sales", "dim_customer", "dim_product", "dim_date", "dim_region",
                "stg_orders", "etl_pipeline_runs", "etl_file_registry",
                "etl_data_quality_results", "etl_rejected_records", "vw_sales_enriched"}
    assert expected <= tables


def test_initial_load_populates_star_schema(db_engine, dirs):
    write_sources(dirs["raw"], sample_orders(), returns=RETURNS, people=DEFAULT_PEOPLE)
    outcome = pipeline(db_engine, dirs).run()

    assert outcome.status in ("SUCCESS", "SUCCESS_WITH_WARNINGS"), outcome.report.errors
    assert outcome.totals["records_loaded"] == 6
    assert scalar(db_engine, "SELECT COUNT(*) FROM fact_sales") == 6
    assert scalar(db_engine, "SELECT COUNT(*) FROM dim_customer") == 2
    assert scalar(db_engine, "SELECT COUNT(*) FROM dim_product") == 4
    assert scalar(db_engine, "SELECT COUNT(*) FROM dim_region") == 3
    # Full calendar years 2016-2018 generated in dim_date
    assert scalar(db_engine, "SELECT COUNT(*) FROM dim_date") == 366 + 365 + 365
    assert float(scalar(db_engine, "SELECT SUM(sales) FROM fact_sales")) == pytest.approx(1260.592)
    assert scalar(db_engine, "SELECT SUM(is_returned) FROM fact_sales") == 2  # both lines of the order
    assert scalar(db_engine, "SELECT regional_manager FROM dim_region WHERE region='West'") == "Anna Andreadi"
    assert scalar(db_engine, "SELECT postal_code FROM dim_region WHERE city='Burlington'") == "05401"
    assert scalar(db_engine, "SELECT COUNT(*) FROM vw_sales_enriched") == 6
    checks = {c.check_name: c.status for c in outcome.report.checks if c.source == "warehouse"}
    assert set(checks.values()) == {"PASS"} and "LOAD_ROW_RECONCILIATION" in checks


def test_audit_tables_are_populated(db_engine, dirs):
    write_sources(dirs["raw"], sample_orders() + [order_row(99, Quantity="-4")], people=DEFAULT_PEOPLE)
    outcome = pipeline(db_engine, dirs).run()
    with db_engine.connect() as conn:
        run = conn.execute(text("SELECT * FROM etl_pipeline_runs WHERE run_id=:r"),
                           {"r": outcome.run_id}).mappings().one()
        assert run["status"] == "SUCCESS_WITH_WARNINGS"
        assert run["end_ts"] is not None and run["triggered_by"] == "pytest"
        assert (run["records_extracted"], run["records_rejected"], run["records_loaded"]) == (11, 1, 6)
        assert conn.execute(text("SELECT COUNT(*) FROM etl_file_registry")).scalar_one() == 2
        assert conn.execute(text("SELECT COUNT(*) FROM etl_data_quality_results WHERE run_id=:r"),
                            {"r": outcome.run_id}).scalar_one() == len(outcome.report.checks)
        rej = conn.execute(text("SELECT source_line, rejection_reasons, "
                                "JSON_UNQUOTE(JSON_EXTRACT(raw_record, '$.quantity')) AS q "
                                "FROM etl_rejected_records")).mappings().one()
        assert (rej["source_line"], rej["rejection_reasons"], rej["q"]) == (8, "NON_POSITIVE_QUANTITY", "-4")


def test_rerun_of_same_files_loads_nothing(db_engine, dirs):
    write_sources(dirs["raw"], sample_orders(), people=DEFAULT_PEOPLE)
    pipeline(db_engine, dirs).run()
    second = pipeline(db_engine, dirs).run()
    assert second.status == "NO_NEW_DATA"
    assert second.report.sources["orders"].status == "SKIPPED_ALREADY_LOADED"
    assert scalar(db_engine, "SELECT COUNT(*) FROM fact_sales") == 6


def test_forced_rerun_is_idempotent(db_engine, dirs):
    write_sources(dirs["raw"], sample_orders(), people=DEFAULT_PEOPLE)
    pipeline(db_engine, dirs).run()
    forced = pipeline(db_engine, dirs, force=True).run()
    assert forced.totals["records_loaded"] == 0
    assert forced.totals["records_updated"] == 0
    assert forced.totals["records_unchanged"] == 6
    assert scalar(db_engine, "SELECT COUNT(*) FROM fact_sales") == 6
    assert scalar(db_engine, "SELECT COUNT(*) FROM dim_customer") == 2


def test_incremental_load_inserts_new_and_updates_changed(db_engine, dirs):
    write_sources(dirs["raw"], sample_orders(), people=DEFAULT_PEOPLE)
    first = pipeline(db_engine, dirs).run()

    changed = sample_orders()
    changed[0]["Quantity"], changed[0]["Sales"] = "3", "392.94"          # correction
    for line in (2, 3):                                                 # SCD1 attribute change
        changed[line]["Customer Name"] = "Darrin Van-Huff"
    new = order_row(7, **{"Order ID": "CA-2019-400007", "Order Date": "1/3/2019", "Ship Date": "1/6/2019"})
    write_sources(dirs["raw"], changed + [new])
    second = pipeline(db_engine, dirs).run()

    assert (second.totals["records_loaded"], second.totals["records_updated"],
            second.totals["records_unchanged"]) == (1, 3, 3)
    assert scalar(db_engine, "SELECT COUNT(*) FROM fact_sales") == 7
    assert scalar(db_engine, "SELECT quantity FROM fact_sales WHERE source_row_id=1") == 3
    assert scalar(db_engine, "SELECT etl_run_id FROM fact_sales WHERE source_row_id=1") == second.run_id
    assert scalar(db_engine, "SELECT etl_run_id FROM fact_sales WHERE source_row_id=5") == first.run_id
    assert scalar(db_engine, "SELECT customer_name FROM dim_customer WHERE customer_id='DV-13045'") \
        == "Darrin Van-Huff"
    assert scalar(db_engine, "SELECT COUNT(*) FROM dim_customer") == 2   # updated, not duplicated
    assert scalar(db_engine, "SELECT COUNT(*) FROM dim_date WHERE calendar_year=2019") == 365


def test_duplicate_transaction_across_loads_is_rejected(db_engine, dirs):
    write_sources(dirs["raw"], sample_orders(), people=DEFAULT_PEOPLE)
    pipeline(db_engine, dirs).run()
    resend = dict(sample_orders()[0], **{"Row ID": "500"})   # same transaction, new row id
    write_sources(dirs["raw"], [resend])
    outcome = pipeline(db_engine, dirs).run()
    assert outcome.report.sources["orders"].rejection_breakdown == {"DUPLICATE_TRANSACTION_IN_WAREHOUSE": 1}
    assert scalar(db_engine, "SELECT COUNT(*) FROM fact_sales") == 6


def test_returns_for_already_loaded_orders(db_engine, dirs):
    write_sources(dirs["raw"], sample_orders(), people=DEFAULT_PEOPLE)
    pipeline(db_engine, dirs).run()
    write_sources(dirs["raw"], sample_orders(), returns=[{"Returned": "Yes", "Order ID": "CA-2016-300005"},
                                                         {"Returned": "Yes", "Order ID": "GHOST-1"}])
    outcome = pipeline(db_engine, dirs).run()   # orders skipped (unchanged), returns processed
    assert outcome.report.sources["orders"].status == "SKIPPED_ALREADY_LOADED"
    assert outcome.report.sources["returns"].rejection_breakdown == {"ORPHAN_RETURN": 1}
    assert scalar(db_engine, "SELECT SUM(is_returned) FROM fact_sales") == 2


def test_unique_key_prevents_duplicate_fact_rows(db_engine, dirs):
    write_sources(dirs["raw"], sample_orders(), people=DEFAULT_PEOPLE)
    pipeline(db_engine, dirs).run()
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.exec_driver_sql("""
                INSERT INTO fact_sales (order_id, source_row_id, order_date_key, ship_date_key,
                    customer_key, product_key, region_key, ship_mode, quantity, sales, discount,
                    profit, row_hash, business_hash, etl_run_id)
                SELECT order_id, source_row_id, order_date_key, ship_date_key, customer_key,
                    product_key, region_key, ship_mode, quantity, sales, discount, profit,
                    row_hash, business_hash, etl_run_id
                FROM fact_sales WHERE source_row_id = 1""")


def test_check_constraint_blocks_negative_quantity(db_engine, dirs):
    write_sources(dirs["raw"], sample_orders(), people=DEFAULT_PEOPLE)
    pipeline(db_engine, dirs).run()
    with pytest.raises(OperationalError, match="ck_fact_sales_quantity"):
        with db_engine.begin() as conn:
            conn.exec_driver_sql("UPDATE fact_sales SET quantity = -1 WHERE source_row_id = 1")


def test_failed_load_rolls_back_completely(db_engine, dirs, tmp_path):
    """A failing transformation step must leave the warehouse untouched."""
    broken = tmp_path / "transformations"
    broken.mkdir()
    for p in sorted(WarehouseLoader(db_engine).transform_dir.glob("*.sql")):
        (broken / p.name).write_text(p.read_text())
    (broken / "07_apply_returns.sql").write_text("UPDATE no_such_table SET x = 1;")

    write_sources(dirs["raw"], sample_orders(), people=DEFAULT_PEOPLE)
    pipe = pipeline(db_engine, dirs)
    pipe.loader.transform_dir = broken
    outcome = pipe.run()

    assert outcome.status == "FAILED"
    assert scalar(db_engine, "SELECT COUNT(*) FROM fact_sales") == 0
    assert scalar(db_engine, "SELECT COUNT(*) FROM dim_customer") == 0
    assert scalar(db_engine, "SELECT COUNT(*) FROM etl_file_registry") == 0   # file can be retried
    assert scalar(db_engine, "SELECT status FROM etl_pipeline_runs WHERE run_id=:r",
                  r=outcome.run_id) == "FAILED"
    assert "no_such_table" in scalar(db_engine, "SELECT error_message FROM etl_pipeline_runs")

    pipe.loader.transform_dir = WarehouseLoader(db_engine).transform_dir   # fix and retry
    retry = pipe.run()
    assert retry.totals["records_loaded"] == 6


def test_all_analytics_queries_execute(db_engine, dirs):
    write_sources(dirs["raw"], sample_orders(), returns=RETURNS, people=DEFAULT_PEOPLE)
    pipeline(db_engine, dirs).run()
    queries = list_queries()
    assert len(queries) >= 10
    for path in queries:
        df = run_query(db_engine, path)
        assert not df.empty, path.name
    kpi = run_query(db_engine, [q for q in queries if "kpi" in q.name][0]).iloc[0]
    assert float(kpi["total_revenue"]) == pytest.approx(1260.59)
    assert int(kpi["total_orders"]) == 3
    assert float(kpi["average_order_value"]) == pytest.approx(420.20, abs=0.01)
