"""Per-run data quality & execution report (JSON + Markdown)."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.validation.validator import CheckResult


@dataclass
class SourceSummary:
    source: str
    file_name: str = ""
    checksum: str = ""
    status: str = "PENDING"           # PROCESSED | SKIPPED_ALREADY_LOADED | MISSING_OPTIONAL | FAILED
    records_extracted: int = 0        # all data records incl. malformed
    malformed: int = 0
    removed_in_transform: int = 0     # exact duplicates removed / collapsed
    rejected: int = 0                 # failed validation rules
    valid: int = 0
    warnings: int = 0
    transform_stats: dict = field(default_factory=dict)
    rejection_breakdown: dict = field(default_factory=dict)
    warning_breakdown: dict = field(default_factory=dict)
    message: str = ""


class DataQualityReport:
    def __init__(self, run_id: int | str, started_at: datetime):
        self.run_id = run_id
        self.started_at = started_at
        self.finished_at: datetime | None = None
        self.status = "RUNNING"
        self.sources: dict[str, SourceSummary] = {}
        self.checks: list[CheckResult] = []
        self.load_stats: dict = {}
        self.errors: list[str] = []

    def source(self, name: str) -> SourceSummary:
        return self.sources.setdefault(name, SourceSummary(name))

    @staticmethod
    def breakdown(reasons) -> dict:
        counter: Counter = Counter()
        for value in reasons:
            for part in str(value).split(";"):
                part = part.strip()
                if part:
                    counter[part.split(":")[0]] += 1
        return dict(counter.most_common())

    def add_checks(self, checks: list[CheckResult]) -> None:
        self.checks.extend(checks)

    def add_check(self, source: str, name: str, category: str, severity: str, description: str,
                  checked: int, failed: int) -> CheckResult:
        chk = CheckResult(source, name, category, severity, description, checked, failed)
        self.checks.append(chk)
        return chk

    # ------------------------------------------------------------------ output
    def summary(self) -> dict:
        fails = sum(1 for c in self.checks if c.status == "FAIL")
        warns = sum(1 for c in self.checks if c.status == "WARN")
        return {
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "finished_at": self.finished_at.isoformat(timespec="seconds") if self.finished_at else None,
            "duration_seconds": round((self.finished_at - self.started_at).total_seconds(), 2)
            if self.finished_at else None,
            "checks_total": len(self.checks),
            "checks_failed": fails,
            "checks_warning": warns,
            "checks_passed": len(self.checks) - fails - warns,
        }

    def to_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "sources": {k: vars(v) for k, v in self.sources.items()},
            "load": self.load_stats,
            "checks": [c.as_dict() for c in self.checks],
            "errors": self.errors,
        }

    def to_markdown(self) -> str:
        s = self.summary()
        lines = [
            f"# Data Quality & Execution Report - Run {self.run_id}",
            "",
            f"- **Status:** {s['status']}",
            f"- **Started:** {s['started_at']}",
            f"- **Finished:** {s['finished_at']}",
            f"- **Duration (s):** {s['duration_seconds']}",
            f"- **Checks:** {s['checks_total']} total / {s['checks_passed']} passed / "
            f"{s['checks_failed']} failed / {s['checks_warning']} warnings",
            "",
            "## Sources",
            "",
            "| Source | File | Status | Extracted | Malformed | Removed (dedup) | Rejected | Valid | Warnings |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
        for src in self.sources.values():
            lines.append(f"| {src.source} | {src.file_name} | {src.status} | {src.records_extracted:,} | "
                         f"{src.malformed:,} | {src.removed_in_transform:,} | {src.rejected:,} | "
                         f"{src.valid:,} | {src.warnings:,} |")
        if self.load_stats:
            lines += ["", "## Warehouse Load", "", "| Metric | Value |", "|---|---:|"]
            lines += [f"| {k} | {v:,} |" if isinstance(v, int) else f"| {k} | {v} |"
                      for k, v in self.load_stats.items()]
        lines += ["", "## Checks", "",
                  "| Source | Check | Category | Severity | Checked | Failed | Status |",
                  "|---|---|---|---|---:|---:|---|"]
        for c in self.checks:
            lines.append(f"| {c.source} | {c.check_name} | {c.category} | {c.severity} | "
                         f"{c.records_checked:,} | {c.records_failed:,} | {c.status} |")
        for src in self.sources.values():
            if src.rejection_breakdown or src.warning_breakdown:
                lines += ["", f"### {src.source}: rejection / warning reasons", ""]
                for k, v in src.rejection_breakdown.items():
                    lines.append(f"- REJECTED `{k}`: {v:,}")
                for k, v in src.warning_breakdown.items():
                    lines.append(f"- WARNING `{k}`: {v:,}")
            if src.transform_stats:
                lines += ["", f"### {src.source}: transformation statistics", ""]
                lines += [f"- {k}: {v:,}" if isinstance(v, int) else f"- {k}: {v}"
                          for k, v in src.transform_stats.items()]
        if self.errors:
            lines += ["", "## Errors", ""] + [f"- {e}" for e in self.errors]
        return "\n".join(lines) + "\n"

    def write(self, directory: Path) -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"run_{int(self.run_id):06d}" if str(self.run_id).isdigit() else f"run_{self.run_id}"
        json_path = directory / f"{stem}_dq_report.json"
        md_path = directory / f"{stem}_dq_report.md"
        json_path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        md_path.write_text(self.to_markdown(), encoding="utf-8")
        return json_path, md_path
