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

from . import electrum as el
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


def _entry(index: int, path: str, kind: str, address: str, pubkey: str = None) -> dict:
    return {"index": index, "path": path, "address_type": kind,
            "public_key": pubkey, "public_key_uncompressed": None, "address": address}


def _electrum_sections(mnemonic: str, passphrase: str, count: int, change: int) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    out["Electrum-Legacy"] = [
        _entry(i, path, "P2PKH", addr) for i, (path, addr)
        in enumerate(el.standard_legacy_addresses(mnemonic, passphrase=passphrase, count=count, change=change))]
    out["Electrum-Segwit"] = [
        _entry(i, path, "P2WPKH", addr) for i, (path, addr)
        in enumerate(el.standard_segwit_addresses(mnemonic, passphrase=passphrase, count=count, change=change))]
    try:
        old = el.old_addresses(mnemonic, count=count, change=change)
        out["Electrum-Old"] = [_entry(i, label, "P2PKH-uncompressed", addr)
                               for i, (label, addr) in enumerate(old)]
    except ValueError:
        # Can't decode to an old-format seed. Stay quiet for ordinary BIP39/
        # standard phrases, but if it looks like a pre-2.0 seed (multiple of 3
        # words, only 1-2 unrecognized) surface it so the scheme isn't silently
        # dropped -- better to flag than to skip.
        if change == 0:
            words = mnemonic.split()
            if len(words) >= 12 and len(words) % 3 == 0:
                unknown = el.old_unrecognized_words(mnemonic)
                if 1 <= len(unknown) <= 2:
                    print(f"note: Electrum-Old not derived -- word(s) not in the old "
                          f"wordlist: {', '.join(unknown)}. If this is a pre-2.0 Electrum "
                          f"seed, fix the spelling or pass the 32-char hex seed so its "
                          f"addresses get checked.", file=sys.stderr)
    return out


def derive_from_mnemonic(mnemonic: str, *, passphrase: str = "", count: int = 5,
                         account: int = 0, change: int = 0,
                         electrum: bool = True) -> Dict[str, List[dict]]:
    """Derive addresses for a seed across every algorithm.

    The BIP standards treat the input as a BIP39 mnemonic; Electrum algorithms
    treat it as an Electrum seed. No wordlist/checksum validation, so any phrase
    is accepted as-is. ``passphrase`` is the optional BIP39/Electrum passphrase.
    """
    master = hd.master_from_seed(hd.bip39_seed(mnemonic, passphrase))
    result = _derive_from_master(master, count, account, change)
    if electrum:
        result.update(_electrum_sections(mnemonic, passphrase, count, change))
    return result


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
    p.add_argument("--no-electrum", action="store_true", help="skip the Electrum algorithms")
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
                                      account=args.account, change=args.change,
                                      electrum=not args.no_electrum)

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
