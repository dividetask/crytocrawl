"""Generate public keys and addresses from a seed, for each derivation algorithm.

Given a seed (a BIP39 mnemonic, or a raw BIP32 seed in hex), this derives the
public keys / receiving addresses that the common wallet standards would produce,
so you can verify the program reproduces a real wallet's addresses regardless of
which one created the seed:

    BIP44  m/44'/<account>'/0'/0/i  -> P2PKH        "1..."
    BIP49  m/49'/<account>'/0'/0/i  -> P2SH-P2WPKH  "3..."
    BIP84  m/84'/<account>'/0'/0/i  -> P2WPKH       "bc1q..."
    BIP86  m/86'/<account>'/0'/0/i  -> P2TR         "bc1p..."

All crypto is verified against published BIP32/BIP84/BIP86 test vectors (tests/).

This module only *derives* keys; it does not check them against anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, Dict, List, Optional

from . import hdwallet as hd
from . import walletcrypto as w

# (purpose, label, address-type, encoder taking a compressed public key)
ALGORITHMS = [
    (44, "BIP44", "P2PKH", lambda pub: w.p2pkh(pub)),
    (49, "BIP49", "P2SH-P2WPKH", w.p2sh_p2wpkh),
    (84, "BIP84", "P2WPKH", w.p2wpkh),
    (86, "BIP86", "P2TR", w.p2tr),
]


def _derive_from_master(master: hd.HDKey, count: int, account: int, change: int) -> Dict[str, List[dict]]:
    """For each algorithm, the first ``count`` entries on the chain."""
    out: Dict[str, List[dict]] = {}
    for purpose, label, kind, encode in ALGORITHMS:
        entries = []
        for i in range(count):
            path = f"m/{purpose}'/{account}'/0'/{change}/{i}"
            k, _ = hd.derive_path(master, path)
            pub_c = w.public_key_bytes(k, compressed=True)
            entries.append({
                "index": i,
                "path": path,
                "address_type": kind,
                "public_key": pub_c.hex(),
                "public_key_uncompressed": w.public_key_bytes(k, compressed=False).hex(),
                "address": encode(pub_c),
            })
        out[label] = entries
    return out


def derive_from_mnemonic(mnemonic: str, *, passphrase: str = "", count: int = 5,
                         account: int = 0, change: int = 0) -> Dict[str, List[dict]]:
    """Derive addresses for a BIP39 mnemonic (no wordlist/checksum validation, so
    any seed phrase is accepted as-is). ``passphrase`` is the optional BIP39
    25th-word passphrase."""
    master = hd.master_from_seed(hd.bip39_seed(mnemonic, passphrase))
    return _derive_from_master(master, count, account, change)


def derive_from_seed_hex(seed_hex: str, *, count: int = 5, account: int = 0,
                         change: int = 0) -> Dict[str, List[dict]]:
    """Derive addresses from a raw BIP32 seed given as hex."""
    master = hd.master_from_seed(bytes.fromhex(seed_hex.strip()))
    return _derive_from_master(master, count, account, change)


# --- CLI ---------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="seedderive", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("seed", nargs="?", help="BIP39 mnemonic (quote it), or omit to read from stdin")
    p.add_argument("--seed-hex", action="store_true", help="treat the input as a raw BIP32 seed in hex")
    p.add_argument("--passphrase", default="", help="BIP39 passphrase (the optional 25th word)")
    p.add_argument("--count", type=int, default=5, help="addresses per algorithm (default: 5)")
    p.add_argument("--account", type=int, default=0, help="account index (default: 0)")
    p.add_argument("--change", type=int, default=0, help="0 = receive chain, 1 = change (default: 0)")
    p.add_argument("--pubkeys", action="store_true", help="also print the public key hex")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)

    seed = args.seed if args.seed is not None else sys.stdin.read().strip()
    if not seed:
        print("No seed provided.", file=sys.stderr)
        return 2

    if args.seed_hex:
        result = derive_from_seed_hex(seed, count=args.count, account=args.account, change=args.change)
    else:
        result = derive_from_mnemonic(seed, passphrase=args.passphrase, count=args.count,
                                      account=args.account, change=args.change)

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    for label, entries in result.items():
        kind = entries[0]["address_type"]
        print(f"\n{label}  ({kind})")
        for e in entries:
            line = f"  {e['index']}  {e['path']:<22}  {e['address']}"
            if args.pubkeys:
                line += f"  pub={e['public_key']}"
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
