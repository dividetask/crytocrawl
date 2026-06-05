"""Command-line interface for crytocrawl.

Run with ``python -m crytocrawl <command>``. Pipeline commands::

    init              create the database
    download          fetch Blockchair dump files (resumable)
    ingest-outputs    aggregate output dumps -> every address that ever held a balance
    ingest-balances   apply the addresses dump -> each address's current balance

Query commands::

    exists ADDR   did this address ever hold a balance? (exit 0 = yes, 1 = no)
    get ADDR      show an address's current balance
    top [-n N]    richest addresses
    search PREFIX addresses by prefix
    stats         aggregate statistics
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from . import db as dbmod
from . import download as dlmod
from . import ingest as ingestmod
from . import outputs as outputsmod
from . import query as querymod


def _print(obj, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, default=str))
        return
    if isinstance(obj, list):
        for item in obj:
            _print_row(item)
    elif isinstance(obj, dict) and "address" in obj:
        _print_row(obj)
    elif isinstance(obj, dict):
        width = max((len(k) for k in obj), default=0)
        for k, v in obj.items():
            print(f"{k.ljust(width)}  {v}")
    else:
        print(obj)


def _print_row(row: dict) -> None:
    print(f"{row['address']:<48}  {row['balance_btc']:>18.8f} BTC")


def cmd_init(args) -> int:
    dbmod.open_db(args.db).close()
    print(f"Initialised database at {args.db}")
    return 0


def cmd_download(args) -> int:
    paths = dlmod.download_dataset(
        args.dataset, args.dir, since=args.since, until=args.until, sleep=args.sleep
    )
    print(f"Downloaded/verified {len(paths)} file(s) into {args.dir}")
    return 0


def cmd_ingest_outputs(args) -> int:
    conn = dbmod.open_db(args.db, fast=True)
    try:
        n = outputsmod.ingest_outputs(conn, args.paths)
        total = querymod.count_addresses(conn)
    finally:
        conn.close()
    print(f"Aggregated {n} file(s). Addresses that ever held a balance: {total:,}")
    return 0


def cmd_ingest_balances(args) -> int:
    conn = dbmod.open_db(args.db, fast=True)
    try:
        n = ingestmod.ingest_balances(
            conn, file=args.file, url=args.url, zero_first=not args.no_zero_first
        )
    finally:
        conn.close()
    print(f"Applied current balances: {n:,} funded addresses.")
    return 0


def cmd_exists(args) -> int:
    conn = dbmod.open_db(args.db)
    try:
        held = querymod.ever_held(conn, args.address)
    finally:
        conn.close()
    if args.json:
        print(json.dumps({"address": args.address, "ever_held": held}))
    else:
        print("yes" if held else "no")
    return 0 if held else 1


def cmd_get(args) -> int:
    conn = dbmod.open_db(args.db)
    try:
        row = querymod.get_address(conn, args.address)
    finally:
        conn.close()
    if row is None:
        print(f"Address never held a balance (not stored): {args.address}", file=sys.stderr)
        return 1
    _print(row, args.json)
    return 0


def cmd_top(args) -> int:
    conn = dbmod.open_db(args.db)
    try:
        rows = querymod.top_addresses(conn, args.n)
    finally:
        conn.close()
    _print(rows, args.json)
    return 0


def cmd_search(args) -> int:
    conn = dbmod.open_db(args.db)
    try:
        rows = querymod.search_addresses(conn, args.prefix, args.limit)
    finally:
        conn.close()
    _print(rows, args.json)
    return 0


def cmd_stats(args) -> int:
    conn = dbmod.open_db(args.db)
    try:
        s = querymod.stats(conn)
    finally:
        conn.close()
    _print(s, args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crytocrawl", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=dbmod.DEFAULT_DB_PATH,
                   help=f"SQLite database path (default: {dbmod.DEFAULT_DB_PATH}, or $CRYTOCRAWL_DB)")
    p.add_argument("--json", action="store_true", help="output JSON")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="create the database")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("download", help="fetch Blockchair dump files (resumable)")
    sp.add_argument("--dataset", choices=["outputs", "addresses"], default="outputs")
    sp.add_argument("--dir", required=True, help="destination directory")
    sp.add_argument("--since", help="earliest file date YYYYMMDD (inclusive)")
    sp.add_argument("--until", help="latest file date YYYYMMDD (inclusive)")
    sp.add_argument("--sleep", type=float, default=1.0, help="seconds between files")
    sp.set_defaults(func=cmd_download)

    sp = sub.add_parser("ingest-outputs",
                        help="aggregate output dumps into the 'ever held' address set")
    sp.add_argument("paths", nargs="+", help="dump files, globs, or directories")
    sp.set_defaults(func=cmd_ingest_outputs)

    sp = sub.add_parser("ingest-balances", help="apply current balances from the addresses dump")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--file", help="local addresses .tsv.gz (or .tsv) dump")
    g.add_argument("--url", help="URL to fetch (default: Blockchair addresses latest)")
    sp.add_argument("--no-zero-first", action="store_true",
                    help="do NOT reset balances to 0 before applying (faster, less exact on re-runs)")
    sp.set_defaults(func=cmd_ingest_balances)

    sp = sub.add_parser("exists", help="did an address ever hold a balance?")
    sp.add_argument("address")
    sp.set_defaults(func=cmd_exists)

    sp = sub.add_parser("get", help="show an address's current balance")
    sp.add_argument("address")
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("top", help="richest addresses")
    sp.add_argument("-n", type=int, default=20)
    sp.set_defaults(func=cmd_top)

    sp = sub.add_parser("search", help="addresses by prefix")
    sp.add_argument("prefix")
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("stats", help="aggregate statistics")
    sp.set_defaults(func=cmd_stats)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
