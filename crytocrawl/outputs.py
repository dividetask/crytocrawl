"""Build the 'ever held a balance' address set from Blockchair output dumps.

Blockchair publishes one gzipped TSV per day of every transaction *output*:

    https://gz.blockchair.com/bitcoin/outputs/blockchair_bitcoin_outputs_YYYYMMDD.tsv.gz

Each output names its ``recipient`` (the address that received the coins) and
the ``value`` (in satoshis). An address has "ever held a balance" exactly when
it was the recipient of at least one output with value > 0. So aggregating the
distinct recipients across *all* daily files yields the complete set required.

We insert each distinct recipient with ``INSERT OR IGNORE`` (balance defaults
to 0); current balances are filled in afterwards by ``ingest.ingest_balances``
from the addresses dump. Processed files are recorded in ``ingested_files`` so
the (multi-hour, multi-hundred-GB) full-history run is resumable.
"""

from __future__ import annotations

import datetime as _dt
import glob as _glob
import gzip
import io
import os
import re
import sqlite3
import sys
from typing import IO, Iterable, Iterator, List, Optional

from . import db as _dbmod

BATCH_SIZE = 200_000
_DATE_RE = re.compile(r"_(\d{8})\.tsv(?:\.gz)?$")


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def file_date(path: str) -> Optional[str]:
    """Extract the YYYYMMDD date embedded in a dump filename, if present."""
    m = _DATE_RE.search(os.path.basename(path))
    return m.group(1) if m else None


def _open_text(path: str) -> IO[str]:
    raw = open(path, "rb")
    is_gz = path.endswith(".gz") or raw.read(2) == b"\x1f\x8b"
    raw.seek(0)
    binary = gzip.GzipFile(fileobj=raw) if is_gz else raw
    return io.TextIOWrapper(binary, encoding="utf-8", errors="replace")


def _column_indexes(header: str) -> tuple[int, int]:
    """Return (recipient_idx, value_idx) from a TSV header row."""
    cols = header.rstrip("\n").split("\t")
    try:
        rec = cols.index("recipient")
    except ValueError:
        raise ValueError(
            "dump header has no 'recipient' column; got: " + ", ".join(cols[:8])
        )
    try:
        val = cols.index("value")
    except ValueError:
        val = -1  # value column optional; if absent we keep every recipient
    return rec, val


def iter_recipients(lines: Iterable[str]) -> Iterator[str]:
    """Yield non-empty recipient addresses (value > 0) from output-dump lines."""
    it = iter(lines)
    try:
        header = next(it)
    except StopIteration:
        return
    rec_idx, val_idx = _column_indexes(header)
    need = max(rec_idx, val_idx) + 1
    for line in it:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < need:
            continue
        recipient = parts[rec_idx]
        if not recipient:
            continue
        if val_idx >= 0:
            v = parts[val_idx]
            # Skip zero-value outputs (e.g. OP_RETURN) — they never "held" coins.
            if not v or v == "0":
                continue
        yield recipient


def ingest_output_file(
    conn: sqlite3.Connection, path: str, *, batch_size: int = BATCH_SIZE, progress: bool = True
) -> int:
    """Aggregate one output dump file into the addresses table.

    Returns the number of recipient rows scanned. Records the file in
    ``ingested_files``; a no-op if already recorded.
    """
    name = os.path.basename(path)
    already = conn.execute(
        "SELECT 1 FROM ingested_files WHERE name = ?", (name,)
    ).fetchone()
    if already:
        if progress:
            print(f"  skip {name} (already ingested)", file=sys.stderr)
        return 0

    scanned = 0
    text = _open_text(path)
    try:
        batch: set[str] = set()
        for recipient in iter_recipients(text):
            batch.add(recipient)
            scanned += 1
            if len(batch) >= batch_size:
                conn.executemany(
                    "INSERT OR IGNORE INTO addresses(address) VALUES(?)",
                    [(a,) for a in batch],
                )
                batch.clear()
                if progress:
                    print(f"\r  {name}: {scanned:,} outputs...", end="", file=sys.stderr)
        if batch:
            conn.executemany(
                "INSERT OR IGNORE INTO addresses(address) VALUES(?)",
                [(a,) for a in batch],
            )
    finally:
        text.close()

    conn.execute(
        "INSERT OR REPLACE INTO ingested_files(name, rows, ingested_at) VALUES(?, ?, ?)",
        (name, scanned, _utcnow()),
    )
    d = file_date(name)
    if d:
        prev = _dbmod.get_meta(conn, "outputs_through")
        if prev is None or d > prev:
            _dbmod.set_meta(conn, "outputs_through", d)
    _dbmod.set_meta(conn, "last_outputs_ingest_at", _utcnow())
    conn.commit()
    if progress:
        print(f"\r  {name}: {scanned:,} outputs.            ", file=sys.stderr)
    return scanned


def discover_files(paths_or_dirs: List[str]) -> List[str]:
    """Expand directories/globs into a sorted list of dump files."""
    found: List[str] = []
    for p in paths_or_dirs:
        if os.path.isdir(p):
            found += _glob.glob(os.path.join(p, "blockchair_bitcoin_outputs_*.tsv*"))
        elif any(ch in p for ch in "*?["):
            found += _glob.glob(p)
        else:
            found.append(p)
    # Sort by embedded date when available so 'outputs_through' advances in order.
    return sorted(set(found), key=lambda x: (file_date(x) or "", x))


def ingest_outputs(
    conn: sqlite3.Connection, paths_or_dirs: List[str], *, progress: bool = True
) -> int:
    """Aggregate every given (or discovered) output dump file. Returns files done."""
    files = discover_files(paths_or_dirs)
    if not files:
        raise FileNotFoundError("no output dump files matched: " + ", ".join(paths_or_dirs))
    done = 0
    for path in files:
        ingest_output_file(conn, path, progress=progress)
        done += 1
    return done
