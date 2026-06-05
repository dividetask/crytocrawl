"""Command-line interface for crytocrawl.

Run with ``python -m crytocrawl <command>``. Commands::

    init      create the database
    ingest    load a Blockchair address dump (balances for all addresses)
    enrich    fetch tx counts (+ fresh balances) for addresses via mempool.space
    get       look up a single address
    top       list the richest addresses
    search    list addresses by prefix
    stats     show aggregate statistics
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from . import db as dbmod
from . import enrich as enrichmod
from . import ingest as ingestmod
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
    tx = row["tx_count"]
    tx_disp = "?" if tx is None else str(tx)
    print(f"{row['address']:<48}  {row['balance_btc']:>18.8f} BTC  tx={tx_disp}")


def cmd_init(args: argparse.Namespace) -> int:
    dbmod.open_db(args.db).close()
    print(f"Initialised database at {args.db}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    conn = dbmod.open_db(args.db, fast=True)
    try:
        n = ingestmod.ingest_dump(
            conn,
            file=args.file,
            url=args.url,
            zero_missing=args.zero_missing,
        )
    finally:
        conn.close()
    print(f"Ingest complete: {n:,} addresses processed.")
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    conn = dbmod.open_db(args.db)
    try:
        addrs: List[str] = list(args.address or [])
        if args.pending:
            addrs += enrichmod.pending_addresses(conn, args.pending)
        if not addrs:
            print("Nothing to enrich. Pass addresses or --pending N.", file=sys.stderr)
            return 1
        n = enrichmod.enrich_addresses(conn, addrs, sleep=args.sleep)
    finally:
        conn.close()
    print(f"Enriched {n} address(es).")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    conn = dbmod.open_db(args.db)
    try:
        row = querymod.get_address(conn, args.address)
    finally:
        conn.close()
    if row is None:
        print(f"Address not found: {args.address}", file=sys.stderr)
        return 1
    _print(row, args.json)
    return 0


def cmd_top(args: argparse.Namespace) -> int:
    conn = dbmod.open_db(args.db)
    try:
        rows = querymod.top_addresses(conn, args.n)
    finally:
        conn.close()
    _print(rows, args.json)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    conn = dbmod.open_db(args.db)
    try:
        rows = querymod.search_addresses(conn, args.prefix, args.limit)
    finally:
        conn.close()
    _print(rows, args.json)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
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
                   help=f"SQLite database path (default: {dbmod.DEFAULT_DB_PATH}, "
                        "or $CRYTOCRAWL_DB)")
    p.add_argument("--json", action="store_true", help="output JSON")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="create the database")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("ingest", help="load a Blockchair address dump")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--file", help="local .tsv.gz (or .tsv) dump to load")
    g.add_argument("--url", help="URL to fetch (default: Blockchair latest)")
    sp.add_argument("--zero-missing", action="store_true",
                    help="set addresses absent from this dump to a zero balance")
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("enrich", help="fetch tx counts via mempool.space")
    sp.add_argument("address", nargs="*", help="specific address(es) to enrich")
    sp.add_argument("--pending", type=int, metavar="N",
                    help="also enrich up to N stored addresses lacking a tx_count")
    sp.add_argument("--sleep", type=float, default=0.5,
                    help="seconds to sleep between API calls (default: 0.5)")
    sp.set_defaults(func=cmd_enrich)

    sp = sub.add_parser("get", help="look up a single address")
    sp.add_argument("address")
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("top", help="list the richest addresses")
    sp.add_argument("-n", type=int, default=20, help="how many (default: 20)")
    sp.set_defaults(func=cmd_top)

    sp = sub.add_parser("search", help="list addresses by prefix")
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
