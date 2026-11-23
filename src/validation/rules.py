"""Declarative data-quality rules.

A rule is a named function ``DataFrame -> boolean Series`` where ``True`` means the
row FAILS the rule. ERROR rules reject the row; WARNING rules only flag it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Callable, Iterable

import pandas as pd

from src.transformation.cleaners import PARSE_ERRORS


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class Rule:
    name: str
    description: str
    category: str
    severity: Severity
    check: Callable[[pd.DataFrame], pd.Series]
    # Set-based rules (uniqueness) are evaluated only on rows that passed all
    # row-level ERROR rules, so a bad first occurrence never knocks out a good one.
    on_survivors: bool = False


# --------------------------------------------------------------------------- helpers
def _parse_error_for(df: pd.DataFrame, column: str) -> pd.Series:
    return df[PARSE_ERRORS].fillna("").str.contains(f"{column}:", regex=False)


def not_null_rule(column: str) -> Rule:
    return Rule(
        name=f"NULL_{column.upper()}",
        description=f"'{column}' is mandatory",
        category="Null check",
        severity=Severity.ERROR,
        check=lambda df, col=column: df[col].isna() & ~_parse_error_for(df, col),
    )


def parse_error_rule() -> Rule:
    return Rule(
        name="INVALID_FORMAT",
        description="Value could not be converted to the expected type (number/date/flag)",
        category="Data type",
        severity=Severity.ERROR,
        check=lambda df: df[PARSE_ERRORS].fillna("") != "",
    )


def unique_rule(name: str, columns: list[str], description: str, category: str = "Primary key") -> Rule:
    return Rule(
        name=name, description=description, category=category, severity=Severity.ERROR,
        check=lambda df, cols=columns: df.duplicated(subset=cols, keep="first"),
        on_survivors=True,
    )


def in_set_rule(name: str, column: str, allowed: Iterable[str], description: str,
                severity: Severity = Severity.ERROR) -> Rule:
    allowed_set = set(allowed)
    return Rule(
        name=name, description=description, category="Referential integrity",
        severity=severity,
        check=lambda df: df[column].notna() & ~df[column].isin(allowed_set),
    )


# --------------------------------------------------------------------------- rule sets
ORDER_REQUIRED = ["row_id", "order_id", "order_date", "ship_date", "customer_id",
                  "product_id", "region", "sales", "quantity", "profit"]


def build_order_rules(
    today: date | None = None,
    valid_regions: Iterable[str] | None = None,
    existing_transactions: pd.DataFrame | None = None,
    min_date: date = date(2000, 1, 1),
) -> list[Rule]:
    """Rules for order lines.

    ``existing_transactions``: warehouse rows (order_id, row_id, business_hash) used to
    detect duplicate transactions across loads.
    """
    today_ts = pd.Timestamp(today or date.today())
    min_ts = pd.Timestamp(min_date)
    rules: list[Rule] = [parse_error_rule(), *(not_null_rule(c) for c in ORDER_REQUIRED)]
    rules += [
        Rule("FUTURE_ORDER_DATE", "Order date is in the future", "Invalid date", Severity.ERROR,
             lambda df: df["order_date"] > today_ts),
        Rule("ORDER_DATE_OUT_OF_RANGE", f"Order date before {min_date}", "Invalid date", Severity.ERROR,
             lambda df: df["order_date"] < min_ts),
        Rule("SHIP_BEFORE_ORDER", "Ship date earlier than order date", "Invalid date", Severity.ERROR,
             lambda df: df["ship_date"] < df["order_date"]),
        Rule("NON_POSITIVE_QUANTITY", "Quantity must be > 0", "Negative quantity", Severity.ERROR,
             lambda df: (df["quantity"] <= 0).fillna(False).astype(bool)),
        Rule("NON_POSITIVE_SALES", "Sales amount must be > 0", "Invalid financial value", Severity.ERROR,
             lambda df: df["sales"] <= 0),
        Rule("INVALID_DISCOUNT", "Discount must be in [0, 1)", "Invalid financial value", Severity.ERROR,
             lambda df: (df["discount"] < 0) | (df["discount"] >= 1)),
        Rule("PROFIT_EXCEEDS_SALES", "Profit cannot exceed sales revenue", "Invalid financial value",
             Severity.ERROR, lambda df: df["profit"] > df["sales"]),
    ]
    if valid_regions is not None:
        rules.append(in_set_rule("UNKNOWN_REGION", "region", valid_regions,
                                 "Region not present in the region/manager reference data"))
    rules += [
        unique_rule("DUPLICATE_PRIMARY_KEY", ["order_id", "row_id"],
                    "Source key (order_id, row_id) appears more than once in the batch"),
        unique_rule("DUPLICATE_TRANSACTION", ["business_hash"],
                    "Identical transaction (all business fields) under a different row id",
                    category="Duplicate transaction"),
    ]
    if existing_transactions is not None and not existing_transactions.empty:
        existing = existing_transactions[["order_id", "row_id", "business_hash"]]

        def cross_load_duplicate(df: pd.DataFrame) -> pd.Series:
            m = df[["order_id", "row_id", "business_hash"]].reset_index().merge(
                existing, on="business_hash", how="inner", suffixes=("", "_wh"))
            m = m[(m["order_id"] != m["order_id_wh"]) | (m["row_id"].astype("int64") != m["row_id_wh"].astype("int64"))]
            return df.index.to_series().isin(set(m["index"]))

        rules.append(Rule("DUPLICATE_TRANSACTION_IN_WAREHOUSE",
                          "Identical transaction already loaded under a different source key",
                          "Duplicate transaction", Severity.ERROR, cross_load_duplicate, on_survivors=True))
    rules += [
        Rule("PRODUCT_ID_MULTIPLE_NAMES", "Product ID is used for more than one product name",
             "Consistency", Severity.WARNING,
             lambda df: df.groupby("product_id")["product_name"].transform("nunique").fillna(0) > 1),
        Rule("POSTAL_CODE_UNKNOWN", "Postal code missing and could not be imputed", "Null check",
             Severity.WARNING, lambda df: df["postal_code"] == "UNKNOWN"),
        Rule("LOSS_EXCEEDS_SALES", "Loss larger than the sale value (review pricing/discount)",
             "Business rule", Severity.WARNING, lambda df: df["profit"] < -df["sales"]),
    ]
    return rules


def build_return_rules(known_order_ids: Iterable[str] | None) -> list[Rule]:
    rules = [parse_error_rule(), not_null_rule("order_id"), not_null_rule("returned")]
    if known_order_ids is not None:
        known = set(known_order_ids)
        rules.append(Rule(
            "ORPHAN_RETURN", "Returned order does not exist in orders (batch or warehouse)",
            "Referential integrity", Severity.ERROR,
            lambda df: df["order_id"].notna() & ~df["order_id"].isin(known)))
    rules.append(unique_rule("DUPLICATE_PRIMARY_KEY", ["order_id"], "Order flagged as returned more than once"))
    return rules


def build_people_rules() -> list[Rule]:
    return [
        parse_error_rule(), not_null_rule("regional_manager"), not_null_rule("region"),
        unique_rule("DUPLICATE_PRIMARY_KEY", ["region"], "Region assigned to more than one manager"),
    ]
