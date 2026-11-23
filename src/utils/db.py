"""Database helpers: engine creation and execution of SQL script files."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, URL

from src.config import DatabaseConfig
from src.utils.logger import get_logger

log = get_logger("db")


def build_url(cfg: DatabaseConfig, include_database: bool = True) -> URL:
    return URL.create(
        drivername="mysql+pymysql",
        username=cfg.user,
        password=cfg.password,
        host=cfg.host,
        port=cfg.port,
        database=cfg.database if include_database else None,
        query={"charset": "utf8mb4"},
    )


def get_engine(cfg: DatabaseConfig, include_database: bool = True) -> Engine:
    # pool_pre_ping avoids "MySQL server has gone away" on long-idle connections.
    return create_engine(build_url(cfg, include_database), pool_pre_ping=True, future=True)


def create_database_if_missing(cfg: DatabaseConfig) -> None:
    if not cfg.database.replace("_", "").isalnum():
        raise ValueError(f"Unsafe database name: {cfg.database!r}")
    engine = get_engine(cfg, include_database=False)
    with engine.begin() as conn:
        conn.execute(text(
            f"CREATE DATABASE IF NOT EXISTS `{cfg.database}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        ))
    engine.dispose()


def split_sql_statements(sql: str) -> list[str]:
    """Split a script on ``;`` while respecting quotes and ``--``/``#``/``/* */`` comments."""
    statements: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    quote: str | None = None
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if quote:
            buf.append(ch)
            if ch == "\\" and quote != "`":
                buf.append(nxt)
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
        elif (ch == "-" and nxt == "-") or ch == "#":
            end = sql.find("\n", i)
            i = n if end == -1 else end
            continue
        elif ch == "/" and nxt == "*":
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def run_sql_file(conn: Connection, path: Path) -> list[int]:
    """Execute every statement in a SQL file on an open connection.

    Returns the affected row count of each statement.
    """
    sql = path.read_text(encoding="utf-8")
    counts: list[int] = []
    for stmt in split_sql_statements(sql):
        # exec_driver_sql: no SQLAlchemy bind-parameter parsing (":" in SQL is safe).
        # PyMySQL still applies %-formatting, so literal % (DATE_FORMAT) must be doubled.
        result = conn.exec_driver_sql(stmt.replace("%", "%%"))
        counts.append(result.rowcount if result.rowcount is not None else 0)
    log.debug("Executed %s (%d statements)", path.name, len(counts))
    return counts


def run_sql_files(conn: Connection, paths: Iterable[Path]) -> None:
    for path in paths:
        log.info("Running SQL script %s", path.relative_to(path.parents[2]))
        run_sql_file(conn, path)
