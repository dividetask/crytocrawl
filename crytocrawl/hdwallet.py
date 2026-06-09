"""Minimal BIP32 / BIP39 hierarchical-deterministic derivation (pure Python).

Turns a mnemonic/seed into addresses along the standard account paths:

    BIP44  m/44'/0'/0'/0/i  -> P2PKH   ("1...")
    BIP49  m/49'/0'/0'/0/i  -> P2SH-P2WPKH ("3...")
    BIP84  m/84'/0'/0'/0/i  -> P2WPKH  ("bc1q...")
    BIP86  m/86'/0'/0'/0/i  -> P2TR    ("bc1p...")

Validated against the official BIP84/BIP86 test vectors in the test suite.
"""

from __future__ import annotations

import hashlib
import hmac
import unicodedata
from typing import List, Tuple

from . import walletcrypto as w

_N = w._N
HARDENED = 0x80000000

# (priv_int, chain_code_bytes)
HDKey = Tuple[int, bytes]


def bip39_seed(mnemonic: str, passphrase: str = "") -> bytes:
    """BIP39 mnemonic -> 64-byte seed (no wordlist/checksum validation, so any
    phrase you remember can be tried as-is)."""
    m = unicodedata.normalize("NFKD", mnemonic)
    salt = unicodedata.normalize("NFKD", "mnemonic" + passphrase).encode("utf-8")
    return hashlib.pbkdf2_hmac("sha512", m.encode("utf-8"), salt, 2048, 64)


def master_from_seed(seed: bytes) -> HDKey:
    I = hmac.new(b"Bitcoin seed", seed, hashlib.sha512).digest()
    return int.from_bytes(I[:32], "big") % _N, I[32:]


def ckd_priv(parent: HDKey, index: int) -> HDKey:
    k_par, c_par = parent
    if index & HARDENED:
        data = b"\x00" + k_par.to_bytes(32, "big") + index.to_bytes(4, "big")
    else:
        data = w.public_key_bytes(k_par, compressed=True) + index.to_bytes(4, "big")
    I = hmac.new(c_par, data, hashlib.sha512).digest()
    child_k = (int.from_bytes(I[:32], "big") + k_par) % _N
    return child_k, I[32:]


def _parse_path(path: str) -> List[int]:
    out: List[int] = []
    for part in path.strip().split("/"):
        if part in ("m", ""):
            continue
        hardened = part.endswith("'") or part.endswith("h")
        n = int(part.rstrip("'h"))
        out.append(n + HARDENED if hardened else n)
    return out


def derive_path(master: HDKey, path: str) -> HDKey:
    key = master
    for index in _parse_path(path):
        key = ckd_priv(key, index)
    return key
