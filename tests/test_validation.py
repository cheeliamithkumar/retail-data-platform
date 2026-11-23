import pandas as pd
import pytest

from src.config import ORDERS_SPEC
from src.ingestion import CSVIngestor
from src.transformation import OrdersTransformer
from src.validation import (DataQualityReport, DataValidator, build_order_rules,
                            build_people_rules, build_return_rules)
from tests.conftest import ORDER_HEADER, TODAY, order_row, sample_orders, write_csv

REGIONS = {"West", "East", "Central", "South"}


def transformed(tmp_path, rows):
    path = write_csv(tmp_path / "orders.csv", ORDER_HEADER, rows)
    return OrdersTransformer().transform(CSVIngestor(ORDERS_SPEC).ingest(path).data).data


def validate(tmp_path, rows, **kwargs):
    df = transformed(tmp_path, rows)
    rules = build_order_rules(today=TODAY, valid_regions=REGIONS, **kwargs)
    return DataValidator("orders", rules).validate(df)


def reasons_by_row(result):
    return dict(zip(result.rejected["row_id"].astype(int), result.rejected["rejection_reasons"]))


def test_clean_batch_passes_every_error_check(tmp_path):
    result = validate(tmp_path, sample_orders())
    assert len(result.valid) == 6 and result.rejected.empty
    assert all(c.status in ("PASS", "WARN") for c in result.checks)


@pytest.mark.parametrize("overrides, expected", [
    ({"Quantity": "-1"}, "NON_POSITIVE_QUANTITY"),
    ({"Quantity": "0"}, "NON_POSITIVE_QUANTITY"),
    ({"Sales": "-5"}, "NON_POSITIVE_SALES"),
    ({"Discount": "1.2"}, "INVALID_DISCOUNT"),
    ({"Discount": "-0.1"}, "INVALID_DISCOUNT"),
    ({"Profit": "999999"}, "PROFIT_EXCEEDS_SALES"),
    ({"Order Date": "1/1/2099", "Ship Date": "1/5/2099"}, "FUTURE_ORDER_DATE"),
    ({"Order Date": "1/1/1990", "Ship Date": "1/5/1990"}, "ORDER_DATE_OUT_OF_RANGE"),
    ({"Ship Date": "3/1/2018"}, "SHIP_BEFORE_ORDER"),
    ({"Order Date": "02/30/2018"}, "INVALID_FORMAT"),
    ({"Sales": "twelve"}, "INVALID_FORMAT"),
    ({"Customer ID": ""}, "NULL_CUSTOMER_ID"),
    ({"Order ID": ""}, "NULL_ORDER_ID"),
    ({"Product ID": "  "}, "NULL_PRODUCT_ID"),
    ({"Region": "Atlantis"}, "UNKNOWN_REGION"),
])
def test_row_level_rules_reject_bad_records(tmp_path, overrides, expected):
    result = validate(tmp_path, sample_orders() + [order_row(99, **overrides)])
    assert len(result.valid) == 6
    assert expected in reasons_by_row(result)[99]


def test_null_and_format_errors_are_not_double_reported(tmp_path):
    result = validate(tmp_path, [order_row(1, Sales="abc")])
    assert reasons_by_row(result)[1] == "INVALID_FORMAT"


def test_multiple_reasons_are_combined(tmp_path):
    result = validate(tmp_path, [order_row(1, Quantity="-2", **{"Customer ID": ""})])
    assert set(reasons_by_row(result)[1].split("; ")) == {"NULL_CUSTOMER_ID", "NON_POSITIVE_QUANTITY"}


def test_duplicate_primary_key_keeps_first(tmp_path):
    rows = sample_orders() + [order_row(1, Sales="300", Profit="10")]  # same (order_id,row_id)
    result = validate(tmp_path, rows)
    assert len(result.valid) == 6
    assert list(reasons_by_row(result).values()) == ["DUPLICATE_PRIMARY_KEY"]
    assert result.valid.loc[result.valid["row_id"] == 1, "sales"].iloc[0] == 261.96


def test_duplicate_transaction_with_different_row_id(tmp_path):
    rows = sample_orders() + [dict(sample_orders()[0], **{"Row ID": "50"})]
    result = validate(tmp_path, rows)
    assert reasons_by_row(result) == {50: "DUPLICATE_TRANSACTION"}


def test_uniqueness_is_checked_on_survivors_only(tmp_path):
    """A bad first occurrence must not cause a good duplicate to be rejected."""
    bad_first = order_row(1, Quantity="-1")
    good_second = order_row(1)
    result = validate(tmp_path, [bad_first, good_second])
    assert len(result.valid) == 1 and result.valid["quantity"].iloc[0] == 2
    assert list(reasons_by_row(result).values()) == ["NON_POSITIVE_QUANTITY"]


def test_cross_load_duplicate_transaction(tmp_path):
    df = transformed(tmp_path, sample_orders())
    existing = pd.DataFrame({"order_id": [df["order_id"].iloc[0]], "row_id": [777],
                             "business_hash": [df["business_hash"].iloc[0]]})
    rules = build_order_rules(today=TODAY, valid_regions=REGIONS, existing_transactions=existing)
    result = DataValidator("orders", rules).validate(df)
    assert reasons_by_row(result) == {1: "DUPLICATE_TRANSACTION_IN_WAREHOUSE"}


def test_same_key_in_warehouse_is_not_a_duplicate(tmp_path):
    """Re-sending an already-loaded line is an update/no-op, not a duplicate."""
    df = transformed(tmp_path, sample_orders())
    existing = df[["order_id", "row_id", "business_hash"]].astype({"row_id": "int64"})
    rules = build_order_rules(today=TODAY, valid_regions=REGIONS, existing_transactions=existing)
    assert DataValidator("orders", rules).validate(df).rejected.empty


def test_warnings_flag_but_do_not_reject(tmp_path):
    rows = sample_orders() + [
        order_row(7, **{"Product Name": "Different name, same id"}),
        order_row(8, **{"Postal Code": "", "City": "Nowhere"}),
        order_row(9, Sales="10", Profit="-25"),
    ]
    result = validate(tmp_path, rows)
    assert result.rejected.empty and len(result.valid) == 9
    flagged = " ".join(result.warnings)
    for name in ("PRODUCT_ID_MULTIPLE_NAMES", "POSTAL_CODE_UNKNOWN", "LOSS_EXCEEDS_SALES"):
        assert name in flagged
    statuses = {c.check_name: c.status for c in result.checks}
    assert statuses["POSTAL_CODE_UNKNOWN"] == "WARN"


def test_return_rules_orphan_and_duplicates():
    df = pd.DataFrame({"order_id": ["A", "B", "Z", None], "returned": [True, True, True, True],
                       "_parse_errors": ["", "", "", ""]})
    result = DataValidator("returns", build_return_rules({"A", "B"})).validate(df)
    assert result.valid["order_id"].tolist() == ["A", "B"]
    assert sorted(result.reasons.tolist()) == ["NULL_ORDER_ID", "ORPHAN_RETURN"]


def test_people_rules_region_unique():
    df = pd.DataFrame({"regional_manager": ["Ann", "Bob"], "region": ["West", "West"],
                       "_parse_errors": ["", ""]})
    result = DataValidator("people", build_people_rules()).validate(df)
    assert len(result.valid) == 1 and result.reasons.tolist() == ["DUPLICATE_PRIMARY_KEY"]


def test_report_outputs(tmp_path):
    from datetime import datetime
    result = validate(tmp_path, sample_orders() + [order_row(99, Quantity="-1")])
    report = DataQualityReport(7, datetime.now())
    report.add_checks(result.checks)
    src = report.source("orders")
    src.rejection_breakdown = report.breakdown(result.reasons)
    report.finished_at = datetime.now()
    report.status = "SUCCESS_WITH_WARNINGS"
    json_path, md_path = report.write(tmp_path / "reports")
    assert json_path.name == "run_000007_dq_report.json"
    md = md_path.read_text()
    assert "NON_POSITIVE_QUANTITY" in md and "| FAIL |" in md
    assert report.summary()["checks_failed"] == 1
    assert src.rejection_breakdown == {"NON_POSITIVE_QUANTITY": 1}
