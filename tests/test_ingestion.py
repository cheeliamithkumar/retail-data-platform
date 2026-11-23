import pandas as pd
import pytest

from src.config import ORDERS_SPEC, RETURNS_SPEC
from src.ingestion import CSVIngestor, SchemaValidationError, SourceFileMissingError
from tests.conftest import ORDER_HEADER, order_row, sample_orders, write_csv


def test_reads_valid_file_with_lineage_metadata(tmp_path):
    path = write_csv(tmp_path / "orders.csv", ORDER_HEADER, sample_orders())
    result = CSVIngestor(ORDERS_SPEC).ingest(path)

    assert result.rows_read == 6
    assert result.malformed_count == 0
    assert list(result.data["row_id"]) == ["1", "2", "3", "4", "5", "6"]   # kept as text
    assert (result.data["_source_file"] == "orders.csv").all()
    assert list(result.data["_source_line"]) == [2, 3, 4, 5, 6, 7]
    assert result.data["_ingested_at"].notna().all()
    assert len(result.checksum) == 64
    assert "sales" in result.data.columns and "Sales" not in result.data.columns


def test_missing_file_raises(tmp_path):
    with pytest.raises(SourceFileMissingError):
        CSVIngestor(ORDERS_SPEC).ingest(tmp_path / "nope.csv")


def test_empty_file_raises(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("")
    with pytest.raises(SchemaValidationError, match="empty"):
        CSVIngestor(ORDERS_SPEC).ingest(path)


def test_missing_required_column_raises(tmp_path):
    header = [c for c in ORDER_HEADER if c != "Profit"]
    rows = [{k: v for k, v in order_row(1).items() if k != "Profit"}]
    path = write_csv(tmp_path / "orders.csv", header, rows)
    with pytest.raises(SchemaValidationError, match="Profit"):
        CSVIngestor(ORDERS_SPEC).ingest(path)


def test_header_matching_is_case_and_whitespace_insensitive(tmp_path):
    path = tmp_path / "returns.csv"
    path.write_text("  RETURNED , order   id\nYes,CA-1\n")
    result = CSVIngestor(RETURNS_SPEC).ingest(path)
    assert list(result.data[["returned", "order_id"]].iloc[0]) == ["Yes", "CA-1"]


def test_malformed_records_are_separated_with_line_numbers(tmp_path):
    path = write_csv(tmp_path / "orders.csv", ORDER_HEADER, sample_orders()[:2])
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("99,BROKEN,1/1/2018\n")                       # too few fields
        fh.write(",".join(order_row(7).values()) + ",EXTRA\n")  # too many fields
        fh.write("\n")                                         # blank line ignored
        fh.write(",".join(order_row(8).values()) + "\n")
    result = CSVIngestor(ORDERS_SPEC).ingest(path)
    assert result.rows_read == 3
    assert result.malformed_count == 2
    assert list(result.malformed["_source_line"]) == [4, 5]
    assert result.malformed["rejection_reasons"].str.startswith("MALFORMED_RECORD").all()
    assert result.total_records == 5


def test_quoted_commas_are_not_malformed(tmp_path):
    rows = [order_row(1, **{"Product Name": 'Chairs, "Rounded" Back'})]
    path = write_csv(tmp_path / "orders.csv", ORDER_HEADER, rows)
    result = CSVIngestor(ORDERS_SPEC).ingest(path)
    assert result.malformed_count == 0
    assert result.data.loc[0, "product_name"] == 'Chairs, "Rounded" Back'


def test_extra_columns_are_dropped(tmp_path):
    rows = [dict(order_row(1), Notes="x")]
    path = write_csv(tmp_path / "orders.csv", ORDER_HEADER + ["Notes"], rows)
    result = CSVIngestor(ORDERS_SPEC).ingest(path)
    assert result.extra_columns == ["Notes"]
    assert "Notes" not in result.data.columns


def test_windows_1252_encoding_is_detected(tmp_path):
    rows = [order_row(1, **{"Customer Name": "José Müller"})]
    path = write_csv(tmp_path / "orders.csv", ORDER_HEADER, rows, encoding="cp1252")
    result = CSVIngestor(ORDERS_SPEC).ingest(path)
    assert result.encoding == "cp1252"
    assert result.data.loc[0, "customer_name"] == "José Müller"


def test_chunked_reading_returns_all_rows(tmp_path):
    rows = [order_row(i) for i in range(1, 26)]
    path = write_csv(tmp_path / "orders.csv", ORDER_HEADER, rows)
    result = CSVIngestor(ORDERS_SPEC, chunk_size=4).ingest(path)
    assert result.rows_read == 25
    assert pd.Series(result.data["_source_line"]).is_monotonic_increasing


def test_header_only_file_gives_empty_frame(tmp_path):
    path = write_csv(tmp_path / "orders.csv", ORDER_HEADER, [])
    result = CSVIngestor(ORDERS_SPEC).ingest(path)
    assert result.rows_read == 0
    assert "order_id" in result.data.columns
