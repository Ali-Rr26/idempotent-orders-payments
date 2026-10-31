"""Runs docs/evidencia.sql against both databases and prints each result as a table.

Usage:
    python docs/evidencia.py                       # auto-detects Docker or local databases
    python docs/evidencia.py --orders PATH --payments PATH
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL_PATH = Path(__file__).resolve().parent / "evidencia.sql"

CANDIDATES = [
    ("Docker", ROOT / "data/order/orders.db", ROOT / "data/payment/payments.db"),
    ("local", ROOT / "order_api/orders.db", ROOT / "payment_mock_api/payments.db"),
]


def parse_queries(text):
    """Split the file into (title, sql) pairs using the '-- name:' markers."""
    queries = []
    for block in re.split(r"^-- name:", text, flags=re.MULTILINE)[1:]:
        title, _, body = block.partition("\n")
        sql = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("--"))
        queries.append((title.strip(), sql.strip().rstrip(";")))
    return queries


def print_table(cursor, rows):
    headers = [col[0] for col in cursor.description]
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(headers)]
    line = "+".join("-" * (w + 2) for w in widths)
    print("+" + line + "+")
    print("| " + " | ".join(h.ljust(w) for h, w in zip(headers, widths)) + " |")
    print("+" + line + "+")
    for row in cells:
        print("| " + " | ".join(v.ljust(w) for v, w in zip(row, widths)) + " |")
    print("+" + line + "+")
    print(f"({len(rows)} fila{'s' if len(rows) != 1 else ''})")


def resolve_paths(args):
    if args.orders and args.payments:
        return Path(args.orders), Path(args.payments)
    for label, orders, payments in CANDIDATES:
        if orders.exists() and payments.exists():
            print(f"Usando bases {label}: {orders.relative_to(ROOT)} y {payments.relative_to(ROOT)}\n")
            return orders, payments
    sys.exit("No se encontraron las bases. Levanta los servicios o indica --orders y --payments.")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--orders", help="ruta de orders.db")
    parser.add_argument("--payments", help="ruta de payments.db")
    orders_path, payments_path = resolve_paths(parser.parse_args())

    # Read-only: the evidence must never change the data it inspects.
    conn = sqlite3.connect(f"{orders_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.execute("ATTACH DATABASE ? AS pay", (f"{payments_path.resolve().as_uri()}?mode=ro",))

    for title, sql in parse_queries(SQL_PATH.read_text(encoding="utf-8")):
        print(f"== {title}")
        cursor = conn.execute(sql)
        print_table(cursor, cursor.fetchall())
        print()


if __name__ == "__main__":
    main()
