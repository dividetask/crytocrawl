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

## Deriving addresses from a seed (`seedderive`)

A separate, self-contained tool (installed alongside `crytocrawl`) that turns a
seed into the public keys / addresses each wallet standard would produce, so you
can confirm it reproduces a real wallet's addresses regardless of which one made
the seed. It only *derives* — it checks nothing against anything.

```bash
seedderive "your twelve or twenty-four word mnemonic here" --count 5
seedderive "<mnemonic>" --passphrase "optional 25th word" --pubkeys
seedderive --seed-hex "000102...0f"        # raw BIP32 seed instead of a mnemonic
seedderive "<mnemonic>" --json             # machine-readable
```

For each algorithm it prints the first N receiving addresses and their paths:

| Algorithm | Path | Address type |
|---|---|---|
| BIP44 | `m/44'/<account>'/0'/0/i` | P2PKH `1...` |
| BIP49 | `m/49'/<account>'/0'/0/i` | P2SH-P2WPKH `3...` |
| BIP84 | `m/84'/<account>'/0'/0/i` | P2WPKH `bc1q...` |
| BIP86 | `m/86'/<account>'/0'/0/i` | P2TR `bc1p...` |
| Electrum legacy | `m/<change>/i` (salt `electrum`) | P2PKH `1...` |
| Electrum segwit | `m/0'/<change>/i` (salt `electrum`) | P2WPKH `bc1q...` |
| Electrum old (pre-2.0) | non-BIP32 stretch+sequence | P2PKH `1...` (uncompressed) |

`--account`/`--change` select the account index and receive(0)/change(1) chain;
`--no-electrum` skips the Electrum algorithms.

**Electrum notes.** Electrum doesn't use BIP39 — it stretches the seed with the
PBKDF2 salt `"electrum"` and uses its own paths, so the same phrase produces
different addresses than the BIP rows. The **old (pre-2.0)** scheme isn't BIP32
at all; enter either the 12 old-format words or the 32-char hex seed (both give
the same result). The bundled old wordlist is validated by Electrum's test
vector, but for a high-stakes recovery you can pass the hex seed (which bypasses
the wordlist entirely) or supply Electrum's official wordlist.

The crypto is pinned to published test vectors — BIP32 / BIP49 / BIP84 / BIP86,
and Electrum's own legacy / segwit / old seed vectors (`tests/test_derive.py`).
If one of your wallets still doesn't match (e.g. a 2FA Electrum wallet, or a
different account layout), tell me the wallet and I'll add its exact scheme.

As a library:

```python
from crytocrawl.derive import derive_from_mnemonic
r = derive_from_mnemonic("abandon abandon ... about", count=5)
print(r["BIP84"][0]["address"], r["BIP84"][0]["public_key"])
```

## Has a seed ever been used? (`seedcheck`)

Give it a seed and it derives the **first 4 receiving + first 4 change
addresses of every algorithm** (BIP44/49/84/86 and Electrum legacy/segwit/old —
both chains), checks them against the used-address list, and answers `yes`/`no`.

```bash
seedcheck "<your seed>"                 # prints yes or no
seedcheck "<your seed>" -v              # also shows which address/path matched
seedcheck "<your seed>" --count 10      # check the first 10 of each chain
seedcheck "<your seed>" --passphrase "x" --account 1
seedcheck --seed-file candidates.txt    # one seed per line -> "yes/no  <seed>"
```

- Default list: `dumps/all_Bitcoin_addresses_ever_used_sorted.txt.gz` (override
  with `--file`). It streams the file once; for many checks, load the file into
  a crytocrawl SQLite DB and pass `--db bitcoin.db` for fast index lookups
  instead of a full scan.
- Exit status: `0` = used (yes), `1` = not used (no), `2` = error — so you can
  script it. With multiple seeds it prints one line each and exits `0`.
- "Used" means at least one derived address has appeared on-chain. Look the
  matched address up (`crytocrawl get <addr>`, or any explorer) to see its
  current balance.

## Tests

```bash
python3 -m pytest -q
```

Fully offline — address-list parsing, balance parsing (incl. sat/BTC units),
resume, and the downloader's URL/index logic are all covered without network.
