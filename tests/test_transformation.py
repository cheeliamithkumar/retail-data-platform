import numpy as np
import pandas as pd

from src.config import ORDERS_SPEC
from src.ingestion import CSVIngestor
from src.transformation import OrdersTransformer, PeopleTransformer, ReturnsTransformer
from src.transformation import cleaners as c
from tests.conftest import ORDER_HEADER, order_row, sample_orders, write_csv


def ingest(tmp_path, rows):
    path = write_csv(tmp_path / "orders.csv", ORDER_HEADER, rows)
    return CSVIngestor(ORDERS_SPEC).ingest(path).data


def test_strip_strings_trims_collapses_and_nulls_empty():
    df = pd.DataFrame({"a": ["  x  y ", "", None, "z"]}, dtype=object)
    out = c.strip_strings(df, ["a"])
    assert out["a"].tolist()[0] == "x y"
    assert out["a"].isna().tolist() == [False, True, True, False]


def test_to_numeric_flags_invalid_values_but_not_missing():
    df = pd.DataFrame({"v": ["1,234.50", "$10", "abc", None]}, dtype=object)
    df[c.PARSE_ERRORS] = ""
    out = c.to_numeric(df, "v")
    assert out["v"].iloc[0] == 1234.5 and out["v"].iloc[1] == 10.0
    assert out[c.PARSE_ERRORS].tolist() == ["", "", "v:invalid_number", ""]


def test_to_numeric_integer_rejects_fractions():
    df = pd.DataFrame({"q": ["3", "2.5"]}, dtype=object)
    out = c.to_numeric(df, "q", integer=True)
    assert out["q"].iloc[0] == 3 and pd.isna(out["q"].iloc[1])
    assert out[c.PARSE_ERRORS].iloc[1] == "q:invalid_number"


def test_parse_dates_accepts_multiple_formats():
    df = pd.DataFrame({"d": ["11/8/2017", "2017-11-08", "08 Nov 2017", "13/45/2017", None]}, dtype=object)
    out = c.parse_dates(df, "d", ["%m/%d/%Y", "%Y-%m-%d", "%d %b %Y"])
    assert out["d"].iloc[:3].tolist() == [pd.Timestamp("2017-11-08")] * 3
    assert pd.isna(out["d"].iloc[3]) and pd.isna(out["d"].iloc[4])
    assert out[c.PARSE_ERRORS].tolist() == ["", "", "", "d:invalid_date", ""]


def test_postal_code_leading_zeros_restored():
    s = pd.Series(["5401", "42420", "5401.0", "SW1A", None], dtype=object)
    assert c.standardise_postal_code(s).tolist()[:4] == ["05401", "42420", "05401", "SW1A"]


def test_remove_exact_duplicates_keeps_first():
    df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
    kept, removed = c.remove_exact_duplicates(df, ["a", "b"])
    assert kept.index.tolist() == [0, 2] and removed.index.tolist() == [1]


def test_fill_from_group_mode():
    df = pd.DataFrame({"city": ["A", "A", "A", "B"], "zip": ["1", "1", None, None]}, dtype=object)
    filled, imputed = c.fill_from_group_mode(df, "zip", ["city"])
    assert filled.tolist()[:3] == ["1", "1", "1"] and pd.isna(filled.iloc[3])
    assert imputed.tolist() == [False, False, True, False]


def test_row_hash_is_stable_and_sensitive():
    df = pd.DataFrame({"a": ["x", "x", "x", "x"], "b": [1.0, 1.0, 1.0001, 1.00001]})
    h = c.row_hash(df, ["a", "b"])
    assert h.iloc[0] == h.iloc[1] and h.iloc[0] != h.iloc[2]
    # Differences below warehouse precision (DECIMAL(12,4)) are not a change
    assert h.iloc[0] == h.iloc[3]
    assert len(h.iloc[0]) == 64


def test_orders_transformation_types_and_derivations(tmp_path):
    out = OrdersTransformer().transform(ingest(tmp_path, sample_orders())).data
    assert str(out["row_id"].dtype) == "Int64" and str(out["quantity"].dtype) == "Int64"
    assert out["sales"].dtype == np.float64
    assert pd.api.types.is_datetime64_any_dtype(out["order_date"])
    # ISO-formatted and US-formatted dates both standardised
    assert out.loc[out["row_id"] == 5, "order_date"].iloc[0] == pd.Timestamp("2016-06-12")
    assert out.loc[out["row_id"] == 1, "ship_days"].iloc[0] == 4
    assert out.loc[out["row_id"] == 1, "unit_price"].iloc[0] == round(261.96 / 2, 4)
    assert out.loc[out["row_id"] == 5, "postal_code"].iloc[0] == "05401"
    assert (out[c.PARSE_ERRORS] == "").all()
    assert out["row_hash"].is_unique


def test_orders_exact_duplicates_removed(tmp_path):
    rows = sample_orders() + [sample_orders()[0]]
    result = OrdersTransformer().transform(ingest(tmp_path, rows))
    assert len(result.data) == 6
    assert result.stats["exact_duplicates_removed"] == 1
    assert result.removed["rejection_reasons"].tolist() == ["EXACT_DUPLICATE_RECORD"]


def test_orders_missing_values_handling(tmp_path):
    rows = sample_orders() + [
        order_row(7, **{"Postal Code": "", "Discount": "", "Ship Mode": "", "City": "Henderson"}),
        order_row(8, **{"Postal Code": "", "City": "Nowhere"}),
    ]
    result = OrdersTransformer().transform(ingest(tmp_path, rows))
    out = result.data.set_index("row_id")
    assert out.loc[7, "postal_code"] == "42420"          # imputed from Henderson, Kentucky
    assert out.loc[8, "postal_code"] == "UNKNOWN"
    assert out.loc[7, "discount"] == 0.0
    assert out.loc[7, "ship_mode"] == "Unknown"
    assert result.stats["postal_code_imputed"] == 1
    assert result.stats["postal_code_unknown"] == 1


def test_orders_normalisation_of_case(tmp_path):
    rows = [order_row(1, **{"Region": "south", "Segment": "CONSUMER", "Customer ID": "cg-12520"})]
    out = OrdersTransformer().transform(ingest(tmp_path, rows)).data
    assert out.loc[0, "region"] == "South" and out.loc[0, "segment"] == "Consumer"
    assert out.loc[0, "customer_id"] == "CG-12520"


def test_orders_invalid_values_recorded_as_parse_errors(tmp_path):
    rows = [order_row(1, Sales="abc"), order_row(2, **{"Order Date": "2018-13-45"})]
    out = OrdersTransformer().transform(ingest(tmp_path, rows)).data
    assert out[c.PARSE_ERRORS].tolist() == ["sales:invalid_number", "order_date:invalid_date"]


def test_returns_collapse_to_order_level():
    df = pd.DataFrame({"returned": ["Yes", "yes", "Yes", "maybe"],
                       "order_id": ["ca-1", "CA-1", "CA-2", "CA-3"]}, dtype=object)
    result = ReturnsTransformer().transform(df)
    assert result.data["order_id"].tolist() == ["CA-1", "CA-2", "CA-3"]
    assert result.stats["collapsed_to_order_level"] == 1
    assert result.data.loc[result.data["order_id"] == "CA-3", c.PARSE_ERRORS].iloc[0] == "returned:invalid_flag"


def test_people_title_case_region():
    df = pd.DataFrame({"regional_manager": [" Anna Andreadi "], "region": ["west"]}, dtype=object)
    out = PeopleTransformer().transform(df).data
    assert out.iloc[0].tolist()[:2] == ["Anna Andreadi", "West"]
