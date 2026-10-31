"""SQLite access for the Order API.

Connections run in autocommit mode (isolation_level=None) so transactions are
always explicit (BEGIN IMMEDIATE ... COMMIT) and visible in the code.
"""

import sqlite3
from pathlib import Path

from flask import g

import config

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

SEED_PRODUCTS = [
    # (id, name, price_cents, stock)
    (1, "Teclado mecánico", 4500, 5),
    (2, "Mouse inalámbrico (última unidad)", 2500, 1),
]


def connect(db_path=None):
    conn = sqlite3.connect(db_path or config.DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("BEGIN IMMEDIATE")
        _seed_products(conn)
        conn.execute("COMMIT")
    finally:
        conn.close()


def reset_db(conn):
    """Delete all orders/reservations and restore the seed stock."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM reservations")
        conn.execute("DELETE FROM orders")
        conn.execute("DELETE FROM products")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('orders', 'reservations')")
        _seed_products(conn)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _seed_products(conn):
    # INSERT OR IGNORE keeps existing stock and tolerates several workers starting at once.
    conn.executemany(
        "INSERT OR IGNORE INTO products (id, name, price_cents, stock) VALUES (?, ?, ?, ?)",
        SEED_PRODUCTS,
    )
