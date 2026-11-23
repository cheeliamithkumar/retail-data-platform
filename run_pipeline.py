"""Single entry point for the retail ETL pipeline.

Examples::

    python run_pipeline.py                 # incremental run (new/changed files only)
    python run_pipeline.py --force         # reprocess files even if already loaded
    python run_pipeline.py --dry-run       # ingest + transform + validate, no database
    python run_pipeline.py --raw-dir path  # read source files from another folder
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config import RAW_DIR, DatabaseConfig
from src.pipeline import RetailPipeline
from src.utils.db import create_database_if_missing, get_engine
from src.utils.logger import get_logger, setup_logging


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retail sales ETL pipeline -> MySQL star schema")
    parser.add_argument("--force", action="store_true",
                        help="Reprocess source files even if identical content was already loaded")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run ingestion, transformation and validation only (no database)")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR, help="Directory containing source CSVs")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    setup_logging()
    log = get_logger("main")
    engine = None
    if not args.dry_run:
        try:
            cfg = DatabaseConfig.from_env()
            create_database_if_missing(cfg)
            engine = get_engine(cfg)
        except Exception as exc:  # noqa: BLE001
            log.error("Cannot connect to MySQL: %s", exc)
            log.error("Check .env settings, or use --dry-run to run without a database.")
            return 2
    try:
        outcome = RetailPipeline(engine=engine, raw_dir=args.raw_dir, force=args.force).run()
    finally:
        if engine is not None:
            engine.dispose()
    print(f"\nRun {outcome.run_id}: {outcome.status}")
    for key, value in outcome.totals.items():
        print(f"  {key:<20} {value:>8,}")
    if outcome.report_paths:
        print(f"  report: {outcome.report_paths[1]}")
    return 1 if outcome.status == "FAILED" else 0


if __name__ == "__main__":
    sys.exit(main())
