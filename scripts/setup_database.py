"""Create the warehouse database (if missing) and deploy all DDL from sql/schema.

Usage::

    python scripts/setup_database.py            # database from DB_NAME in .env
    python scripts/setup_database.py --test     # database from DB_TEST_NAME
    python scripts/setup_database.py --reset --yes   # DROP and recreate (destroys all data)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import DatabaseConfig  # noqa: E402
from src.loading import WarehouseLoader  # noqa: E402
from src.utils.db import create_database_if_missing, get_engine  # noqa: E402
from src.utils.logger import setup_logging  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy the retail data warehouse schema")
    parser.add_argument("--test", action="store_true", help="Target the test database (DB_TEST_NAME)")
    parser.add_argument("--reset", action="store_true", help="Drop the database first (destroys all data)")
    parser.add_argument("--yes", action="store_true", help="Confirm --reset without prompting")
    args = parser.parse_args()
    setup_logging()
    name = os.getenv("DB_TEST_NAME", "retail_dw_test") if args.test else None
    cfg = DatabaseConfig.from_env(database=name)
    if args.reset:
        if not cfg.database.replace("_", "").isalnum():
            raise ValueError(f"Unsafe database name: {cfg.database!r}")
        if not args.yes and input(f"Drop database '{cfg.database}' and ALL its data? [y/N] ").lower() != "y":
            print("Aborted.")
            return 1
        server = get_engine(cfg, include_database=False)
        with server.begin() as conn:
            conn.exec_driver_sql(f"DROP DATABASE IF EXISTS `{cfg.database}`")
        server.dispose()
        print(f"Dropped database '{cfg.database}'.")
    create_database_if_missing(cfg)
    engine = get_engine(cfg)
    WarehouseLoader(engine).ensure_schema()
    with engine.connect() as conn:
        tables = [r[0] for r in conn.exec_driver_sql("SHOW FULL TABLES")]
    engine.dispose()
    print(f"Database '{cfg.database}' ready with {len(tables)} tables/views:")
    for t in sorted(tables):
        print(f"  - {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
