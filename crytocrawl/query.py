"""Read-only query helpers, usable from Python or via the CLI.

Reminder: a row existing in ``addresses`` means the address has *ever held a
balance*. ``balance_sat`` is its *current* balance (0 if spent out).
"""

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
        "balance_updated_at": row["balance_updated_at"],
    }


def get_address(conn: sqlite3.Connection, address: str) -> Optional[Dict]:
    """Return a dict for one address, or None if it never held a balance."""
    row = conn.execute(
        "SELECT * FROM addresses WHERE address = ?", (address,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def ever_held(conn: sqlite3.Connection, address: str) -> bool:
    """True iff the address has ever held a balance (i.e. is stored)."""
    return conn.execute(
        "SELECT 1 FROM addresses WHERE address = ? LIMIT 1", (address,)
    ).fetchone() is not None


def top_addresses(conn: sqlite3.Connection, n: int = 20) -> List[Dict]:
    """The ``n`` richest addresses by current balance."""
    rows = conn.execute(
        "SELECT * FROM addresses ORDER BY balance_sat DESC LIMIT ?", (n,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def search_addresses(conn: sqlite3.Connection, prefix: str, limit: int = 20) -> List[Dict]:
    """Addresses starting with ``prefix`` (uses the primary-key index)."""
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
        "       SUM(CASE WHEN balance_sat > 0 THEN 1 ELSE 0 END) AS funded, "
        "       MAX(balance_sat) AS max_sat "
        "FROM addresses"
    ).fetchone()
    from .db import get_meta

    return {
        "addresses_ever_held": row["n"],
        "currently_funded": row["funded"] or 0,
        "total_balance_sat": row["total_sat"],
        "total_balance_btc": row["total_sat"] / SATS_PER_BTC,
        "max_balance_btc": (row["max_sat"] or 0) / SATS_PER_BTC,
        "outputs_through": get_meta(conn, "outputs_through"),
        "balances_dump_date": get_meta(conn, "balances_dump_date"),
        "last_outputs_ingest_at": get_meta(conn, "last_outputs_ingest_at"),
        "last_balances_ingest_at": get_meta(conn, "last_balances_ingest_at"),
    }
