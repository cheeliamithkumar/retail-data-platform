"""Execute the analytical SQL library and export each result set to CSV."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy.engine import Engine

from src.config import REPORT_DIR, SQL_DIR
from src.utils.db import split_sql_statements
from src.utils.logger import get_logger

log = get_logger("analytics")
ANALYTICS_DIR = SQL_DIR / "analytics"


def list_queries(directory: Path = ANALYTICS_DIR) -> list[Path]:
    return sorted(directory.glob("*.sql"))


def run_query(engine: Engine, path: Path) -> pd.DataFrame:
    statements = split_sql_statements(path.read_text(encoding="utf-8"))
    if len(statements) != 1:
        raise ValueError(f"{path.name}: expected exactly one statement, found {len(statements)}")
    with engine.connect() as conn:
        result = conn.exec_driver_sql(statements[0].replace("%", "%%"))
        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))


def run_all(engine: Engine, output_dir: Path = REPORT_DIR / "analytics") -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, pd.DataFrame] = {}
    for path in list_queries():
        df = run_query(engine, path)
        df.to_csv(output_dir / f"{path.stem}.csv", index=False)
        results[path.stem] = df
        log.info("%-36s %4d rows -> %s", path.name, len(df), output_dir / f"{path.stem}.csv")
    return results
