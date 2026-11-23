"""Source-specific transformations built from the generic cleaners."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.config import ACCEPTED_DATE_FORMATS
from src.transformation import cleaners as c
from src.utils.logger import get_logger

log = get_logger("transformation")

ORDER_SOURCE_COLUMNS = [
    "row_id", "order_id", "order_date", "ship_date", "ship_mode", "customer_id",
    "customer_name", "segment", "country", "city", "state", "postal_code", "region",
    "product_id", "category", "sub_category", "product_name", "sales", "quantity",
    "discount", "profit",
]
# Business content of a transaction (everything except the source line identifier).
ORDER_BUSINESS_COLUMNS = [col for col in ORDER_SOURCE_COLUMNS if col != "row_id"]
UNKNOWN = "Unknown"
UNKNOWN_POSTAL = "UNKNOWN"


@dataclass
class TransformResult:
    data: pd.DataFrame
    removed: pd.DataFrame  # records removed during transformation, with a reason
    stats: dict = field(default_factory=dict)


def _removed(df: pd.DataFrame, reason: str) -> pd.DataFrame:
    out = df.copy()
    out["rejection_reasons"] = reason
    return out


class OrdersTransformer:
    """Clean, type and enrich order lines."""

    def __init__(self, date_formats=ACCEPTED_DATE_FORMATS):
        self.date_formats = date_formats

    def transform(self, df: pd.DataFrame) -> TransformResult:
        stats: dict = {"input_rows": len(df)}
        out = c.strip_strings(df, ORDER_SOURCE_COLUMNS)
        out[c.PARSE_ERRORS] = ""

        # 1. Exact duplicates (identical in every source field incl. Row ID) are
        #    re-sent records - drop all but the first.
        out, dups = c.remove_exact_duplicates(out, ORDER_SOURCE_COLUMNS)
        stats["exact_duplicates_removed"] = len(dups)

        # 2. Type conversion
        out = c.to_numeric(out, "row_id", integer=True)
        out = c.to_numeric(out, "quantity", integer=True)
        for col in ("sales", "discount", "profit"):
            out = c.to_numeric(out, col)

        # 3. Date standardisation (multiple accepted input formats -> ISO dates)
        for col in ("order_date", "ship_date"):
            out = c.parse_dates(out, col, self.date_formats)

        # 4. Normalise categorical text to a consistent case
        for col in ("ship_mode", "segment", "region", "category", "sub_category"):
            out[col] = c.title_case(out[col])
        out["postal_code"] = c.standardise_postal_code(out["postal_code"])
        out["customer_id"] = out["customer_id"].str.upper()
        out["product_id"] = out["product_id"].str.upper()
        out["order_id"] = out["order_id"].str.upper()

        # 5. Missing-value handling
        #    a) postal code: impute from other rows of the same city/state, else UNKNOWN
        filled, imputed = c.fill_from_group_mode(out, "postal_code", ["country", "state", "city"])
        out["postal_code"] = filled
        still_missing = out["postal_code"].isna()
        out.loc[still_missing, "postal_code"] = UNKNOWN_POSTAL
        stats["postal_code_imputed"] = int(imputed.sum())
        stats["postal_code_unknown"] = int(still_missing.sum())
        #    b) missing discount means "no discount" by business definition
        no_disc = out["discount"].isna() & ~out[c.PARSE_ERRORS].str.contains("discount:")
        out.loc[no_disc, "discount"] = 0.0
        stats["discount_defaulted_to_zero"] = int(no_disc.sum())
        #    c) descriptive attributes default to 'Unknown'; keys/measures are left
        #       missing so the validation layer rejects them.
        for col in ("ship_mode", "segment", "country", "city", "state", "category",
                    "sub_category", "customer_name", "product_name"):
            n = int(out[col].isna().sum())
            if n:
                out[col] = out[col].fillna(UNKNOWN)
                stats[f"{col}_defaulted_unknown"] = n

        # 6. Rounding money to warehouse precision
        for col in ("sales", "profit"):
            out[col] = out[col].round(4)
        out["discount"] = out["discount"].round(4)

        # 7. Derived attributes
        out["ship_days"] = (out["ship_date"] - out["order_date"]).dt.days.astype("Int64")
        with np.errstate(divide="ignore", invalid="ignore"):
            out["unit_price"] = (out["sales"] / out["quantity"].astype("float64")).round(4)
        out["unit_price"] = out["unit_price"].replace([np.inf, -np.inf], np.nan)
        out["row_hash"] = c.row_hash(out, ORDER_SOURCE_COLUMNS)
        out["business_hash"] = c.row_hash(out, ORDER_BUSINESS_COLUMNS)

        stats["output_rows"] = len(out)
        stats["rows_with_parse_errors"] = int((out[c.PARSE_ERRORS] != "").sum())
        log.info("[orders] Transformation stats: %s", stats)
        return TransformResult(out, _removed(dups, "EXACT_DUPLICATE_RECORD"), stats)


class ReturnsTransformer:
    """Returns arrive one line per returned order line; the warehouse needs one flag per order."""

    def transform(self, df: pd.DataFrame) -> TransformResult:
        stats: dict = {"input_rows": len(df)}
        out = c.strip_strings(df, ["returned", "order_id"])
        out["order_id"] = out["order_id"].str.upper()
        out["returned"] = out["returned"].str.lower().map(
            {"yes": True, "y": True, "true": True, "1": True,
             "no": False, "n": False, "false": False, "0": False})
        out[c.PARSE_ERRORS] = ""
        c.add_parse_error(out, df["returned"].notna() & out["returned"].isna(), "returned:invalid_flag")
        # Collapse to order level; duplicates here are expected (one per line), not errors.
        out, collapsed = c.remove_exact_duplicates(out, ["order_id", "returned"])
        stats["collapsed_to_order_level"] = len(collapsed)
        stats["output_rows"] = len(out)
        log.info("[returns] Transformation stats: %s", stats)
        return TransformResult(out, _removed(collapsed, "COLLAPSED_ORDER_LEVEL"), stats)


class PeopleTransformer:
    def transform(self, df: pd.DataFrame) -> TransformResult:
        out = c.strip_strings(df, ["regional_manager", "region"])
        out["region"] = c.title_case(out["region"])
        out[c.PARSE_ERRORS] = ""
        out, dups = c.remove_exact_duplicates(out, ["regional_manager", "region"])
        stats = {"input_rows": len(df), "exact_duplicates_removed": len(dups), "output_rows": len(out)}
        log.info("[people] Transformation stats: %s", stats)
        return TransformResult(out, _removed(dups, "EXACT_DUPLICATE_RECORD"), stats)
