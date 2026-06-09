# crytocrawl

A local, queryable store of **every Bitcoin address that has ever held a
balance**, with each address's **current balance**. Pure Python standard
library — nothing to `pip install` to run it; data lives in one SQLite file.

## Install (fresh server)

No third-party dependencies — just Python 3.8+. On a clean Debian/Ubuntu VM:

```bash
git clone https://github.com/dividetask/crytocrawl.git
cd crytocrawl
bash install.sh        # installs python3/venv + the `crytocrawl` command into ~/crytocrawl-venv
source ~/crytocrawl-venv/bin/activate
crytocrawl --help
```

`install.sh` also installs the optional `sqlite3` CLI (handy for querying the DB
directly; not required — the tool uses Python's built-in sqlite3).

Prefer to do it by hand, or on another OS:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install .          # registers the `crytocrawl` command
```

Or skip installing entirely and run it straight from the repo:

```bash
python3 -m crytocrawl --help
```

All three give you the same CLI; the examples below use `crytocrawl` (swap in
`python3 -m crytocrawl` if you didn't install).

## TL;DR — the free, no-key, no-node way

You do **not** need a Blockchair API key, and you do **not** need to run a node
or crawl the chain. Two free public files (published by *LoyceV*, derived from a
full archival node) give you everything:

```bash
export CRYTOCRAWL_DB=bitcoin.db

# 1. Every address that ever appeared = every address that ever held a balance.
crytocrawl download --source loyce-all     --dir dumps
crytocrawl ingest-addresses dumps/all_Bitcoin_addresses_ever_used_sorted.txt.gz

# 2. Current balance for every funded address (first load: --no-zero-first is faster).
crytocrawl download --source loyce-balance --dir dumps
crytocrawl ingest-balances --file dumps/Bitcoin_addresses_LATEST.txt.gz --no-zero-first

# 3. Query.
crytocrawl exists 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa   # yes/no (exit 0/1)
crytocrawl get    1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa   # current balance
crytocrawl stats
crytocrawl top -n 25
```

That's the whole thing. The rest of this README explains the model, the
alternatives, and the exact behaviour.

## What "ever held a balance" means

An address has held a balance if and only if it was ever the recipient of a
transaction output — and an address can only be spent from after it has
received, so **every address that ever appeared on the blockchain has held a
balance**. That historical set is exactly LoyceV's "all addresses ever" list.

The data is built in two phases:

1. **`ingest-addresses`** loads the flat "every address ever" list → the
   complete ever-held set (each stored with balance 0).
2. **`ingest-balances`** applies the current-balance list on top. Addresses that
   received coins in the past but have since spent them all stay in the table
   with a current balance of **0**.

> The current-balance list alone is **not** enough — it omits every spent-out
> address. The "all addresses ever" list is what makes the set complete.

Balances are stored as integer **satoshis** (exact) and shown as BTC floats at
query time, so no precision is lost. **Presence of a row is the "ever held a
balance" fact.**

## Data sources (pick one)

| Source | API key? | Run a node? | How |
|---|---|---|---|
| **LoyceV free dumps** *(recommended)* | No | No | `loyce-all` + `loyce-balance` as above. Trusts LoyceV's extraction. |
| Blockchair dumps | Usually yes (history) | No | `ingest-outputs` on the full output-dump history + `ingest-balances`. |
| Your own full node | No | Yes | Scan blocks for output addresses; `dumptxoutset` for balances. Most authoritative. |

All three produce the same table; only ingest changes. The LoyceV path is the
one wired up for "no key, no node".

> **Filenames:** LoyceV occasionally renames its files. The `download --source`
> presets use the current known names, but if a download 404s, grab the file
> from `http://alladdresses.loyce.club/` / `http://addresses.loyce.club/` and
> point `ingest-addresses` / `ingest-balances --file` straight at it — the
> ingest commands accept any local path. `ingest-balances` also has
> `--unit auto|sat|btc` in case a mirror expresses balances in BTC.

## Requirements & expectations

- Python 3.8+. No third-party packages.
- The "all addresses ever" file is large (a few GB compressed, ~1B+ lines);
  loading it is a one-pass, multi-hour job. The resulting SQLite DB is tens of
  GB. Downloads are resumable; ingests are idempotent (processed files are
  recorded, so you can stop and restart).

## Commands

| Command | What it does |
|---|---|
| `init` | Create the database file/schema |
| `download --source {loyce-all,loyce-balance,blockchair-outputs,blockchair-addresses} --dir D` | Fetch dumps (resumable). `--url U` for an arbitrary file. |
| `ingest-addresses PATHS...` | Load a flat "every address ever" list → ever-held set *(recommended)* |
| `ingest-outputs PATHS...` | Alt: aggregate Blockchair output dumps → ever-held set |
| `ingest-balances [--file F \| --url U] [--unit auto\|sat\|btc] [--no-zero-first]` | Apply current balances |
| `exists ADDR` | Did this address ever hold a balance? (`yes`/`no`, exit 0/1) |
| `get ADDR` | Show an address's current balance |
| `top [-n N]` | Richest addresses by current balance |
| `search PREFIX [--limit N]` | Addresses by prefix |
| `stats` | Totals, # ever-held, # currently funded, dump dates |

Add `--json` to any query for machine-readable output.

## Query directly with the `sqlite3` CLI

It's a plain SQLite file, so you don't even need Python to query it:

```bash
# Did an address ever hold a balance?
sqlite3 bitcoin.db "SELECT EXISTS(SELECT 1 FROM addresses WHERE address='1A1z...');"
# Current balance (BTC):
sqlite3 bitcoin.db "SELECT balance_sat/1e8 FROM addresses WHERE address='1A1z...';"
# Richest 10:
sqlite3 bitcoin.db "SELECT address, balance_sat/1e8 AS btc FROM addresses
                    ORDER BY balance_sat DESC LIMIT 10;"
```

## As a library

```python
from crytocrawl import open_db, ever_held, get_address, top_addresses, stats

conn = open_db("bitcoin.db")
print(ever_held(conn, "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"))   # True/False
print(get_address(conn, "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")) # {'balance_btc': ...}
print(top_addresses(conn, 10))
print(stats(conn))
```

## Schema

```
addresses(
  address             TEXT PRIMARY KEY,   -- exists  => ever held a balance
  balance_sat         INTEGER NOT NULL,   -- current balance in satoshis (0 = spent out)
  balance_updated_at  TEXT                -- ISO-8601 UTC
)
ingested_files(name TEXT PRIMARY KEY, rows INTEGER, ingested_at TEXT)  -- resume bookkeeping
meta(key TEXT PRIMARY KEY, value TEXT)    -- dump dates, progress
```

## Tests

```bash
python3 -m pytest -q
```

Fully offline — address-list parsing, balance parsing (incl. sat/BTC units),
resume, and the downloader's URL/index logic are all covered without network.
