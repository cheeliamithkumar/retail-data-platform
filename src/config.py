"""Central configuration: paths, database settings and source-file contracts.

Credentials are read from environment variables (optionally loaded from a local,
git-ignored ``.env`` file). Nothing secret is ever hard-coded here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
REJECTED_DIR = DATA_DIR / "rejected"
LOG_DIR = PROJECT_ROOT / "logs"
REPORT_DIR = PROJECT_ROOT / "reports"
SQL_DIR = PROJECT_ROOT / "sql"


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_env(cls, database: str | None = None) -> "DatabaseConfig":
        missing = [v for v in ("DB_USER", "DB_PASSWORD") if not os.getenv(v)]
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Copy .env.example to .env and fill in your MySQL credentials."
            )
        return cls(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=database or os.getenv("DB_NAME", "retail_dw"),
        )

    def __repr__(self) -> str:  # never leak the password into logs
        return (f"DatabaseConfig(host={self.host!r}, port={self.port}, "
                f"user={self.user!r}, password='***', database={self.database!r})")


@dataclass(frozen=True)
class SourceSpec:
    """Contract for one raw CSV source file."""

    name: str
    filename: str
    required_columns: tuple[str, ...]
    column_mapping: dict[str, str]
    required: bool = True
    optional_columns: tuple[str, ...] = field(default_factory=tuple)


ORDERS_SPEC = SourceSpec(
    name="orders",
    filename="superstore_orders.csv",
    required_columns=(
        "Row ID", "Order ID", "Order Date", "Ship Date", "Ship Mode", "Customer ID",
        "Customer Name", "Segment", "Country", "City", "State", "Postal Code",
        "Region", "Product ID", "Category", "Sub-Category", "Product Name",
        "Sales", "Quantity", "Discount", "Profit",
    ),
    column_mapping={
        "Row ID": "row_id", "Order ID": "order_id", "Order Date": "order_date",
        "Ship Date": "ship_date", "Ship Mode": "ship_mode", "Customer ID": "customer_id",
        "Customer Name": "customer_name", "Segment": "segment", "Country": "country",
        "City": "city", "State": "state", "Postal Code": "postal_code", "Region": "region",
        "Product ID": "product_id", "Category": "category", "Sub-Category": "sub_category",
        "Product Name": "product_name", "Sales": "sales", "Quantity": "quantity",
        "Discount": "discount", "Profit": "profit",
    },
    required=True,
)

RETURNS_SPEC = SourceSpec(
    name="returns",
    filename="superstore_returns.csv",
    required_columns=("Returned", "Order ID"),
    column_mapping={"Returned": "returned", "Order ID": "order_id"},
    required=False,
)

PEOPLE_SPEC = SourceSpec(
    name="people",
    filename="superstore_people.csv",
    required_columns=("Person", "Region"),
    column_mapping={"Person": "regional_manager", "Region": "region"},
    required=False,
)

SOURCE_SPECS: tuple[SourceSpec, ...] = (PEOPLE_SPEC, ORDERS_SPEC, RETURNS_SPEC)

# Date formats accepted from source systems, tried in order.
ACCEPTED_DATE_FORMATS: tuple[str, ...] = (
    "%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%Y/%m/%d", "%d %b %Y", "%d-%b-%Y",
)

INGEST_CHUNK_SIZE = int(os.getenv("INGEST_CHUNK_SIZE", "5000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
