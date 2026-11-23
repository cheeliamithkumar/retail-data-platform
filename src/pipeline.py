"""Runs the whole pipeline: ingest -> transform -> validate -> load -> audit -> report."""
from __future__ import annotations

import getpass
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy.engine import Engine

from src.config import (PROCESSED_DIR, RAW_DIR, REJECTED_DIR, REPORT_DIR, SOURCE_SPECS,
                        SourceSpec)
from src.ingestion import CSVIngestor, IngestionError, IngestionResult, SourceFileMissingError
from src.loading import AuditRepository, WarehouseLoader
from src.transformation import OrdersTransformer, PeopleTransformer, ReturnsTransformer
from src.transformation.transformer import TransformResult
from src.utils.file_utils import ensure_dir
from src.utils.logger import get_logger
from src.validation import (DataQualityReport, DataValidator, build_order_rules,
                            build_people_rules, build_return_rules)
from src.validation.validator import ValidationResult

log = get_logger("pipeline")

TRANSFORMERS = {"orders": OrdersTransformer, "returns": ReturnsTransformer, "people": PeopleTransformer}
STAGING_TABLE = {"orders": "stg_orders", "returns": "stg_returns", "people": "stg_people"}
# returns collapsing to one row per order is expected, not an error
NON_REJECTION_REASONS = {"COLLAPSED_ORDER_LEVEL"}


class PipelineError(Exception):
    pass


@dataclass
class SourceBatch:
    spec: SourceSpec
    ingestion: IngestionResult
    transform: TransformResult | None = None
    validation: ValidationResult | None = None
    rejected_output: pd.DataFrame | None = None


@dataclass
class PipelineOutcome:
    run_id: int | str
    status: str
    report: DataQualityReport
    report_paths: tuple[Path, Path] | None = None
    totals: dict = field(default_factory=dict)


class RetailPipeline:
    def __init__(
        self,
        engine: Engine | None = None,
        raw_dir: Path = RAW_DIR,
        processed_dir: Path = PROCESSED_DIR,
        rejected_dir: Path = REJECTED_DIR,
        report_dir: Path = REPORT_DIR,
        specs: tuple[SourceSpec, ...] = SOURCE_SPECS,
        force: bool = False,
        today: date | None = None,
        triggered_by: str | None = None,
    ):
        self.engine = engine
        self.dry_run = engine is None
        self.raw_dir, self.processed_dir = Path(raw_dir), Path(processed_dir)
        self.rejected_dir, self.report_dir = Path(rejected_dir), Path(report_dir)
        self.specs = specs
        self.force = force
        self.today = today
        self.triggered_by = triggered_by or _whoami()
        self.audit = AuditRepository(engine) if engine is not None else None
        self.loader = WarehouseLoader(engine) if engine is not None else None
        self._batches: dict[str, SourceBatch] = {}

    def run(self) -> PipelineOutcome:
        started = datetime.now()
        run_id: int | str = f"dryrun_{started:%Y%m%d_%H%M%S}"
        totals = {"records_extracted": 0, "records_valid": 0, "records_rejected": 0,
                  "records_loaded": 0, "records_updated": 0, "records_unchanged": 0}
        report: DataQualityReport | None = None
        self._batches = {}
        try:
            if not self.dry_run:
                self.loader.ensure_schema()
                run_id = self.audit.start_run(self.triggered_by)
            report = DataQualityReport(run_id, started)
            log.info("=" * 70)
            log.info("Pipeline run %s started (dry_run=%s, force=%s)", run_id, self.dry_run, self.force)

            batches = self._extract(report)
            self._batches = batches
            # people before orders (region check), orders before returns (order check)
            for name in ("people", "orders", "returns"):
                if name in batches:
                    self._transform_and_validate(batches[name], batches, report)
            self._write_outputs(batches, run_id, report)
            for b in batches.values():
                s = report.source(b.spec.name)
                totals["records_extracted"] += s.records_extracted
                totals["records_valid"] += s.valid
                totals["records_rejected"] += len(b.rejected_output) if b.rejected_output is not None else 0

            if not batches:
                status = "NO_NEW_DATA"
                log.info("No new source files to process.")
            else:
                if not self.dry_run:
                    self._load(batches, run_id, report, totals)
                status = self._final_status(report)
            report.status = status
        except Exception as exc:  # noqa: BLE001 - log it, mark the run FAILED
            status = "FAILED"
            log.error("Pipeline run %s FAILED: %s", run_id, exc)
            log.debug(traceback.format_exc())
            if report is None:
                report = DataQualityReport(run_id, started)
            report.status = status
            report.errors.append(f"{type(exc).__name__}: {exc}")

        report.finished_at = datetime.now()
        summary = report.summary()
        totals["checks_failed"] = summary["checks_failed"]
        totals["checks_warning"] = summary["checks_warning"]
        if not self.dry_run and isinstance(run_id, int):
            self._persist_audit(run_id, report, totals, status)
        paths = report.write(self.report_dir)
        log.info("Run %s finished: %s in %.2fs | %s", run_id, status,
                 summary["duration_seconds"], totals)
        log.info("Data quality report: %s", paths[1])
        return PipelineOutcome(run_id, status, report, paths, totals)

    def _extract(self, report: DataQualityReport) -> dict[str, SourceBatch]:
        batches: dict[str, SourceBatch] = {}
        for spec in self.specs:
            summary = report.source(spec.name)
            summary.file_name = spec.filename
            path = self.raw_dir / spec.filename
            try:
                result = CSVIngestor(spec).ingest(path)
            except SourceFileMissingError as exc:
                if spec.required:
                    summary.status = "FAILED"
                    summary.message = str(exc)
                    raise PipelineError(f"Required source '{spec.name}' is missing: {path}") from exc
                summary.status = "MISSING_OPTIONAL"
                summary.message = str(exc)
                log.warning("[%s] Optional source not found, skipping: %s", spec.name, path)
                continue
            except IngestionError as exc:
                summary.status = "FAILED"
                summary.message = str(exc)
                if spec.required:
                    raise
                log.error("[%s] Optional source failed ingestion, skipping: %s", spec.name, exc)
                continue

            summary.checksum = result.checksum
            if not self.dry_run and not self.force and self.audit.is_file_processed(spec.name, result.checksum):
                summary.status = "SKIPPED_ALREADY_LOADED"
                summary.message = "Identical file content already loaded (use --force to reprocess)"
                log.info("[%s] %s already loaded (checksum match) - skipping", spec.name, spec.filename)
                continue
            summary.status = "PROCESSING"
            summary.records_extracted = result.total_records
            summary.malformed = result.malformed_count
            batches[spec.name] = SourceBatch(spec, result)
        return batches

    def _transform_and_validate(self, batch: SourceBatch, batches: dict[str, SourceBatch],
                                report: DataQualityReport) -> None:
        name = batch.spec.name
        tr = TRANSFORMERS[name]().transform(batch.ingestion.data)
        batch.transform = tr

        if name == "people":
            rules = build_people_rules()
        elif name == "orders":
            regions: set[str] = set()
            if "people" in batches and batches["people"].validation is not None:
                regions |= set(batches["people"].validation.valid["region"])
            if not self.dry_run:
                regions |= self.audit.known_regions()
            if not regions:
                log.warning("[orders] No region reference data available - UNKNOWN_REGION check skipped")
            existing = None if self.dry_run else self.audit.existing_transactions(tr.data["order_id"])
            rules = build_order_rules(today=self.today, valid_regions=regions or None,
                                      existing_transactions=existing)
        elif name == "returns":
            known: set[str] = set()
            if "orders" in batches and batches["orders"].validation is not None:
                known |= set(batches["orders"].validation.valid["order_id"])
            if not self.dry_run:
                known |= self.audit.existing_order_ids(tr.data["order_id"])
            rules = build_return_rules(known)
        else:  # pragma: no cover
            raise PipelineError(f"No rules defined for source {name}")

        vr = DataValidator(name, rules).validate(tr.data)
        batch.validation = vr
        report.add_checks(vr.checks)

        # write the original raw values to the rejected file, not the cleaned ones
        raw = batch.ingestion.data
        parts = []
        if not batch.ingestion.malformed.empty:
            parts.append(batch.ingestion.malformed)
        removed_rej = tr.removed[~tr.removed["rejection_reasons"].isin(NON_REJECTION_REASONS)]
        if not removed_rej.empty:
            parts.append(raw.loc[removed_rej.index].assign(rejection_reasons=removed_rej["rejection_reasons"]))
        if not vr.rejected.empty:
            parts.append(raw.loc[vr.rejected.index].assign(rejection_reasons=vr.reasons))
        batch.rejected_output = (pd.concat(parts, ignore_index=True) if parts
                                 else pd.DataFrame(columns=[*raw.columns, "rejection_reasons"]))

        s = report.source(name)
        s.removed_in_transform = len(tr.removed)
        s.rejected = len(vr.rejected)
        s.valid = len(vr.valid)
        s.warnings = len(vr.warnings)
        s.transform_stats = tr.stats
        s.rejection_breakdown = report.breakdown(batch.rejected_output["rejection_reasons"])
        s.warning_breakdown = report.breakdown(vr.warnings)

        accounted = s.malformed + s.removed_in_transform + s.rejected + s.valid
        report.add_check(name, "ROW_COUNT_RECONCILIATION", "Row count reconciliation", "ERROR",
                         "extracted = malformed + removed + rejected + valid",
                         s.records_extracted, abs(s.records_extracted - accounted))
        log.info("[%s] Reconciliation: extracted=%d -> malformed=%d removed=%d rejected=%d valid=%d",
                 name, s.records_extracted, s.malformed, s.removed_in_transform, s.rejected, s.valid)

    def _write_outputs(self, batches: dict[str, SourceBatch], run_id, report: DataQualityReport) -> None:
        tag = f"run_{run_id:06d}" if isinstance(run_id, int) else str(run_id)
        for name, b in batches.items():
            if b.rejected_output is not None and not b.rejected_output.empty:
                path = ensure_dir(self.rejected_dir) / f"{tag}_{name}_rejected.csv"
                b.rejected_output.to_csv(path, index=False)
                log.info("[%s] %d rejected records -> %s", name, len(b.rejected_output), path)
            if b.validation is not None and not b.validation.valid.empty:
                path = ensure_dir(self.processed_dir) / f"{tag}_{name}_clean.csv"
                b.validation.valid.drop(columns=["_parse_errors"], errors="ignore").to_csv(path, index=False)
            report.source(name).status = "PROCESSED" if self.dry_run else "VALIDATED"

    def _load(self, batches: dict[str, SourceBatch], run_id: int, report: DataQualityReport,
              totals: dict) -> None:
        frames = {STAGING_TABLE[n]: b.validation.valid for n, b in batches.items() if b.validation is not None}
        with self.engine.begin() as conn:  # one transaction for the whole load
            stats = self.loader.load(conn, run_id, frames)
            checks = self.loader.integrity_checks(conn)
            for name, b in batches.items():
                s = report.source(name)
                self.audit.register_file(conn, run_id, name, b.spec.filename, b.ingestion.checksum,
                                         b.ingestion.file_size_bytes, s.records_extracted, s.valid,
                                         len(b.rejected_output))
        for name, b in batches.items():
            report.source(name).status = "PROCESSED"

        report.load_stats = stats.as_dict()
        totals["records_loaded"] = stats.fact_new
        totals["records_updated"] = stats.fact_changed
        totals["records_unchanged"] = stats.fact_unchanged

        if "orders" in batches:
            valid_orders = report.source("orders").valid
            report.add_check("warehouse", "FACT_DIMENSION_KEY_RESOLUTION", "Referential integrity", "ERROR",
                             "Every staged order line resolved all dimension keys",
                             stats.staged.get("stg_orders", 0), stats.fact_unresolved)
            loaded = stats.fact_new + stats.fact_changed + stats.fact_unchanged
            report.add_check("warehouse", "LOAD_ROW_RECONCILIATION", "Row count reconciliation", "ERROR",
                             "valid order lines = inserted + updated + unchanged",
                             valid_orders, abs(valid_orders - loaded))
        for check, (checked, failed) in checks.items():
            report.add_check("warehouse", check, "Warehouse integrity", "ERROR",
                             "Post-load warehouse invariant", checked, failed)

    def _persist_audit(self, run_id: int, report: DataQualityReport, totals: dict, status: str) -> None:
        try:
            self.audit.save_dq_results(run_id, report.checks)
            saved = 0
            for name, b in self._batches.items():
                saved += self.audit.save_rejected(run_id, name, b.rejected_output)
            if saved:
                log.info("Persisted %d rejected records to etl_rejected_records", saved)
            self.audit.finish_run(run_id, status, totals, "; ".join(report.errors) or None)
        except Exception as exc:  # noqa: BLE001
            log.error("Could not persist audit information for run %s: %s", run_id, exc)
            report.errors.append(f"Audit persistence failed: {exc}")

    @staticmethod
    def _final_status(report: DataQualityReport) -> str:
        summary = report.summary()
        if summary["checks_failed"] or summary["checks_warning"]:
            return "SUCCESS_WITH_WARNINGS"
        return "SUCCESS"


def _whoami() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "unknown"
