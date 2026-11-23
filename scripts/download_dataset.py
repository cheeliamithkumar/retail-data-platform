"""Download the public "Sample - Superstore" retail dataset and split it into raw sources.

Source
------
Tableau's "Sample - Superstore" dataset (US retail orders 2015-2018), as mirrored at
https://github.com/leonism/sample-superstore (``data/superstore.csv``).

The mirrored CSV is an export of the original Excel workbook with its three sheets
concatenated one after another:

* ``Orders``  - 9,994 order lines (header starts with ``Row ID``)
* ``People``  - regional managers  (header ``Person,Region``)
* ``Returns`` - returned orders    (header ``Returned,Order ID``)

This script splits them into three CSV files in ``data/raw`` so each can be ingested
as an independent source, mirroring how separate source-system extracts arrive.

Usage::

    python scripts/download_dataset.py            # download + split
    python scripts/download_dataset.py --file x   # split an already-downloaded file
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"

DATASET_URL = "https://raw.githubusercontent.com/leonism/sample-superstore/master/data/superstore.csv"
# SHA-256 of the file as downloaded on 2026-11-23; a mismatch is reported, not fatal.
KNOWN_SHA256 = "af443ca30d732c886f7a1d603f9492f98e9a88c268d47cbc146fe758b1f5d65d"

SECTIONS = {
    "Row ID": "superstore_orders.csv",
    "Person": "superstore_people.csv",
    "Returned": "superstore_returns.csv",
}


def download(url: str) -> bytes:
    print(f"Downloading {url} ...")
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 (fixed https URL)
        return resp.read()


def split_sections(content: str) -> dict[str, list[list[str]]]:
    """Split the concatenated CSV on known header rows."""
    sections: dict[str, list[list[str]]] = {}
    current: str | None = None
    for row in csv.reader(io.StringIO(content)):
        if not row or all(not c.strip() for c in row):
            continue
        first = row[0].strip().lstrip("﻿")
        if first in SECTIONS and (current is None or first != current):
            # A header row only counts if it differs from the current section.
            if first not in sections:
                current = first
                sections[current] = [[c.strip().lstrip("﻿") for c in row if c.strip()]]
                continue
        if current is None:
            raise ValueError("File does not start with a recognised header row")
        header_len = len(sections[current][0])
        # Trim trailing empty cells produced by the sheet concatenation.
        while len(row) > header_len and row[-1] == "":
            row = row[:-1]
        sections[current].append(row)
    return sections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, help="Use a local copy instead of downloading")
    parser.add_argument("--url", default=DATASET_URL)
    args = parser.parse_args()

    raw = args.file.read_bytes() if args.file else download(args.url)
    digest = hashlib.sha256(raw).hexdigest()
    print(f"SHA-256: {digest}")
    if digest != KNOWN_SHA256:
        print("WARNING: checksum differs from the version this project was built against.")

    sections = split_sections(raw.decode("utf-8-sig"))
    missing = [h for h in SECTIONS if h not in sections]
    if missing:
        print(f"ERROR: sections not found: {missing}")
        return 1

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for header, filename in SECTIONS.items():
        rows = sections[header]
        out = RAW_DIR / filename
        with open(out, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
        print(f"Wrote {out.relative_to(PROJECT_ROOT)}: {len(rows) - 1:,} data rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
