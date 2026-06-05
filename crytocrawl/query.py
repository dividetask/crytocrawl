"""Read-only query helpers, usable from Python or via the CLI."""

from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional

SATS_PER_BTC = 100_000_000


def _row_to_dict(row: sqlite3.Row) -> Dict:
    sat = row["balance_sat"]
    return {
        "address": row["address"],
        "balance_sat": sat,
        "balance_btc": sat / SATS_PER_BTC,
        "tx_count": row["tx_count"],
        "balance_updated_at": row["balance_updated_at"],
        "tx_count_updated_at": row["tx_count_updated_at"],
    }


def get_address(conn: sqlite3.Connection, address: str) -> Optional[Dict]:
    """Return a dict for one address, or None if it isn't stored."""
    row = conn.execute(
        "SELECT * FROM addresses WHERE address = ?", (address,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def top_addresses(conn: sqlite3.Connection, n: int = 20) -> List[Dict]:
    """The ``n`` richest addresses by current balance."""
    rows = conn.execute(
        "SELECT * FROM addresses ORDER BY balance_sat DESC LIMIT ?", (n,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def search_addresses(conn: sqlite3.Connection, prefix: str, limit: int = 20) -> List[Dict]:
    """Addresses starting with ``prefix`` (uses the PK index)."""
    rows = conn.execute(
        "SELECT * FROM addresses WHERE address >= ? AND address < ? "
        "ORDER BY address LIMIT ?",
        (prefix, prefix + "￿", limit),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_addresses(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS c FROM addresses").fetchone()["c"]


def stats(conn: sqlite3.Connection) -> Dict:
    """Aggregate statistics over the whole table."""
    row = conn.execute(
        "SELECT COUNT(*) AS n, "
        "       COALESCE(SUM(balance_sat), 0) AS total_sat, "
        "       COUNT(tx_count) AS enriched, "
        "       MAX(balance_sat) AS max_sat "
        "FROM addresses"
    ).fetchone()
    from .db import get_meta

    return {
        "addresses": row["n"],
        "total_balance_sat": row["total_sat"],
        "total_balance_btc": row["total_sat"] / SATS_PER_BTC,
        "enriched_with_tx_count": row["enriched"],
        "max_balance_btc": (row["max_sat"] or 0) / SATS_PER_BTC,
        "dump_date": get_meta(conn, "dump_date"),
        "dump_source": get_meta(conn, "dump_source"),
        "last_ingest_at": get_meta(conn, "last_ingest_at"),
    }
