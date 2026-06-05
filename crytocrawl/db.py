"""SQLite storage layer for crytocrawl.

We store balances in **satoshis** as an INTEGER (exact), and only convert to a
BTC float at display/query time. Storing the float directly would lose
precision (a satoshi is 1e-8 BTC and floats cannot represent every value
exactly), so the integer is the source of truth.

Schema
------
addresses
    address              TEXT  PRIMARY KEY  -- the bitcoin address
    balance_sat          INTEGER NOT NULL   -- current balance in satoshis
    tx_count             INTEGER            -- # txs (in+out); NULL until enriched
    balance_updated_at   TEXT               -- ISO-8601 UTC of last balance write
    tx_count_updated_at  TEXT               -- ISO-8601 UTC of last tx_count write

meta
    key   TEXT PRIMARY KEY
    value TEXT
        -- bookkeeping, e.g. dump_date, dump_source, last_ingest_at
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
    tx_count            INTEGER,
    balance_updated_at  TEXT,
    tx_count_updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_addresses_balance_sat
    ON addresses (balance_sat DESC);

CREATE INDEX IF NOT EXISTS idx_addresses_tx_count_null
    ON addresses (address) WHERE tx_count IS NULL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def open_db(path: str = DEFAULT_DB_PATH, *, fast: bool = False) -> sqlite3.Connection:
    """Open (and create if needed) the database and ensure the schema exists.

    Set ``fast=True`` during bulk ingest to trade durability for speed.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if fast:
        # These make bulk loads dramatically faster. They are safe for an
        # ingest job: if the process dies you simply re-run the ingest.
        conn.execute("PRAGMA journal_mode = MEMORY")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -262144")  # ~256 MB page cache
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
