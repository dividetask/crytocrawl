"""Bulk ingest of the Blockchair address dump.

Blockchair publishes a daily gzip-compressed TSV of every address with a
non-zero balance:

    https://gz.blockchair.com/bitcoin/addresses/blockchair_bitcoin_addresses_latest.tsv.gz

Format (tab-separated, with a header row)::

    address	balance
    1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa	6857585654
    ...

``balance`` is in **satoshis**. This module streams the file (so memory stays
flat even on a multi-GB dump) and upserts rows into SQLite in batches.

The dump only lists addresses that *currently* hold a balance. We never delete
rows, so addresses that previously held a balance remain in the DB (matching
the "every address that ever held a balance" requirement). Use
``zero_missing=True`` if you instead want addresses absent from a fresh dump to
be set to a zero balance.
"""

from __future__ import annotations

import datetime as _dt
import gzip
import io
import sqlite3
import sys
import urllib.request
from typing import IO, Iterable, Iterator, Optional, Tuple

LATEST_URL = (
    "https://gz.blockchair.com/bitcoin/addresses/"
    "blockchair_bitcoin_addresses_latest.tsv.gz"
)

_USER_AGENT = "crytocrawl/0.1 (+https://github.com/dividetask/crytocrawl)"
BATCH_SIZE = 50_000


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _open_source(file: Optional[str], url: Optional[str]) -> Tuple[IO[bytes], str]:
    """Return a binary stream of the (still gzipped) dump and a source label."""
    if file:
        return open(file, "rb"), f"file:{file}"
    target = url or LATEST_URL
    req = urllib.request.Request(target, headers={"User-Agent": _USER_AGENT})
    resp = urllib.request.urlopen(req)  # noqa: S310 (intentional remote fetch)
    return resp, f"url:{target}"


def parse_rows(text_stream: Iterable[str]) -> Iterator[Tuple[str, int]]:
    """Yield ``(address, balance_sat)`` from the decoded TSV lines.

    Skips a leading header row if present and ignores blank/malformed lines.
    """
    first = True
    for line in text_stream:
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        addr, bal = parts[0], parts[1]
        if first:
            first = False
            # Header row uses the literal column name.
            if bal.strip().lower() == "balance" or not bal.strip().isdigit():
                continue
        try:
            yield addr, int(bal)
        except ValueError:
            continue


def _upsert_batch(conn: sqlite3.Connection, batch: list[Tuple[str, int]], now: str) -> None:
    conn.executemany(
        "INSERT INTO addresses(address, balance_sat, balance_updated_at) "
        "VALUES(?, ?, ?) "
        "ON CONFLICT(address) DO UPDATE SET "
        "  balance_sat = excluded.balance_sat, "
        "  balance_updated_at = excluded.balance_updated_at",
        [(addr, bal, now) for addr, bal in batch],
    )


def ingest_dump(
    conn: sqlite3.Connection,
    *,
    file: Optional[str] = None,
    url: Optional[str] = None,
    batch_size: int = BATCH_SIZE,
    zero_missing: bool = False,
    progress: bool = True,
) -> int:
    """Load a Blockchair address dump into ``conn``.

    Provide ``file`` for a locally-downloaded ``.tsv.gz`` (or plain ``.tsv``),
    or ``url`` to fetch (defaults to Blockchair's "latest"). Returns the number
    of address rows processed.
    """
    from . import db as _dbmod

    raw, source = _open_source(file, url)
    now = _utcnow()
    processed = 0

    # Transparently handle both gzipped and already-decompressed inputs.
    try:
        peeked = raw.peek(2) if hasattr(raw, "peek") else b""
    except Exception:
        peeked = b""
    is_gzip = source.startswith("url:") or (file or "").endswith(".gz") or peeked[:2] == b"\x1f\x8b"

    binary = gzip.GzipFile(fileobj=raw) if is_gzip else raw
    text = io.TextIOWrapper(binary, encoding="utf-8", errors="replace")

    try:
        if zero_missing:
            conn.execute("UPDATE addresses SET balance_sat = 0, balance_updated_at = ?", (now,))

        batch: list[Tuple[str, int]] = []
        for addr, bal in parse_rows(text):
            batch.append((addr, bal))
            if len(batch) >= batch_size:
                _upsert_batch(conn, batch, now)
                processed += len(batch)
                batch.clear()
                if progress:
                    print(f"\r  ingested {processed:,} addresses...", end="", file=sys.stderr)
        if batch:
            _upsert_batch(conn, batch, now)
            processed += len(batch)

        _dbmod.set_meta(conn, "dump_source", source)
        _dbmod.set_meta(conn, "last_ingest_at", now)
        _dbmod.set_meta(conn, "dump_date", now[:10])
        conn.commit()
    finally:
        text.close()
        if raw is not binary:
            try:
                raw.close()
            except Exception:
                pass

    if progress:
        print(f"\r  ingested {processed:,} addresses.        ", file=sys.stderr)
    return processed
