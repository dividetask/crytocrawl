"""crytocrawl - download, store and query Bitcoin address balances & tx counts.

Public API (importable):

    from crytocrawl import db, ingest, enrich, query

The most useful query helpers are re-exported here for convenience::

    from crytocrawl import open_db, get_address, top_addresses, stats
"""

from .db import open_db, init_db
from .query import get_address, top_addresses, stats, search_addresses, count_addresses

__all__ = [
    "open_db",
    "init_db",
    "get_address",
    "top_addresses",
    "stats",
    "search_addresses",
    "count_addresses",
]

__version__ = "0.1.0"

SATS_PER_BTC = 100_000_000
