"""Pipeline orchestration tests that run without a database (dry-run mode)."""
import pandas as pd

from src.pipeline import RetailPipeline
from tests.conftest import DEFAULT_PEOPLE, TODAY, order_row, sample_orders, write_sources


def run(dirs, **kwargs):
    return RetailPipeline(engine=None, raw_dir=dirs["raw"], processed_dir=dirs["processed"],
                          rejected_dir=dirs["rejected"], report_dir=dirs["reports"], today=TODAY,
                          **kwargs).run()


def test_dry_run_end_to_end_reconciles(dirs):
    orders = sample_orders() + [order_row(98, Quantity="-1"), sample_orders()[0]]
    write_sources(dirs["raw"], orders, returns=[{"Returned": "Yes", "Order ID": "CA-2018-100001"},
                                                {"Returned": "Yes", "Order ID": "NOPE"}],
                  people=DEFAULT_PEOPLE)
    with open(dirs["raw"] / "superstore_orders.csv", "a") as fh:
        fh.write("1,2,3\n")
    outcome = run(dirs)

    assert outcome.status == "SUCCESS_WITH_WARNINGS"
    s = outcome.report.sources["orders"]
    assert (s.records_extracted, s.malformed, s.removed_in_transform, s.rejected, s.valid) == (9, 1, 1, 1, 6)
    recon = [c for c in outcome.report.checks if c.check_name == "ROW_COUNT_RECONCILIATION"]
    assert len(recon) == 3 and all(c.status == "PASS" for c in recon)
    assert outcome.report.sources["returns"].rejection_breakdown == {"ORPHAN_RETURN": 1}
    assert outcome.totals["records_rejected"] == 3 + 1   # orders: malformed+dup+invalid; returns: orphan


def test_rejected_file_keeps_raw_values_and_reasons(dirs):
    write_sources(dirs["raw"], sample_orders() + [order_row(99, Sales="12abc")], people=DEFAULT_PEOPLE)
    outcome = run(dirs)
    rejected_files = list(dirs["rejected"].glob("*_orders_rejected.csv"))
    assert len(rejected_files) == 1
    rej = pd.read_csv(rejected_files[0], dtype=str)
    assert rej.loc[0, "sales"] == "12abc"               # original raw value preserved
    assert rej.loc[0, "rejection_reasons"] == "INVALID_FORMAT"
    assert rej.loc[0, "_source_line"] == "8"
    assert list(dirs["processed"].glob("*_orders_clean.csv"))
    assert outcome.report_paths[0].exists() and outcome.report_paths[1].exists()


def test_missing_required_source_fails_gracefully(dirs):
    outcome = run(dirs)
    assert outcome.status == "FAILED"
    assert any("Required source 'orders' is missing" in e for e in outcome.report.errors)
    assert outcome.report_paths[1].exists()


def test_missing_optional_sources_are_skipped(dirs):
    write_sources(dirs["raw"], sample_orders())
    outcome = run(dirs)
    assert outcome.status in ("SUCCESS", "SUCCESS_WITH_WARNINGS")
    assert outcome.report.sources["returns"].status == "MISSING_OPTIONAL"
    assert outcome.report.sources["people"].status == "MISSING_OPTIONAL"
    assert outcome.report.sources["orders"].valid == 6
    # Without region reference data the region check is skipped, not failed
    assert "UNKNOWN_REGION" not in {c.check_name for c in outcome.report.checks}


def test_schema_error_in_required_source_fails(dirs):
    (dirs["raw"] / "superstore_orders.csv").write_text("a,b,c\n1,2,3\n")
    outcome = run(dirs)
    assert outcome.status == "FAILED"
    assert any("missing required columns" in e for e in outcome.report.errors)
