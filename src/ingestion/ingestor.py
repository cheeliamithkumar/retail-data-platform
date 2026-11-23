"""Reusable CSV ingestion.

Responsibilities
----------------
* check the file exists and is not empty
* detect encoding and validate the header against the source contract
* stream rows in chunks (bounded memory), separating malformed lines
  (wrong number of fields) with their line numbers
* attach lineage metadata: source file, source line number, ingestion timestamp
* never type-cast here - everything is read as text; typing is a transformation concern
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pandas as pd

from src.config import INGEST_CHUNK_SIZE, SourceSpec
from src.utils.file_utils import detect_encoding, file_sha256
from src.utils.logger import get_logger

log = get_logger("ingestion")

META_COLUMNS = ["_source_file", "_source_line", "_ingested_at"]


class IngestionError(Exception):
    """Base class for ingestion failures."""


class SourceFileMissingError(IngestionError):
    pass


class SchemaValidationError(IngestionError):
    pass


@dataclass
class IngestionResult:
    source: str
    file_path: Path
    file_size_bytes: int
    checksum: str
    encoding: str
    ingested_at: datetime
    data: pd.DataFrame
    malformed: pd.DataFrame
    extra_columns: list[str] = field(default_factory=list)

    @property
    def rows_read(self) -> int:
        return len(self.data)

    @property
    def malformed_count(self) -> int:
        return len(self.malformed)

    @property
    def total_records(self) -> int:
        return self.rows_read + self.malformed_count


def _normalise(name: str) -> str:
    return " ".join(name.replace("﻿", "").strip().split()).lower()


class CSVIngestor:
    """Ingest a single CSV source described by a :class:`SourceSpec`."""

    def __init__(self, spec: SourceSpec, chunk_size: int = INGEST_CHUNK_SIZE):
        self.spec = spec
        self.chunk_size = chunk_size

    # ------------------------------------------------------------------ checks
    def check_file(self, path: Path) -> None:
        if not path.exists():
            raise SourceFileMissingError(f"Source file not found: {path}")
        if not path.is_file():
            raise SourceFileMissingError(f"Source path is not a file: {path}")
        if path.stat().st_size == 0:
            raise SchemaValidationError(f"Source file is empty: {path}")

    def validate_header(self, header: list[str]) -> tuple[list[str], list[str]]:
        """Return (canonical header, extra columns). Raises on missing columns."""
        lookup = {_normalise(c): c for c in self.spec.required_columns + self.spec.optional_columns}
        canonical: list[str] = []
        extras: list[str] = []
        for col in header:
            key = _normalise(col)
            if key in lookup:
                canonical.append(lookup[key])
            else:
                canonical.append(col.strip())
                extras.append(col.strip())
        missing = [c for c in self.spec.required_columns if c not in canonical]
        if missing:
            raise SchemaValidationError(
                f"{self.spec.filename}: missing required columns {missing}; found {header}"
            )
        duplicates = {c for c in canonical if canonical.count(c) > 1}
        if duplicates:
            raise SchemaValidationError(f"{self.spec.filename}: duplicate columns {sorted(duplicates)}")
        return canonical, extras

    # ------------------------------------------------------------------ reading
    def iter_chunks(self, path: Path, encoding: str) -> Iterator[tuple[list[str], list[list[str]], list[dict]]]:
        """Yield (header, good_rows_with_line_no, malformed) per chunk."""
        with open(path, newline="", encoding=encoding) as fh:
            reader = csv.reader(fh)
            try:
                raw_header = next(reader)
            except StopIteration as exc:
                raise SchemaValidationError(f"{path.name}: no header row") from exc
            header, _ = self.validate_header(raw_header)
            width = len(header)
            good: list[list[str]] = []
            bad: list[dict] = []
            while True:
                try:
                    row = next(reader)
                except StopIteration:
                    break
                except csv.Error as exc:  # e.g. NUL byte / unterminated quote
                    bad.append({"_source_line": reader.line_num, "raw_record": "",
                                "rejection_reasons": f"MALFORMED_CSV: {exc}"})
                    continue
                line_no = reader.line_num
                if not row or all(not c.strip() for c in row):
                    continue  # blank line: not a record
                if len(row) != width:
                    bad.append({
                        "_source_line": line_no,
                        "raw_record": ",".join(row),
                        "rejection_reasons": f"MALFORMED_RECORD: expected {width} fields, got {len(row)}",
                    })
                    continue
                good.append([*row, line_no])
                if len(good) >= self.chunk_size:
                    yield header, good, bad
                    good, bad = [], []
            yield header, good, bad

    def ingest(self, path: Path) -> IngestionResult:
        started = datetime.now()
        log.info("[%s] Ingesting %s", self.spec.name, path)
        self.check_file(path)
        encoding = detect_encoding(path)
        checksum = file_sha256(path)

        frames: list[pd.DataFrame] = []
        malformed: list[dict] = []
        header: list[str] = []
        for header, good, bad in self.iter_chunks(path, encoding):
            malformed.extend(bad)
            if good:
                frames.append(pd.DataFrame(good, columns=[*header, "_source_line"], dtype="object"))

        if frames:
            data = pd.concat(frames, ignore_index=True)
        else:
            data = pd.DataFrame(columns=[*header, "_source_line"], dtype="object")
        _, extras = self.validate_header(header)
        if extras:
            log.warning("[%s] Ignoring unexpected columns: %s", self.spec.name, extras)
            data = data.drop(columns=extras)

        data = data.rename(columns=self.spec.column_mapping)
        data["_source_line"] = data["_source_line"].astype("int64")
        data["_source_file"] = path.name
        data["_ingested_at"] = started

        bad_df = pd.DataFrame(malformed, columns=["_source_line", "raw_record", "rejection_reasons"])
        bad_df["_source_file"] = path.name
        bad_df["_ingested_at"] = started

        result = IngestionResult(
            source=self.spec.name, file_path=path, file_size_bytes=path.stat().st_size,
            checksum=checksum, encoding=encoding, ingested_at=started,
            data=data, malformed=bad_df, extra_columns=extras,
        )
        log.info("[%s] Read %d records (%d malformed) from %s [encoding=%s, sha256=%s...]",
                 self.spec.name, result.rows_read, result.malformed_count, path.name,
                 encoding, checksum[:12])
        return result
