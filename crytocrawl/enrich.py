"""Per-address enrichment of transaction counts (and fresh balances).

The Blockchair bulk dump gives balances but no transaction counts. This module
fills in ``tx_count`` (and refreshes ``balance_sat``) for individual addresses
on demand, using the mempool.space REST API:

    GET https://mempool.space/api/address/<address>

which returns::

    {
      "chain_stats":   {"funded_txo_sum": .., "spent_txo_sum": .., "tx_count": ..},
      "mempool_stats": {"funded_txo_sum": .., "spent_txo_sum": .., "tx_count": ..}
    }

balance  = (funded_txo_sum - spent_txo_sum)            [confirmed only]
tx_count = chain_stats.tx_count + mempool_stats.tx_count

This is rate-limited by the public API, so enrichment is meant for the
addresses you actually care about, not the whole dataset (there is no feasible
way to get tx counts for *every* address without running your own node).
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional

API_BASE = "https://mempool.space/api"
_USER_AGENT = "crytocrawl/0.1 (+https://github.com/dividetask/crytocrawl)"

# A fetcher takes an address and returns {"balance_sat": int, "tx_count": int}.
Fetcher = Callable[[str], Dict[str, int]]


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def fetch_address_stats(address: str, *, api_base: str = API_BASE, timeout: float = 20.0) -> Dict[str, int]:
    """Fetch live balance + tx_count for one address from mempool.space."""
    url = f"{api_base}/address/{address}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8"))
    chain = data.get("chain_stats", {}) or {}
    mem = data.get("mempool_stats", {}) or {}
    balance_sat = int(chain.get("funded_txo_sum", 0)) - int(chain.get("spent_txo_sum", 0))
    tx_count = int(chain.get("tx_count", 0)) + int(mem.get("tx_count", 0))
    return {"balance_sat": balance_sat, "tx_count": tx_count}


def _fetch_with_retry(fetcher: Fetcher, address: str, *, retries: int = 4) -> Optional[Dict[str, int]]:
    delay = 2.0
    for attempt in range(retries):
        try:
            return fetcher(address)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:  # rate limited
                time.sleep(delay)
                delay *= 2
                continue
            if e.code == 400:  # malformed/unknown address — don't retry
                return None
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    return None


def enrich_addresses(
    conn: sqlite3.Connection,
    addresses: List[str],
    *,
    fetcher: Fetcher = fetch_address_stats,
    sleep: float = 0.0,
    upsert: bool = True,
) -> int:
    """Enrich the given addresses, writing balance_sat + tx_count.

    Rows that don't exist yet are inserted when ``upsert`` is True (handy for
    a watchlist of addresses not present in the bulk dump). Returns the number
    of addresses successfully updated.
    """
    updated = 0
    for addr in addresses:
        stats = _fetch_with_retry(fetcher, addr)
        if stats is None:
            continue
        now = _utcnow()
        if upsert:
            conn.execute(
                "INSERT INTO addresses(address, balance_sat, tx_count, "
                "  balance_updated_at, tx_count_updated_at) "
                "VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(address) DO UPDATE SET "
                "  balance_sat = excluded.balance_sat, "
                "  tx_count = excluded.tx_count, "
                "  balance_updated_at = excluded.balance_updated_at, "
                "  tx_count_updated_at = excluded.tx_count_updated_at",
                (addr, stats["balance_sat"], stats["tx_count"], now, now),
            )
        else:
            conn.execute(
                "UPDATE addresses SET balance_sat = ?, tx_count = ?, "
                "  balance_updated_at = ?, tx_count_updated_at = ? WHERE address = ?",
                (stats["balance_sat"], stats["tx_count"], now, now, addr),
            )
        updated += 1
        if sleep:
            time.sleep(sleep)
    conn.commit()
    return updated


def pending_addresses(conn: sqlite3.Connection, limit: int) -> List[str]:
    """Addresses that have a balance row but no tx_count yet."""
    rows = conn.execute(
        "SELECT address FROM addresses WHERE tx_count IS NULL "
        "ORDER BY balance_sat DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [r["address"] for r in rows]
