"""Fill in *current* balances from the Blockchair addresses dump.

    https://gz.blockchair.com/bitcoin/addresses/blockchair_bitcoin_addresses_latest.tsv.gz

Format (tab-separated, header row), balance in **satoshis**::

    address	balance
    1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa	6857585654

This dump lists only addresses with a *currently* non-zero balance. The full
"ever held a balance" set comes from :mod:`crytocrawl.outputs`; this step just
writes the current balance onto those rows. By default we first reset every
stored balance to 0, so addresses that have since been spent out correctly read
0 even on a re-run (the dump won't mention them).
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
_USER_AGENT = "crytocrawl/0.2 (+https://github.com/dividetask/crytocrawl)"
BATCH_SIZE = 50_000


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _open_source(file: Optional[str], url: Optional[str]) -> Tuple[IO[bytes], str]:
    if file:
        return open(file, "rb"), f"file:{file}"
    target = url or LATEST_URL
    req = urllib.request.Request(target, headers={"User-Agent": _USER_AGENT})
    resp = urllib.request.urlopen(req)  # noqa: S310 (intentional remote fetch)
    return resp, f"url:{target}"


SATS_PER_BTC = 100_000_000


def _to_sat(value: str, unit: str) -> int:
    """Convert a balance string to integer satoshis.

    unit='sat' -> integer satoshis; 'btc' -> BTC (may be decimal); 'auto' ->
    treat as BTC when a decimal point is present, else satoshis. LoyceV's
    with-balance dump (mirrored from Blockchair) is in satoshis, but other
    mirrors express BTC, so auto-detection avoids a silent 1e8 error.
    """
    value = value.strip()
    if unit == "sat":
        return int(value)
    if unit == "btc" or (unit == "auto" and "." in value):
        return round(float(value) * SATS_PER_BTC)
    return int(value)


def parse_rows(text_stream: Iterable[str], unit: str = "auto") -> Iterator[Tuple[str, int]]:
    """Yield ``(address, balance_sat)`` from decoded TSV lines, skipping header."""
    first = True
    for line in text_stream:
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.replace("\t", " ").split()
        if len(parts) < 2:
            continue
        addr, bal = parts[0], parts[1]
        if first:
            first = False
            if bal.strip().lower() == "balance" or addr.strip().lower() == "address":
                continue
        try:
            yield addr, _to_sat(bal, unit)
        except ValueError:
            continue


def _upsert_batch(conn: sqlite3.Connection, batch, now: str) -> None:
    conn.executemany(
        "INSERT INTO addresses(address, balance_sat, balance_updated_at) "
        "VALUES(?, ?, ?) "
        "ON CONFLICT(address) DO UPDATE SET "
        "  balance_sat = excluded.balance_sat, "
        "  balance_updated_at = excluded.balance_updated_at",
        [(addr, bal, now) for addr, bal in batch],
    )


def ingest_balances(
    conn: sqlite3.Connection,
    *,
    file: Optional[str] = None,
    url: Optional[str] = None,
    batch_size: int = BATCH_SIZE,
    zero_first: bool = True,
    unit: str = "auto",
    progress: bool = True,
) -> int:
    """Apply current balances from an ``address<TAB>balance`` dump.

    Works with the Blockchair addresses dump and the LoyceV with-balance mirror.
    ``unit`` ('auto'|'sat'|'btc') controls how the balance column is interpreted.
    With ``zero_first`` (default) all stored balances are reset to 0 before the
    dump is applied, guaranteeing the table reflects *current* balances exactly.
    Returns the number of funded address rows written.
    """
    from . import db as _dbmod

    raw, source = _open_source(file, url)
    now = _utcnow()
    processed = 0

    try:
        peeked = raw.peek(2) if hasattr(raw, "peek") else b""
    except Exception:
        peeked = b""
    is_gzip = source.startswith("url:") or (file or "").endswith(".gz") or peeked[:2] == b"\x1f\x8b"
    binary = gzip.GzipFile(fileobj=raw) if is_gzip else raw
    text = io.TextIOWrapper(binary, encoding="utf-8", errors="replace")

    try:
        if zero_first:
            conn.execute("UPDATE addresses SET balance_sat = 0, balance_updated_at = ?", (now,))

        batch = []
        for addr, bal in parse_rows(text, unit):
            batch.append((addr, bal))
            if len(batch) >= batch_size:
                _upsert_batch(conn, batch, now)
                processed += len(batch)
                batch.clear()
                if progress:
                    print(f"\r  balances: {processed:,} funded addresses...", end="", file=sys.stderr)
        if batch:
            _upsert_batch(conn, batch, now)
            processed += len(batch)

        _dbmod.set_meta(conn, "balances_dump_source", source)
        _dbmod.set_meta(conn, "balances_dump_date", now[:10])
        _dbmod.set_meta(conn, "last_balances_ingest_at", now)
        conn.commit()
    finally:
        text.close()
        if raw is not binary:
            try:
                raw.close()
            except Exception:
                pass

    if progress:
        print(f"\r  balances: {processed:,} funded addresses.        ", file=sys.stderr)
    return processed
