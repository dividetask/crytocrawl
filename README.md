# crytocrawl

Download, store, and query **Bitcoin address balances and transaction counts**
locally in a single SQLite file. Pure Python standard library — no pip installs
required to run it.

## The important caveat (read this first)

There is **no API that lists every Bitcoin address**, and there are ~50M+
addresses with a non-zero balance (over a billion ever used). You cannot crawl
them one-by-one — it would take years and get you rate-limited. So getting
*all* addresses works in two stages:

1. **Balances for all addresses** come from a bulk **Blockchair dump** — one
   gzipped TSV of `address \t balance_in_satoshis`, refreshed daily. This is
   the only practical way to get the whole set.
2. **Transaction counts** are *not* in that dump. The only ways to get tx
   counts are (a) per-address API calls (fine for the addresses you care about,
   infeasible for all of them) or (b) running your own full Bitcoin node. This
   tool does (a) on demand via `enrich`. For *complete* tx counts across every
   address you'd need a full node — see "Going further" below.

Balances are stored in **satoshis as integers** (exact) and shown as BTC floats
at query time, so no precision is lost.

## Install

Nothing to install. Requires Python 3.9+. Run as a module:

```bash
python3 -m crytocrawl --help
```

The database path defaults to `bitcoin.db` and can be overridden with `--db` or
the `CRYTOCRAWL_DB` environment variable.

## Quick start

```bash
# 1. Download the Blockchair address dump (~ a few GB; do this with curl/wget):
curl -O https://gz.blockchair.com/bitcoin/addresses/blockchair_bitcoin_addresses_latest.tsv.gz

# 2. Load every address + balance into SQLite (streams the file, flat memory):
python3 -m crytocrawl ingest --file blockchair_bitcoin_addresses_latest.tsv.gz
#    ...or let it download for you:
python3 -m crytocrawl ingest          # fetches Blockchair "latest" itself

# 3. Query from the terminal:
python3 -m crytocrawl stats
python3 -m crytocrawl top -n 25
python3 -m crytocrawl get 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
python3 -m crytocrawl search bc1q --limit 50

# 4. Fill in transaction counts for the addresses you care about:
python3 -m crytocrawl enrich 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
python3 -m crytocrawl enrich --pending 500    # enrich 500 richest un-enriched
```

Add `--json` to any query command for machine-readable output.

## Commands

| Command | What it does |
|---|---|
| `init` | Create the database file/schema |
| `ingest [--file F \| --url U] [--zero-missing]` | Load a Blockchair dump (balances for all addresses) |
| `enrich [ADDR...] [--pending N] [--sleep S]` | Fetch tx_count + fresh balance via mempool.space |
| `get ADDR` | Look up one address |
| `top [-n N]` | Richest addresses by balance |
| `search PREFIX [--limit N]` | Addresses by prefix |
| `stats` | Totals, supply held, enrichment progress, dump date |

`ingest` keeps historical rows by default (so the DB reflects "every address
that ever held a balance"). Pass `--zero-missing` if you instead want addresses
absent from a fresh dump to be reset to a zero balance.

## Querying directly with the `sqlite3` CLI

The store is a plain SQLite file, so you can query it without Python too:

```bash
sqlite3 bitcoin.db "SELECT address, balance_sat/1e8 AS btc, tx_count
                    FROM addresses ORDER BY balance_sat DESC LIMIT 10;"
```

## Using it as a library

```python
from crytocrawl import open_db, get_address, top_addresses, stats

conn = open_db("bitcoin.db")
print(get_address(conn, "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"))
print(top_addresses(conn, 10))
print(stats(conn))
```

## Schema

```
addresses(
  address             TEXT PRIMARY KEY,
  balance_sat         INTEGER NOT NULL,   -- satoshis (exact)
  tx_count            INTEGER,            -- NULL until enriched
  balance_updated_at  TEXT,               -- ISO-8601 UTC
  tx_count_updated_at TEXT
)
meta(key TEXT PRIMARY KEY, value TEXT)    -- dump_date, source, last_ingest_at
```

## Going further: complete tx counts for *every* address

That requires your own data, not a public API. Run Bitcoin Core fully synced
with `-txindex=1`, then:

- `bitcoin-cli dumptxoutset utxos.dat` gives the full UTXO set → balances per
  address (authoritative).
- Scanning every block (`getblock ... 2`) and tallying inputs/outputs per
  address gives exact tx counts.

The SQLite schema and query layer here are reusable for that pipeline; only the
ingest source changes. Open an issue if you want this path scaffolded.

## Tests

```bash
python3 -m pytest -q
```

Tests are fully offline (the API is mocked).
