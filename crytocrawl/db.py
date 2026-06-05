"""SQLite storage layer for crytocrawl.

Data model
----------
Every address that has **ever held a balance** (i.e. was ever the recipient of
a transaction output carrying value) gets a row. Presence of a row *is* the
"ever held a balance" fact. ``balance_sat`` is the address's **current**
balance in satoshis (0 if it received coins in the past but has since spent
them all).

Balances are stored in satoshis as an INTEGER (exact); BTC floats are derived
only at query time so no precision is lost.

Schema
------
addresses
    address             TEXT  PRIMARY KEY  -- the bitcoin address
    balance_sat         INTEGER NOT NULL   -- current balance in satoshis (0 = spent out)
    balance_updated_at  TEXT               -- ISO-8601 UTC of last balance write

meta
    key   TEXT PRIMARY KEY
    value TEXT                            -- bookkeeping (dump dates, progress, ...)
"""

from __future__ import annotations

import os
import sqlite3
from typing import Optional

DEFAULT_DB_PATH = os.environ.get("CRYTOCRAWL_DB", "bitcoin.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS addresses (
    address             TEXT PRIMARY KEY,
    balance_sat         INTEGER NOT NULL DEFAULT 0,
    balance_updated_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_addresses_balance_sat
    ON addresses (balance_sat DESC);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Records which dump files have already been aggregated, so a multi-day
-- ingest of the full history can be stopped and resumed safely.
CREATE TABLE IF NOT EXISTS ingested_files (
    name         TEXT PRIMARY KEY,
    rows         INTEGER,
    ingested_at  TEXT
);
"""


def open_db(path: str = DEFAULT_DB_PATH, *, fast: bool = False) -> sqlite3.Connection:
    """Open (creating if needed) the database and ensure the schema exists.

    Set ``fast=True`` for bulk ingest to trade durability for speed (safe: if
    the process dies mid-ingest you simply re-run it).
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    if fast:
        conn.execute("PRAGMA journal_mode = MEMORY")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -1048576")  # ~1 GB page cache
    else:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables/indexes if they do not already exist."""
    conn.executescript(SCHEMA)
    conn.commit()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None
