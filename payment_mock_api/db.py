"""SQLite access for the Payment Mock API.

Connections run in autocommit mode (isolation_level=None) so transactions are
always explicit (BEGIN IMMEDIATE ... COMMIT) and visible in the code.
"""

import sqlite3
from pathlib import Path

from flask import g

import config

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


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
    finally:
        conn.close()


def reset_db(conn):
    """Delete every recorded payment."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM payments")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'payments'")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
