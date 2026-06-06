"""Ingest a flat 'every address that ever appeared' list (e.g. LoyceV's dump).

LoyceV publishes, for free and with no API key, a list of every Bitcoin address
that has ever appeared on the blockchain:

    http://alladdresses.loyce.club/   ->  Bitcoin_addresses_LATEST.txt.gz

It is a gzipped plain-text file, **one address per line**, no header, no
balance. An address can only ever appear by first receiving coins in an output,
so "ever appeared" == "ever held a balance" — exactly the required set. We load
each address with ``INSERT OR IGNORE`` (balance defaults to 0); current balances
are applied afterwards by :mod:`crytocrawl.ingest`.

Processed files are recorded in ``ingested_files`` so a multi-GB load is
resumable.
"""

from __future__ import annotations

import datetime as _dt
import glob as _glob
import gzip
import io
import os
import sqlite3
import sys
from typing import IO, Iterable, Iterator, List

from . import db as _dbmod

BATCH_SIZE = 200_000


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _open_text(path: str) -> IO[str]:
    raw = open(path, "rb")
    is_gz = path.endswith(".gz") or raw.read(2) == b"\x1f\x8b"
    raw.seek(0)
    binary = gzip.GzipFile(fileobj=raw) if is_gz else raw
    return io.TextIOWrapper(binary, encoding="utf-8", errors="replace")


def iter_addresses(lines: Iterable[str]) -> Iterator[str]:
    """Yield one address per non-blank line (whitespace stripped).

    Tolerates an optional ``address``/``balance`` header line and TSV lines by
    taking the first whitespace/tab-delimited token.
    """
    for line in lines:
        tok = line.strip().split()[0] if line.strip() else ""
        if not tok or tok.lower() == "address":
            continue
        yield tok


def ingest_address_file(
    conn: sqlite3.Connection, path: str, *, batch_size: int = BATCH_SIZE, progress: bool = True
) -> int:
    """Load one flat address-list file. Returns addresses scanned; no-op if the
    file is already recorded in ``ingested_files``."""
    name = os.path.basename(path)
    if conn.execute("SELECT 1 FROM ingested_files WHERE name = ?", (name,)).fetchone():
        if progress:
            print(f"  skip {name} (already ingested)", file=sys.stderr)
        return 0

    scanned = 0
    text = _open_text(path)
    try:
        batch: List[tuple] = []
        for addr in iter_addresses(text):
            batch.append((addr,))
            scanned += 1
            if len(batch) >= batch_size:
                conn.executemany("INSERT OR IGNORE INTO addresses(address) VALUES(?)", batch)
                batch.clear()
                if progress:
                    print(f"\r  {name}: {scanned:,} addresses...", end="", file=sys.stderr)
        if batch:
            conn.executemany("INSERT OR IGNORE INTO addresses(address) VALUES(?)", batch)
    finally:
        text.close()

    conn.execute(
        "INSERT OR REPLACE INTO ingested_files(name, rows, ingested_at) VALUES(?, ?, ?)",
        (name, scanned, _utcnow()),
    )
    _dbmod.set_meta(conn, "last_addresslist_ingest_at", _utcnow())
    conn.commit()
    if progress:
        print(f"\r  {name}: {scanned:,} addresses.            ", file=sys.stderr)
    return scanned


def discover_files(paths_or_dirs: List[str]) -> List[str]:
    """Expand directories/globs into a sorted list of address-list files."""
    found: List[str] = []
    for p in paths_or_dirs:
        if os.path.isdir(p):
            found += _glob.glob(os.path.join(p, "*.txt*"))
        elif any(ch in p for ch in "*?["):
            found += _glob.glob(p)
        else:
            found.append(p)
    return sorted(set(found))


def ingest_address_lists(
    conn: sqlite3.Connection, paths_or_dirs: List[str], *, progress: bool = True
) -> int:
    """Load every given (or discovered) address-list file. Returns files done."""
    files = discover_files(paths_or_dirs)
    if not files:
        raise FileNotFoundError("no address-list files matched: " + ", ".join(paths_or_dirs))
    for path in files:
        ingest_address_file(conn, path, progress=progress)
    return len(files)
