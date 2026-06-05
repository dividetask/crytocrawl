"""crytocrawl - the set of every Bitcoin address that ever held a balance,
plus each address's current balance, stored locally and queryable.

Public API (importable):

    from crytocrawl import db, outputs, ingest, download, query

Convenience re-exports::

    from crytocrawl import open_db, get_address, ever_held, top_addresses, stats
"""

from .db import open_db, init_db
from .query import (
    get_address,
    ever_held,
    top_addresses,
    stats,
    search_addresses,
    count_addresses,
)

__all__ = [
    "open_db",
    "init_db",
    "get_address",
    "ever_held",
    "top_addresses",
    "stats",
    "search_addresses",
    "count_addresses",
]

__version__ = "0.2.0"

SATS_PER_BTC = 100_000_000
