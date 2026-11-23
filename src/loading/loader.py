"""Warehouse loader: schema deployment, staging loads and SQL-based dimensional loads."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from src.config import SQL_DIR
from src.utils.db import run_sql_file
from src.utils.logger import get_logger

log = get_logger("loading")

SCHEMA_DIR = SQL_DIR / "schema"
TRANSFORM_DIR = SQL_DIR / "transformations"

STAGING_COLUMNS: dict[str, list[str]] = {
    "stg_orders": [
        "row_id", "order_id", "order_date", "ship_date", "ship_mode", "customer_id",
        "customer_name", "segment", "country", "city", "state", "postal_code", "region",
        "product_id", "category", "sub_category", "product_name", "sales", "quantity",
        "discount", "profit", "ship_days", "unit_price", "row_hash", "business_hash",
    ],
    "stg_returns": ["order_id", "returned"],
    "stg_people": ["regional_manager", "region"],
}
LINEAGE_COLUMNS = {"_source_file": "source_file", "_source_line": "source_line", "_ingested_at": "ingested_at"}


@dataclass
class LoadStats:
    staged: dict = field(default_factory=dict)
    fact_new: int = 0
    fact_changed: int = 0
    fact_unchanged: int = 0
    fact_unresolved: int = 0
    returns_flagged: int = 0
    dims: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {f"staged_{k}": v for k, v in self.staged.items()}
        out.update({
            "fact_rows_inserted": self.fact_new,
            "fact_rows_updated": self.fact_changed,
            "fact_rows_unchanged": self.fact_unchanged,
            "fact_rows_unresolved_keys": self.fact_unresolved,
            "fact_lines_flagged_returned": self.returns_flagged,
        })
        out.update({f"{k}_total_rows": v for k, v in self.dims.items()})
        return out


class WarehouseLoader:
    def __init__(self, engine: Engine, schema_dir: Path = SCHEMA_DIR, transform_dir: Path = TRANSFORM_DIR):
        self.engine = engine
        self.schema_dir = schema_dir
        self.transform_dir = transform_dir

    # ------------------------------------------------------------------ schema
    def ensure_schema(self) -> None:
        """Deploy all DDL (idempotent: CREATE IF NOT EXISTS / CREATE OR REPLACE VIEW)."""
        files = sorted(self.schema_dir.glob("*.sql"))
        with self.engine.begin() as conn:
            for path in files:
                run_sql_file(conn, path)
        log.info("Schema verified (%d DDL scripts)", len(files))

    # ------------------------------------------------------------------ staging
    @staticmethod
    def prepare_staging_frame(table: str, df: pd.DataFrame, run_id: int) -> pd.DataFrame:
        cols = STAGING_COLUMNS[table]
        out = df[cols + list(LINEAGE_COLUMNS)].rename(columns=LINEAGE_COLUMNS).copy()
        for col in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[col]) and col != "ingested_at":
                out[col] = out[col].dt.date
        if "returned" in out.columns:
            out["returned"] = out["returned"].astype(bool).astype(int)
        out.insert(0, "etl_run_id", run_id)
        # Nullable pandas types -> plain Python objects with None for NULL
        return out.astype(object).where(out.notna(), None)

    def stage(self, conn: Connection, table: str, df: pd.DataFrame, run_id: int) -> int:
        frame = self.prepare_staging_frame(table, df, run_id)
        if frame.empty:
            return 0
        frame.to_sql(table, con=conn, if_exists="append", index=False, chunksize=1000, method="multi")
        log.info("Staged %d rows into %s", len(frame), table)
        return len(frame)

    # ------------------------------------------------------------------ warehouse load
    def load(self, conn: Connection, run_id: int, frames: dict[str, pd.DataFrame]) -> LoadStats:
        """Run inside the caller's transaction: stage -> dimensions -> fact -> returns."""
        stats = LoadStats()
        for table in STAGING_COLUMNS:
            conn.exec_driver_sql(f"DELETE FROM {table}")  # DELETE, not TRUNCATE: no implicit commit
        for table, df in frames.items():
            stats.staged[table] = self.stage(conn, table, df, run_id)

        conn.execute(text("SET @run_id = :run_id"), {"run_id": run_id})

        counts = conn.execute(text("""
            SELECT
                COALESCE(SUM(f.sales_key IS NULL), 0)                              AS new_rows,
                COALESCE(SUM(f.sales_key IS NOT NULL AND f.row_hash <> s.row_hash), 0) AS changed_rows,
                COALESCE(SUM(f.row_hash = s.row_hash), 0)                          AS unchanged_rows
            FROM stg_orders s
            LEFT JOIN fact_sales f ON f.order_id = s.order_id AND f.source_row_id = s.row_id
            WHERE s.etl_run_id = :run_id"""), {"run_id": run_id}).one()

        for path in sorted(self.transform_dir.glob("*.sql")):
            log.info("Running transformation %s", path.name)
            affected = run_sql_file(conn, path)
            if path.name.endswith("apply_returns.sql"):
                stats.returns_flagged = affected[-1] if affected else 0

        resolved = conn.execute(text("SELECT COUNT(*) FROM tmp_fact_sales_resolved")).scalar_one()
        staged_orders = stats.staged.get("stg_orders", 0)
        stats.fact_unresolved = staged_orders - int(resolved)
        # Only rows whose keys resolved can be inserted/updated
        stats.fact_new, stats.fact_changed, stats.fact_unchanged = (int(x) for x in counts)
        if stats.fact_unresolved:
            log.error("%d staged order rows could not resolve dimension keys", stats.fact_unresolved)
        conn.exec_driver_sql("DROP TEMPORARY TABLE IF EXISTS tmp_fact_sales_resolved")

        for table in ("dim_customer", "dim_product", "dim_region", "dim_date", "fact_sales"):
            stats.dims[table] = int(conn.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one())
        log.info("Load complete: %s", stats.as_dict())
        return stats

    # ------------------------------------------------------------------ post-load checks
    @staticmethod
    def integrity_checks(conn: Connection) -> dict[str, tuple[int, int]]:
        """Warehouse-level checks -> {name: (records_checked, records_failed)}."""
        total = int(conn.exec_driver_sql("SELECT COUNT(*) FROM fact_sales").scalar_one())
        orphans = int(conn.exec_driver_sql("""
            SELECT COUNT(*) FROM fact_sales f
            LEFT JOIN dim_customer c ON c.customer_key = f.customer_key
            LEFT JOIN dim_product  p ON p.product_key  = f.product_key
            LEFT JOIN dim_region   r ON r.region_key   = f.region_key
            LEFT JOIN dim_date     d ON d.date_key     = f.order_date_key
            WHERE c.customer_key IS NULL OR p.product_key IS NULL
               OR r.region_key IS NULL OR d.date_key IS NULL""").scalar_one())
        dup_keys = int(conn.exec_driver_sql("""
            SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                SELECT COUNT(*) AS cnt FROM fact_sales
                GROUP BY order_id, source_row_id HAVING COUNT(*) > 1) d""").scalar_one())
        dup_tx = int(conn.exec_driver_sql("""
            SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                SELECT COUNT(*) AS cnt FROM fact_sales
                GROUP BY business_hash HAVING COUNT(*) > 1) d""").scalar_one())
        return {
            "WAREHOUSE_REFERENTIAL_INTEGRITY": (total, orphans),
            "WAREHOUSE_PRIMARY_KEY_UNIQUENESS": (total, dup_keys),
            "WAREHOUSE_DUPLICATE_TRANSACTIONS": (total, dup_tx),
        }
