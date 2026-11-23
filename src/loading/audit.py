"""ETL audit repository: run tracking, file registry, DQ results, rejected records."""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime
from typing import Iterable

import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection, Engine

from src.utils.logger import get_logger
from src.validation.validator import CheckResult

log = get_logger("audit")


def _chunks(items: list, size: int = 1000) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _json_safe(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    return value


class AuditRepository:
    def __init__(self, engine: Engine, pipeline_name: str = "retail_sales_etl"):
        self.engine = engine
        self.pipeline_name = pipeline_name

    # ------------------------------------------------------------------ runs
    def start_run(self, triggered_by: str = "manual") -> int:
        with self.engine.begin() as conn:
            result = conn.execute(text(
                "INSERT INTO etl_pipeline_runs (run_uuid, pipeline_name, start_ts, status, triggered_by) "
                "VALUES (:uuid, :name, :ts, 'RUNNING', :by)"),
                {"uuid": str(uuid.uuid4()), "name": self.pipeline_name,
                 "ts": datetime.now(), "by": triggered_by[:100]})
            run_id = int(result.lastrowid)
        log.info("Started pipeline run %s", run_id)
        return run_id

    def finish_run(self, run_id: int, status: str, stats: dict, error: str | None = None) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                UPDATE etl_pipeline_runs SET
                    end_ts = :end_ts, status = :status,
                    records_extracted = :extracted, records_valid = :valid,
                    records_rejected = :rejected, records_loaded = :loaded,
                    records_updated = :updated, records_unchanged = :unchanged,
                    checks_failed = :checks_failed, checks_warning = :checks_warning,
                    error_message = :error
                WHERE run_id = :run_id"""), {
                "end_ts": datetime.now(), "status": status, "run_id": run_id,
                "extracted": stats.get("records_extracted", 0), "valid": stats.get("records_valid", 0),
                "rejected": stats.get("records_rejected", 0), "loaded": stats.get("records_loaded", 0),
                "updated": stats.get("records_updated", 0), "unchanged": stats.get("records_unchanged", 0),
                "checks_failed": stats.get("checks_failed", 0),
                "checks_warning": stats.get("checks_warning", 0),
                "error": (error or None) and error[:60000],
            })
        log.info("Finished pipeline run %s with status %s", run_id, status)

    # ------------------------------------------------------------------ files
    def is_file_processed(self, source: str, checksum: str) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(text(
                "SELECT 1 FROM etl_file_registry WHERE source_name = :s AND file_checksum = :c"),
                {"s": source, "c": checksum}).first()
        return row is not None

    @staticmethod
    def register_file(conn: Connection, run_id: int, source: str, file_name: str, checksum: str,
                      size: int, extracted: int, valid: int, rejected: int) -> None:
        """Called inside the load transaction so a file is registered only if its data committed."""
        conn.execute(text("""
            INSERT INTO etl_file_registry (run_id, source_name, file_name, file_checksum,
                file_size_bytes, records_extracted, records_valid, records_rejected, processed_at)
            VALUES (:run_id, :source, :file_name, :checksum, :size, :extracted, :valid, :rejected, :ts)
                AS new
            ON DUPLICATE KEY UPDATE run_id = new.run_id, file_name = new.file_name,
                records_extracted = new.records_extracted, records_valid = new.records_valid,
                records_rejected = new.records_rejected, processed_at = new.processed_at"""),
            {"run_id": run_id, "source": source, "file_name": file_name, "checksum": checksum,
             "size": size, "extracted": extracted, "valid": valid, "rejected": rejected,
             "ts": datetime.now()})

    # ------------------------------------------------------------------ DQ
    def save_dq_results(self, run_id: int, checks: list[CheckResult]) -> None:
        if not checks:
            return
        rows = [{"run_id": run_id, "source": c.source, "name": c.check_name, "cat": c.category,
                 "sev": c.severity, "checked": c.records_checked, "failed": c.records_failed,
                 "status": c.status} for c in checks]
        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO etl_data_quality_results (run_id, source_name, check_name, check_category,
                    severity, records_checked, records_failed, check_status)
                VALUES (:run_id, :source, :name, :cat, :sev, :checked, :failed, :status)"""), rows)

    def save_rejected(self, run_id: int, source: str, rejected: pd.DataFrame) -> int:
        if rejected is None or rejected.empty:
            return 0
        payload_cols = [c for c in rejected.columns
                        if c not in ("rejection_reasons", "_source_file", "_source_line", "_ingested_at")]
        rows = []
        for rec in rejected.to_dict(orient="records"):
            line = _json_safe(rec.get("_source_line"))
            rows.append({
                "run_id": run_id, "source": source,
                "file": str(rec.get("_source_file", ""))[:255],
                "line": int(line) if line is not None else None,
                "reasons": str(rec.get("rejection_reasons", ""))[:1000],
                "raw": json.dumps({k: _json_safe(rec.get(k)) for k in payload_cols}, default=str),
            })
        with self.engine.begin() as conn:
            for chunk in _chunks(rows):
                conn.execute(text("""
                    INSERT INTO etl_rejected_records (run_id, source_name, source_file, source_line,
                        rejection_reasons, raw_record)
                    VALUES (:run_id, :source, :file, :line, :reasons, :raw)"""), chunk)
        return len(rows)

    # ------------------------------------------------------------------ lookups for validation
    def known_regions(self) -> set[str]:
        with self.engine.connect() as conn:
            return {r[0] for r in conn.execute(text("SELECT region FROM ref_regional_manager"))}

    def existing_order_ids(self, order_ids: Iterable[str]) -> set[str]:
        ids = sorted({str(i) for i in order_ids if pd.notna(i)})
        found: set[str] = set()
        stmt = text("SELECT DISTINCT order_id FROM fact_sales WHERE order_id IN :ids").bindparams(
            bindparam("ids", expanding=True))
        with self.engine.connect() as conn:
            for chunk in _chunks(ids):
                found |= {r[0] for r in conn.execute(stmt, {"ids": chunk})}
        return found

    def existing_transactions(self, order_ids: Iterable[str]) -> pd.DataFrame:
        """(order_id, row_id, business_hash) already in the warehouse for these orders."""
        ids = sorted({str(i) for i in order_ids if pd.notna(i)})
        stmt = text("SELECT order_id, source_row_id AS row_id, business_hash FROM fact_sales "
                    "WHERE order_id IN :ids").bindparams(bindparam("ids", expanding=True))
        frames = []
        with self.engine.connect() as conn:
            for chunk in _chunks(ids):
                frames.append(pd.DataFrame(conn.execute(stmt, {"ids": chunk}).fetchall(),
                                           columns=["order_id", "row_id", "business_hash"]))
        if not frames:
            return pd.DataFrame(columns=["order_id", "row_id", "business_hash"])
        return pd.concat(frames, ignore_index=True)
