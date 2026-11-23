"""Shared test fixtures.

Tests marked `db` need MySQL and use the DB_TEST_NAME database, which gets
dropped and recreated for each test. They're skipped if MySQL isn't reachable."""
from __future__ import annotations

import csv
import os
from datetime import date
from pathlib import Path

import pytest

from src.config import ORDERS_SPEC, PEOPLE_SPEC, RETURNS_SPEC

ORDER_HEADER = list(ORDERS_SPEC.required_columns)
TODAY = date(2026, 11, 23)


def order_row(row_id: int, **overrides) -> dict:
    base = {
        "Row ID": str(row_id), "Order ID": f"CA-2018-{100000 + row_id}",
        "Order Date": "3/15/2018", "Ship Date": "3/19/2018", "Ship Mode": "Standard Class",
        "Customer ID": "CG-12520", "Customer Name": "Claire Gute", "Segment": "Consumer",
        "Country": "United States", "City": "Henderson", "State": "Kentucky",
        "Postal Code": "42420", "Region": "South", "Product ID": "FUR-BO-10001798",
        "Category": "Furniture", "Sub-Category": "Bookcases",
        "Product Name": "Bush Somerset Collection Bookcase",
        "Sales": "261.96", "Quantity": "2", "Discount": "0", "Profit": "41.9136",
    }
    base.update({k: str(v) for k, v in overrides.items()})
    return base


def write_csv(path: Path, header: list[str], rows: list[dict], encoding: str = "utf-8") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding=encoding) as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_sources(raw_dir: Path, orders: list[dict], returns: list[dict] | None = None,
                  people: list[dict] | None = None) -> Path:
    write_csv(raw_dir / ORDERS_SPEC.filename, ORDER_HEADER, orders)
    if returns is not None:
        write_csv(raw_dir / RETURNS_SPEC.filename, ["Returned", "Order ID"], returns)
    if people is not None:
        write_csv(raw_dir / PEOPLE_SPEC.filename, ["Person", "Region"], people)
    return raw_dir


DEFAULT_PEOPLE = [
    {"Person": "Anna Andreadi", "Region": "West"}, {"Person": "Chuck Magee", "Region": "East"},
    {"Person": "Kelly Williams", "Region": "Central"}, {"Person": "Cassandra Brandow", "Region": "South"},
]


def sample_orders() -> list[dict]:
    """6 valid lines over 3 orders, 2 customers, 3 regions."""
    return [
        order_row(1),
        order_row(2, **{"Order ID": "CA-2018-100001", "Product ID": "OFF-PA-10000174",
                        "Category": "Office Supplies", "Sub-Category": "Paper",
                        "Product Name": "Message Book", "Sales": "16.448", "Quantity": "2",
                        "Discount": "0.2", "Profit": "5.5512"}),
        order_row(3, **{"Order ID": "US-2017-200003", "Order Date": "11/22/2017",
                        "Ship Date": "11/26/2017", "Customer ID": "DV-13045",
                        "Customer Name": "Darrin Van Huff", "Segment": "Corporate",
                        "City": "Los Angeles", "State": "California", "Postal Code": "90036",
                        "Region": "West", "Sales": "14.62", "Profit": "6.8714"}),
        order_row(4, **{"Order ID": "US-2017-200003", "Order Date": "11/22/2017",
                        "Ship Date": "11/26/2017", "Customer ID": "DV-13045",
                        "Customer Name": "Darrin Van Huff", "Segment": "Corporate",
                        "City": "Los Angeles", "State": "California", "Postal Code": "90036",
                        "Region": "West", "Product ID": "TEC-PH-10002033",
                        "Category": "Technology", "Sub-Category": "Phones",
                        "Product Name": "Konftel 250 Conference phone", "Sales": "911.424",
                        "Quantity": "4", "Discount": "0.2", "Profit": "68.3568"}),
        order_row(5, **{"Order ID": "CA-2016-300005", "Order Date": "2016-06-12",
                        "Ship Date": "2016-06-16", "City": "Burlington", "State": "Vermont",
                        "Postal Code": "5401", "Region": "East", "Sales": "48.86",
                        "Quantity": "7", "Profit": "14.1694"}),
        order_row(6, **{"Order ID": "CA-2016-300005", "Order Date": "2016-06-12",
                        "Ship Date": "2016-06-16", "City": "Burlington", "State": "Vermont",
                        "Postal Code": "5401", "Region": "East", "Product ID": "OFF-AR-10002833",
                        "Category": "Office Supplies", "Sub-Category": "Art",
                        "Product Name": "Newell 322", "Sales": "7.28", "Quantity": "4",
                        "Profit": "1.9656"}),
    ]


def _test_db_config():
    from src.config import DatabaseConfig
    return DatabaseConfig.from_env(database=os.getenv("DB_TEST_NAME", "retail_dw_test"))


@pytest.fixture(scope="session")
def db_available() -> bool:
    try:
        from sqlalchemy import text

        from src.utils.db import get_engine
        engine = get_engine(_test_db_config(), include_database=False)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture()
def db_engine(db_available):
    """Fresh, empty test database with the full schema deployed."""
    if not db_available:
        pytest.skip("MySQL test database not reachable (configure .env to run db tests)")
    from src.loading import WarehouseLoader
    from src.utils.db import create_database_if_missing, get_engine

    cfg = _test_db_config()
    assert cfg.database.endswith("_test"), "Refusing to run DB tests against a non-test database"
    server = get_engine(cfg, include_database=False)
    with server.begin() as conn:
        conn.exec_driver_sql(f"DROP DATABASE IF EXISTS `{cfg.database}`")
    server.dispose()
    create_database_if_missing(cfg)
    engine = get_engine(cfg)
    WarehouseLoader(engine).ensure_schema()
    yield engine
    engine.dispose()


@pytest.fixture()
def dirs(tmp_path):
    d = {name: tmp_path / name for name in ("raw", "processed", "rejected", "reports")}
    for p in d.values():
        p.mkdir()
    return d
