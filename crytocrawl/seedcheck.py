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
DEFAULT_SORTED_FILE = "dumps/all_Bitcoin_addresses_ever_used_sorted.txt"  # decompressed


def addresses_for_seed(seed: str, *, count: int = 2, passphrase: str = "",
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


# A handful of addresses that are guaranteed to be in any genuine
# "every Bitcoin address ever used" list. Used to prove the binary search
# mechanically works on a given file (right sort order, not gzipped, full list)
# before we trust a "not found" as a real "no".
_SENTINELS = (
    "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # genesis / Satoshi coinbase address
    "12c6DSiU4Rq3P4ZxziKxzrL5LmMBrzjrJX",  # well-known early/large address
)


def _line_start_at_or_after(fh, P: int):
    """Return (start, line) for the first line whose start offset is >= P.

    Checks the byte before P to know whether P already sits on a line boundary,
    so a probe that lands exactly on a line start does not skip that line (a
    boundary bug that could otherwise miss an address -> false negative).
    """
    if P <= 0:
        fh.seek(0)
        return 0, fh.readline()
    fh.seek(P - 1)
    prev = fh.read(1)        # byte at P-1; fh is now positioned at P
    if prev == b"\n":
        return P, fh.readline()
    fh.readline()            # finish the partial line straddling P
    start = fh.tell()
    return start, fh.readline()


def _contains_sorted(fh, size: int, addr: bytes) -> bool:
    """Bytewise binary search for an exact line in a LC_ALL=C-sorted file."""
    lo, hi = 0, size
    while lo < hi:
        mid = (lo + hi) // 2
        start, line = _line_start_at_or_after(fh, mid)
        if not line:
            hi = mid
            continue
        cur = line.rstrip(b"\r\n")
        if cur == addr:
            return True
        if cur < addr:
            lo = start + len(line)
        else:
            hi = mid
    return False


def _first_ge(fh, size: int, key: bytes) -> bytes:
    """Return the first line that is >= key in a bytewise-sorted file (or b'')."""
    lo, hi = 0, size
    ans = b""
    while lo < hi:
        mid = (lo + hi) // 2
        start, line = _line_start_at_or_after(fh, mid)
        if not line:
            hi = mid
            continue
        cur = line.rstrip(b"\r\n")
        if cur < key:
            lo = start + len(line)
        else:
            ans = cur
            hi = mid
    return ans


def bisect_file(targets: Iterable[str], path: str, verify: bool = True) -> set:
    """Membership via binary search over a decompressed, sorted address file.

    Instant lookups with no database. Raises if the file looks gzipped or if a
    self-check fails, so a "not found" is never silently wrong.
    """
    with open(path, "rb") as probe:
        if probe.read(2) == b"\x1f\x8b":
            raise ValueError(f"{path} is gzipped; decompress it first (gunzip -k {path}) "
                             "— binary search needs random access to plain text.")
    fh = open(path, "rb")
    size = os.fstat(fh.fileno()).st_size
    try:
        if verify:
            # 1) the search must mechanically find addresses that ARE present
            missing = [s for s in _SENTINELS if not _contains_sorted(fh, size, s.encode())]
            if missing:
                raise RuntimeError(
                    f"sort-order self-check failed: known-used address {missing[0]} not found "
                    f"via binary search in {path}. The file may be sorted with a non-bytewise "
                    f"collation. Re-sort it with:  LC_ALL=C sort -o {path} {path}\n"
                    "(or pass --no-verify to override if you know the file differs).")
            # 2) confirm the bech32 (bc1...) block is present, so segwit/taproot
            #    wallets can't read a false 'no'. Binary-search for it rather than
            #    inspecting the last line, since some lists have trailing non-bc1
            #    entries that sort after it.
            if not _first_ge(fh, size, b"bc1").startswith(b"bc1"):
                raise RuntimeError(
                    f"coverage self-check failed: {path} contains no bc1... (segwit/taproot) "
                    "addresses. The file is likely truncated or a base58-only list, which would "
                    "make modern wallets falsely read 'no'. Re-download/complete the dump, or pass "
                    "--no-verify to override if you intend to check only legacy addresses.")
        return {a for a in targets if _contains_sorted(fh, size, a.encode())}
    finally:
        fh.close()


def check_seed(seed: str, *, addresses_file: Optional[str] = DEFAULT_ADDRESS_FILE,
               db: Optional[str] = None, sorted_file: Optional[str] = None,
               count: int = 2, passphrase: str = "", account: int = 0,
               electrum: bool = True, progress: bool = False) -> Tuple[bool, List[dict]]:
    """Return (used, matches) for one seed."""
    index = addresses_for_seed(seed, count=count, passphrase=passphrase,
                               account=account, electrum=electrum)
    if db:
        found = scan_db(index, db)
    elif sorted_file:
        found = bisect_file(index, sorted_file)
    else:
        found = scan_file(index, addresses_file, progress=progress)
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
    p.add_argument("--address", "-a", action="append", default=[], metavar="ADDR",
                   help="check a literal address directly (no derivation); repeatable. "
                        "Useful to test an address Electrum shows you against your list.")
    p.add_argument("--count", type=int, default=2, help="receive+change addresses per algorithm (default: 2)")
    p.add_argument("--file", dest="addresses_file", default=None,
                   help=f"used-address list to scan (default: {DEFAULT_ADDRESS_FILE})")
    p.add_argument("--db", default=None,
                   help=f"crytocrawl SQLite DB for fast lookups (default: {DEFAULT_DB_PATH} if it exists)")
    p.add_argument("--sorted-file", default=None,
                   help="decompressed, sorted address file for instant binary-search lookups "
                        "(no database needed)")
    p.add_argument("--no-verify", action="store_true",
                   help="skip the sorted-file sort-order self-check (advanced)")
    p.add_argument("--passphrase", default="", help="optional seed passphrase (BIP39/Electrum)")
    p.add_argument("--account", type=int, default=0, help="account index (default: 0)")
    p.add_argument("--no-electrum", action="store_true", help="skip the Electrum algorithms")
    p.add_argument("--old-wordlist", help="path to Electrum's authoritative old wordlist "
                   "(old_mnemonic.py or a plain word-per-line file) to override the bundled copy")
    p.add_argument("--verbose", "-v", action="store_true", help="also show which address(es) matched")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)

    if args.old_wordlist:
        from . import electrum as el
        words = el.load_wordlist_file(args.old_wordlist)
        el.set_old_wordlist(words)
        if len(words) != 1626:
            print(f"warning: old wordlist has {len(words)} words (expected 1626); "
                  "decoding may be wrong.", file=sys.stderr)

    seeds = [] if args.address else _load_seeds(args)
    if not seeds and not args.address:
        print("No seed provided.", file=sys.stderr)
        return 2

    # Resolve the lookup source. Explicit flags win; otherwise auto-detect, in
    # order of speed: SQLite DB -> decompressed sorted file (binary search) ->
    # the gzipped file (streaming scan).
    db = args.db
    sorted_file = args.sorted_file
    addresses_file = args.addresses_file
    if not (db or sorted_file or addresses_file):
        if os.path.exists(DEFAULT_DB_PATH):
            db = DEFAULT_DB_PATH
        elif os.path.exists(DEFAULT_SORTED_FILE):
            sorted_file = DEFAULT_SORTED_FILE
        else:
            addresses_file = DEFAULT_ADDRESS_FILE
    for label, path in (("Database", db), ("Sorted file", sorted_file), ("Address file", addresses_file)):
        if path and not os.path.exists(path):
            print(f"{label} not found: {path}", file=sys.stderr)
            return 2
    if not (db or sorted_file or addresses_file):
        print("No lookup source. Pass --db, --sorted-file, or --file.", file=sys.stderr)
        return 2

    def lookup(targets):
        if db:
            return scan_db(targets, db)
        if sorted_file:
            return bisect_file(targets, sorted_file, verify=not args.no_verify)
        return scan_file(targets, addresses_file, progress=not args.json)

    # Diagnostic mode: check literal addresses directly, bypassing derivation.
    if args.address:
        try:
            found = lookup(set(args.address))
        except (ValueError, RuntimeError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps([{"address": a, "used": a in found} for a in args.address], indent=2))
        else:
            for a in args.address:
                print(f"{'yes' if a in found else 'no':<3}  {a}")
        return 0 if found else 1

    # Derive every address for every seed, then make ONE pass over the file.
    index: Dict[str, List[Tuple[str, str, str]]] = {}
    for seed in seeds:
        for addr, (algo, path) in addresses_for_seed(
                seed, count=args.count, passphrase=args.passphrase,
                account=args.account, electrum=not args.no_electrum).items():
            index.setdefault(addr, []).append((seed, algo, path))

    if not args.json:
        print(f"Checking {len(index):,} addresses from {len(seeds)} seed(s) "
              f"against {db or sorted_file or addresses_file} ...", file=sys.stderr)
    try:
        found = lookup(index)
    except (ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

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
