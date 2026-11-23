"""Make a small SYNTHETIC batch for testing incremental loads and rejections.

The rows are made up (built from real rows with a fixed seed) and are written to
data/demo_increment/ so the real files in data/raw are never touched. The batch has
~200 new January 2019 order lines, one corrected existing line, one unchanged
re-sent line, a couple of duplicates, one bad record per validation rule, a broken
CSV line and an orphan return.

    python scripts/generate_demo_increment.py
    python run_pipeline.py --raw-dir data/demo_increment
"""
from __future__ import annotations

import argparse
import csv
import random
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUT_DIR = PROJECT_ROOT / "data" / "demo_increment"
SEED = 20190101

# (description, mutation applied to a copy of a valid new row)
DEFECTS = [
    ("negative quantity",       lambda r: r.update({"Quantity": "-3"})),
    ("zero sales",              lambda r: r.update({"Sales": "0"})),
    ("non-numeric sales",       lambda r: r.update({"Sales": "12,34x"})),
    ("unparseable order date",  lambda r: r.update({"Order Date": "31/31/2019"})),
    ("future order date",       lambda r: r.update({"Order Date": "1/15/2099", "Ship Date": "1/20/2099"})),
    ("ship before order",       lambda r: r.update({"Ship Date": "12/1/2018"})),
    ("missing customer id",     lambda r: r.update({"Customer ID": ""})),
    ("discount of 150%",        lambda r: r.update({"Discount": "1.5"})),
    ("profit exceeds sales",    lambda r: r.update({"Profit": str(float(r["Sales"]) * 2)})),
    ("unknown region",          lambda r: r.update({"Region": "Atlantis"})),
]


def read_rows(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--new", type=int, default=200, help="Number of new valid order lines")
    args = parser.parse_args()

    src = RAW_DIR / "superstore_orders.csv"
    if not src.exists():
        print("Run scripts/download_dataset.py first.")
        return 1
    rng = random.Random(SEED)
    header, rows = read_rows(src)
    max_row_id = max(int(r["Row ID"]) for r in rows)

    out: list[dict] = []
    next_row_id = max_row_id + 1
    new_orders: list[str] = []
    templates = rng.sample(rows, args.new)
    for i, tpl in enumerate(templates):
        if i % 2 == 0 or not new_orders:  # ~2 lines per order
            order_id = f"US-2019-{900000 + len(new_orders):06d}"
            new_orders.append(order_id)
            day = rng.randint(1, 28)
            ship = min(day + rng.randint(0, 6), 31)
        row = dict(tpl)
        row.update({"Row ID": str(next_row_id), "Order ID": order_id,
                    "Order Date": f"1/{day}/2019", "Ship Date": f"1/{ship}/2019"})
        out.append(row)
        next_row_id += 1

    # Correction of an existing line and an unchanged re-send
    corrected = dict(next(r for r in rows if r["Row ID"] == "1"))
    unit = float(corrected["Sales"]) / int(corrected["Quantity"])
    corrected["Quantity"] = str(int(corrected["Quantity"]) + 1)
    corrected["Sales"] = f"{unit * int(corrected['Quantity']):.2f}"
    out.append(corrected)
    out.append(dict(next(r for r in rows if r["Row ID"] == "2")))

    # Exact duplicate of a new line (re-sent record)
    out.append(dict(out[0]))
    # Duplicate transaction under a different Row ID
    dup_tx = dict(out[1])
    dup_tx["Row ID"] = str(next_row_id)
    next_row_id += 1
    out.append(dup_tx)

    # One defective record per rule
    for _, mutate in DEFECTS:
        row = dict(rng.choice(out[: args.new]))
        row["Row ID"] = str(next_row_id)
        next_row_id += 1
        mutate(row)
        out.append(row)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    orders_path = OUT_DIR / "superstore_orders.csv"
    with open(orders_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        writer.writerows(out)
        # A malformed line (too few fields) appended raw
        fh.write("99999,US-2019-BROKEN,1/5/2019,1/7/2019,Standard Class\n")

    returns_path = OUT_DIR / "superstore_returns.csv"
    with open(returns_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Returned", "Order ID"])
        for oid in rng.sample(new_orders, 5):
            w.writerow(["Yes", oid])
        w.writerow(["Yes", "US-2019-NOT-AN-ORDER"])  # orphan return

    shutil.copy(RAW_DIR / "superstore_people.csv", OUT_DIR / "superstore_people.csv")
    print(f"SYNTHETIC demo increment written to {OUT_DIR.relative_to(PROJECT_ROOT)}/")
    print(f"  orders : {len(out) + 1} records ({args.new} new valid, 1 corrected, 1 unchanged, "
          f"2 duplicates, {len(DEFECTS)} defective, 1 malformed line)")
    print("  returns: 6 records (5 valid, 1 orphan)")
    print("  people : copied unchanged (will be skipped as already loaded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
