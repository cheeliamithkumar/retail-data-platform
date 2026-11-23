"""Generic, reusable column-level cleaning functions.

Every function is pure (returns new objects) so it can be unit-tested in isolation
and reused for any source.
"""
from __future__ import annotations

import hashlib
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

PARSE_ERRORS = "_parse_errors"


def strip_strings(df: pd.DataFrame, columns: Iterable[str] | None = None) -> pd.DataFrame:
    """Trim and collapse internal whitespace; empty strings become missing."""
    out = df.copy()
    cols = list(columns) if columns is not None else [
        c for c in out.columns
        if not c.startswith("_")
        and (out[c].dtype == object or pd.api.types.is_string_dtype(out[c]))
    ]
    for col in cols:
        s = out[col].astype("object")
        mask = s.notna()
        cleaned = s[mask].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
        s = s.copy()
        s[mask] = cleaned
        # mask() keeps object dtype; replace() would downcast an all-empty column to
        # float on pandas 2.x and break later .str operations.
        out[col] = s.mask(s.eq(""), np.nan).astype("object")
    return out


def remove_exact_duplicates(df: pd.DataFrame, subset: Sequence[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Drop rows whose ``subset`` values are identical to an earlier row.

    Returns (kept, removed). First occurrence is kept.
    """
    dup_mask = df.duplicated(subset=list(subset), keep="first")
    return df.loc[~dup_mask].copy(), df.loc[dup_mask].copy()


def add_parse_error(df: pd.DataFrame, mask: pd.Series, message: str) -> None:
    """Append ``message`` to the parse-error column for rows in ``mask`` (in place)."""
    if PARSE_ERRORS not in df.columns:
        df[PARSE_ERRORS] = ""
    if not mask.any():
        return
    current = df.loc[mask, PARSE_ERRORS].fillna("")
    df.loc[mask, PARSE_ERRORS] = np.where(current == "", message, current + ";" + message)


def to_numeric(df: pd.DataFrame, column: str, integer: bool = False) -> pd.DataFrame:
    """Convert to numeric; values present but unparseable are recorded as parse errors."""
    out = df.copy()
    raw = out[column]
    cleaned = raw.astype("object").where(raw.isna(), raw.astype(str).str.replace(r"[,$\s]", "", regex=True))
    num = pd.to_numeric(cleaned, errors="coerce")
    bad = raw.notna() & num.isna()
    if integer:
        non_int = num.notna() & (num % 1 != 0)
        bad = bad | non_int
        num = num.where(~non_int)
        out[column] = num.astype("Int64")
    else:
        out[column] = num.astype("float64")
    add_parse_error(out, bad, f"{column}:invalid_number")
    return out


def parse_dates(df: pd.DataFrame, column: str, formats: Sequence[str]) -> pd.DataFrame:
    """Standardise dates written in any of ``formats`` to ``datetime64`` (date only)."""
    out = df.copy()
    raw = out[column]
    result = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns]")
    for fmt in formats:
        todo = result.isna() & raw.notna()
        if not todo.any():
            break
        result.loc[todo] = pd.to_datetime(raw[todo], format=fmt, errors="coerce")
    bad = raw.notna() & result.isna()
    out[column] = result.dt.normalize()
    add_parse_error(out, bad, f"{column}:invalid_date")
    return out


def standardise_postal_code(series: pd.Series, width: int = 5) -> pd.Series:
    """US ZIPs lose leading zeros in spreadsheets (e.g. 5401 -> 05401); restore them."""
    s = series.astype("object")
    mask = s.notna()
    vals = s[mask].astype(str).str.strip().str.replace(r"\.0+$", "", regex=True)
    vals = vals.where(~vals.str.fullmatch(r"\d+"), vals.str.zfill(width))
    s = s.copy()
    s[mask] = vals
    return s


def title_case(series: pd.Series) -> pd.Series:
    s = series.astype("object")
    mask = s.notna()
    s = s.copy()
    s[mask] = s[mask].astype(str).str.title()
    return s


def fill_from_group_mode(df: pd.DataFrame, target: str, group_cols: Sequence[str]) -> tuple[pd.Series, pd.Series]:
    """Impute missing ``target`` with the most frequent value within ``group_cols``.

    Returns (filled series, mask of rows that were imputed).
    """
    known = df.dropna(subset=[target])
    if known.empty:
        return df[target], pd.Series(False, index=df.index)
    modes = (known.groupby(list(group_cols))[target]
             .agg(lambda x: x.value_counts().index[0]).rename("_mode"))
    merged = df[list(group_cols)].merge(modes, left_on=list(group_cols), right_index=True, how="left")
    missing = df[target].isna()
    imputed = missing & merged["_mode"].notna()
    filled = df[target].where(~imputed, merged["_mode"])
    return filled, imputed


def row_hash(df: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    """Stable SHA-256 over canonical string forms of ``columns``."""
    def canon(col: pd.Series) -> pd.Series:
        if pd.api.types.is_float_dtype(col):
            return col.map(lambda v: "" if pd.isna(v) else f"{v:.4f}")
        if pd.api.types.is_datetime64_any_dtype(col):
            return col.dt.strftime("%Y-%m-%d").fillna("")
        return col.astype("object").map(lambda v: "" if pd.isna(v) else str(v))

    joined = pd.Series("", index=df.index, dtype="object")
    for i, c in enumerate(columns):
        joined = joined + ("|" if i else "") + canon(df[c])
    return joined.map(lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest())
