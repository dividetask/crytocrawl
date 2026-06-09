"""Has this seed ever been used? Derive its first N receive + change addresses
across every algorithm and check them against the used-address list.

    seedcheck "<seed>"        -> prints "yes" or "no"

By default it checks the first 4 receiving and first 4 change addresses of each
derivation algorithm (BIP44/49/84/86 and Electrum legacy/segwit/old) against
``dumps/all_Bitcoin_addresses_ever_used_sorted.txt.gz``. "yes" means at least
one of those addresses has appeared on the blockchain.

Exit status: 0 = used (yes), 1 = not used (no), 2 = error. With multiple seeds
it prints one line each and always exits 0.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import sys
from typing import Dict, Iterable, List, Optional, Tuple

from .derive import derive_from_mnemonic
from .db import DEFAULT_DB_PATH

DEFAULT_ADDRESS_FILE = "dumps/all_Bitcoin_addresses_ever_used_sorted.txt.gz"


def addresses_for_seed(seed: str, *, count: int = 4, passphrase: str = "",
                       account: int = 0, electrum: bool = True) -> Dict[str, Tuple[str, str]]:
    """Map address -> (algorithm, path) for the first ``count`` receive (chain 0)
    and change (chain 1) addresses of every algorithm."""
    out: Dict[str, Tuple[str, str]] = {}
    for change in (0, 1):
        result = derive_from_mnemonic(seed, passphrase=passphrase, count=count,
                                      account=account, change=change, electrum=electrum)
        for algo, entries in result.items():
            for e in entries:
                out.setdefault(e["address"], (algo, e["path"]))
    return out


def _open_text(path: str):
    raw = open(path, "rb")
    is_gz = path.endswith(".gz") or raw.read(2) == b"\x1f\x8b"
    raw.seek(0)
    binary = gzip.GzipFile(fileobj=raw) if is_gz else raw
    return io.TextIOWrapper(binary, encoding="utf-8", errors="replace")


def scan_file(targets: Iterable[str], path: str, progress: bool = False) -> set:
    """Single streaming pass over the used-address file; return matched targets."""
    wanted = set(targets)
    found: set = set()
    if not wanted:
        return found
    text = _open_text(path)
    n = 0
    try:
        for line in text:
            n += 1
            addr = line.strip()
            if addr in wanted:
                found.add(addr)
                wanted.discard(addr)
                if not wanted:
                    break
            if progress and n % 25_000_000 == 0:
                print(f"  scanned {n:,} addresses...", file=sys.stderr)
    finally:
        text.close()
    return found


def scan_db(targets: Iterable[str], db_path: str) -> set:
    """Fast membership via a crytocrawl SQLite DB (index lookups, no full scan)."""
    from . import db as dbmod
    from . import query as querymod
    conn = dbmod.open_db(db_path)
    try:
        return {a for a in targets if querymod.ever_held(conn, a)}
    finally:
        conn.close()


def check_seed(seed: str, *, addresses_file: str = DEFAULT_ADDRESS_FILE, db: Optional[str] = None,
               count: int = 4, passphrase: str = "", account: int = 0,
               electrum: bool = True, progress: bool = False) -> Tuple[bool, List[dict]]:
    """Return (used, matches) for one seed."""
    index = addresses_for_seed(seed, count=count, passphrase=passphrase,
                               account=account, electrum=electrum)
    found = scan_db(index, db) if db else scan_file(index, addresses_file, progress=progress)
    matches = [{"address": a, "algorithm": index[a][0], "path": index[a][1]} for a in found]
    return bool(matches), matches


# --- CLI ---------------------------------------------------------------------

def _load_seeds(args) -> List[str]:
    if args.seed_file:
        with open(args.seed_file, encoding="utf-8") as fh:
            return [ln.rstrip("\n") for ln in fh if ln.strip()]
    if args.seed is not None:
        return [args.seed]
    return [ln.rstrip("\n") for ln in sys.stdin if ln.strip()]


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="seedcheck", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("seed", nargs="?", help="the seed to check (omit to read seeds from stdin)")
    p.add_argument("--seed-file", help="file of seeds to check, one per line")
    p.add_argument("--count", type=int, default=4, help="receive+change addresses per algorithm (default: 4)")
    p.add_argument("--file", dest="addresses_file", default=None,
                   help=f"used-address list to scan (default: {DEFAULT_ADDRESS_FILE})")
    p.add_argument("--db", default=None,
                   help=f"crytocrawl SQLite DB for fast lookups (default: {DEFAULT_DB_PATH} if it exists)")
    p.add_argument("--passphrase", default="", help="optional seed passphrase (BIP39/Electrum)")
    p.add_argument("--account", type=int, default=0, help="account index (default: 0)")
    p.add_argument("--no-electrum", action="store_true", help="skip the Electrum algorithms")
    p.add_argument("--verbose", "-v", action="store_true", help="also show which address(es) matched")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)

    seeds = _load_seeds(args)
    if not seeds:
        print("No seed provided.", file=sys.stderr)
        return 2

    # Resolve the lookup source: explicit --db/--file wins, else auto-detect the
    # default SQLite DB (fast), else fall back to the default address file.
    db = args.db
    addresses_file = args.addresses_file
    if not db and not addresses_file:
        if os.path.exists(DEFAULT_DB_PATH):
            db = DEFAULT_DB_PATH
        else:
            addresses_file = DEFAULT_ADDRESS_FILE
    if db and not os.path.exists(db):
        print(f"Database not found: {db}", file=sys.stderr)
        return 2
    if not db and not os.path.exists(addresses_file):
        print(f"Address source not found: {addresses_file}\n"
              f"Build the DB (crytocrawl ingest-addresses ...) or pass --file <path> / --db <sqlite db>.",
              file=sys.stderr)
        return 2

    # Derive every address for every seed, then make ONE pass over the file.
    index: Dict[str, List[Tuple[str, str, str]]] = {}
    for seed in seeds:
        for addr, (algo, path) in addresses_for_seed(
                seed, count=args.count, passphrase=args.passphrase,
                account=args.account, electrum=not args.no_electrum).items():
            index.setdefault(addr, []).append((seed, algo, path))

    if not args.json:
        print(f"Checking {len(index):,} addresses from {len(seeds)} seed(s) against {db or addresses_file} ...",
              file=sys.stderr)
    found = scan_db(index, db) if db else scan_file(index, addresses_file, progress=not args.json)

    used_seeds: Dict[str, List[dict]] = {s: [] for s in seeds}
    for addr in found:
        for seed, algo, path in index[addr]:
            used_seeds[seed].append({"address": addr, "algorithm": algo, "path": path})

    if args.json:
        out = [{"seed": s, "used": bool(m), "matches": m} for s, m in used_seeds.items()]
        print(json.dumps(out if len(seeds) > 1 else out[0], indent=2))
    elif len(seeds) == 1:
        s = seeds[0]
        print("yes" if used_seeds[s] else "no")
        if args.verbose and used_seeds[s]:
            for m in used_seeds[s]:
                print(f"  {m['address']}  ({m['algorithm']} {m['path']})", file=sys.stderr)
    else:
        for s in seeds:
            print(f"{'yes' if used_seeds[s] else 'no':<3}  {s}")

    if len(seeds) == 1:
        return 0 if used_seeds[seeds[0]] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
