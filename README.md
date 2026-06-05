# crytocrawl

A local, queryable store of **every Bitcoin address that has ever held a
balance**, with each address's **current balance**. Pure Python standard
library — nothing to `pip install` to run it; data lives in one SQLite file.

## What "ever held a balance" means and how this gets it

An address has held a balance if and only if it was ever the **recipient of a
transaction output** carrying value. That fact only exists in the full history
of the chain, so the dataset is built in two phases from
[Blockchair's bulk dumps](https://gz.blockchair.com/bitcoin/):

1. **`ingest-outputs`** — aggregate the distinct `recipient` of every output
   (value > 0) across **all** daily *output* dumps since 2009. This is the
   complete "ever held a balance" set. Each address is stored with balance 0.
2. **`ingest-balances`** — apply the *addresses* dump (current non-zero
   balances) on top. Addresses that received coins in the past but have since
   spent them all stay in the table with a current balance of **0**.

> The current-balance-only addresses dump alone is **not** enough — it omits
> every spent-out address. The output-history aggregation is what makes the set
> complete.

Balances are stored as integer **satoshis** (exact) and shown as BTC floats at
query time, so no precision is lost. Presence of a row *is* the "ever held a
balance" fact.

## Requirements & expectations

- Python 3.9+. No third-party packages.
- The full output-dump history is **hundreds of GB compressed** (one file per
  day since 2009). Downloading is bandwidth/time heavy; aggregation is a
  multi-hour, single pass. The resulting SQLite DB is in the low tens of GB and
  holds **hundreds of millions** of addresses.
- Blockchair may require an API key for the full historical archive. Set
  `BLOCKCHAIR_API_KEY` and it's appended to download requests automatically.

## End-to-end

```bash
# 0. (optional) pick where the DB lives
export CRYTOCRAWL_DB=bitcoin.db

# 1. Download the full output-dump history (resumable; re-run to continue).
python3 -m crytocrawl download --dataset outputs --dir dumps/outputs
#    ...and the current-balance dump:
python3 -m crytocrawl download --dataset addresses --dir dumps/addresses

# 2. Build the 'ever held a balance' set from every output dump:
python3 -m crytocrawl ingest-outputs dumps/outputs

# 3. Apply current balances:
python3 -m crytocrawl ingest-balances --file dumps/addresses/blockchair_bitcoin_addresses_latest.tsv.gz

# 4. Query from the terminal:
python3 -m crytocrawl stats
python3 -m crytocrawl exists 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa   # -> yes/no (exit 0/1)
python3 -m crytocrawl get    1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa   # -> current balance
python3 -m crytocrawl top -n 25
python3 -m crytocrawl search bc1q --limit 50
```

Both ingest steps are **resumable/idempotent**: processed output files are
recorded, so you can stop and restart `ingest-outputs`; `ingest-balances`
resets balances first so re-running with a fresh dump always yields exact
*current* balances. Add `--json` to any query for machine-readable output.

You can also point ingest at files you've already downloaded by any means, or
let `download` fetch them. `ingest-outputs` accepts files, globs, or directories.

## Commands

| Command | What it does |
|---|---|
| `init` | Create the database file/schema |
| `download --dataset {outputs,addresses} --dir D [--since YYYYMMDD] [--until YYYYMMDD]` | Fetch dumps (resumable) |
| `ingest-outputs PATHS...` | Aggregate output dumps → every address that ever held a balance |
| `ingest-balances [--file F \| --url U] [--no-zero-first]` | Apply current balances |
| `exists ADDR` | Did this address ever hold a balance? (`yes`/`no`, exit 0/1) |
| `get ADDR` | Show an address's current balance |
| `top [-n N]` | Richest addresses by current balance |
| `search PREFIX [--limit N]` | Addresses by prefix |
| `stats` | Totals, # ever-held, # currently funded, dump dates |

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

Fully offline — output/address parsing, aggregation, resume, balance application
and the downloader's URL/index logic are all covered without network access.
