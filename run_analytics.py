"""Run every query in sql/analytics and save the results to reports/analytics/."""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from src.analytics.runner import run_all
from src.config import DatabaseConfig
from src.utils.db import get_engine
from src.utils.logger import setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    setup_logging()
    engine = get_engine(DatabaseConfig.from_env())
    try:
        results = run_all(engine)
    finally:
        engine.dispose()
    if not args.quiet:
        with pd.option_context("display.max_columns", 20, "display.width", 200,
                               "display.max_colwidth", 40):
            for name, df in results.items():
                print(f"\n=== {name} ===")
                print(df.head(15).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
