"""Apply rule sets to a DataFrame and split it into valid and rejected records."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.utils.logger import get_logger
from src.validation.rules import Rule, Severity

log = get_logger("validation")


@dataclass
class CheckResult:
    source: str
    check_name: str
    category: str
    severity: str
    description: str
    records_checked: int
    records_failed: int

    @property
    def status(self) -> str:
        if self.records_failed == 0:
            return "PASS"
        return "FAIL" if self.severity == Severity.ERROR.value else "WARN"

    def as_dict(self) -> dict:
        return {
            "source": self.source, "check_name": self.check_name, "category": self.category,
            "severity": self.severity, "description": self.description,
            "records_checked": self.records_checked, "records_failed": self.records_failed,
            "status": self.status,
        }


@dataclass
class ValidationResult:
    source: str
    valid: pd.DataFrame
    rejected: pd.DataFrame           # typed rows + rejection_reasons
    reasons: pd.Series               # index -> "RULE_A; RULE_B" for rejected rows
    warnings: pd.Series              # index -> "RULE_X" for flagged (kept) rows
    checks: list[CheckResult] = field(default_factory=list)


class DataValidator:
    def __init__(self, source: str, rules: list[Rule]):
        self.source = source
        self.rules = rules

    def validate(self, df: pd.DataFrame) -> ValidationResult:
        n = len(df)
        failures: dict[str, pd.Series] = {}
        checks: list[CheckResult] = []

        def run(rule: Rule, frame: pd.DataFrame) -> pd.Series:
            if frame.empty:
                return pd.Series(False, index=frame.index)
            mask = rule.check(frame)
            return pd.Series(mask, index=frame.index).fillna(False).astype(bool)

        # row-level rules first
        for rule in (r for r in self.rules if not r.on_survivors):
            mask = run(rule, df)
            failures[rule.name] = mask.reindex(df.index, fill_value=False)
            checks.append(CheckResult(self.source, rule.name, rule.category, rule.severity.value,
                                      rule.description, n, int(mask.sum())))

        def error_mask() -> pd.Series:
            m = pd.Series(False, index=df.index)
            for rule in self.rules:
                if rule.severity == Severity.ERROR and rule.name in failures:
                    m |= failures[rule.name]
            return m

        # then uniqueness rules, only on rows that are still valid
        for rule in (r for r in self.rules if r.on_survivors):
            survivors = df.loc[~error_mask()]
            mask = run(rule, survivors)
            failures[rule.name] = mask.reindex(df.index, fill_value=False)
            checks.append(CheckResult(self.source, rule.name, rule.category, rule.severity.value,
                                      rule.description, len(survivors), int(mask.sum())))

        reasons = self._collect(df.index, failures, Severity.ERROR)
        warnings = self._collect(df.index, failures, Severity.WARNING)
        rejected_mask = reasons != ""
        rejected = df.loc[rejected_mask].copy()
        rejected["rejection_reasons"] = reasons[rejected_mask]
        valid = df.loc[~rejected_mask].copy()

        log.info("[%s] Validation: %d checked, %d valid, %d rejected, %d flagged with warnings",
                 self.source, n, len(valid), len(rejected), int((warnings != "").sum()))
        for chk in checks:
            if chk.records_failed:
                log.log(30 if chk.status == "WARN" else 20, "[%s]   %-34s %-5s %d",
                        self.source, chk.check_name, chk.status, chk.records_failed)
        return ValidationResult(self.source, valid, rejected, reasons[rejected_mask],
                                warnings[warnings != ""], checks)

    def _collect(self, index: pd.Index, failures: dict[str, pd.Series], severity: Severity) -> pd.Series:
        out = pd.Series("", index=index, dtype="object")
        for rule in self.rules:
            if rule.severity != severity or rule.name not in failures:
                continue
            mask = failures[rule.name]
            out = pd.Series(np.where(mask, np.where(out == "", rule.name, out + "; " + rule.name), out),
                            index=index, dtype="object")
        return out
