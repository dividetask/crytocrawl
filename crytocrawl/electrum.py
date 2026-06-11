"""Electrum address derivation: standard (legacy & segwit) and old (pre-2.0).

Electrum differs from BIP39/BIP44 in two ways:

  * Seed stretching uses the PBKDF2 salt ``"electrum"`` (not ``"mnemonic"``).
  * Paths are Electrum-specific:
        standard legacy  -> m/<change>/<i>     (P2PKH,  xpub)
        standard segwit  -> m/0'/<change>/<i>  (P2WPKH, zpub)
  * Old (pre-2.0) wallets are NOT BIP32 at all: a 128-bit seed (12 words from a
    1626-word list, or 32 hex chars) is stretched with 100k SHA-256 rounds to a
    master secret, and each address is derived by an additive sequence off the
    master public key. Addresses are P2PKH with *uncompressed* keys.

All three are pinned to Electrum's own published test vectors in tests/.
Derivation only — nothing is checked against anything here.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import List, Optional, Tuple

from . import hdwallet as hd
from . import walletcrypto as w


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKD", text).split())


# --- standard (Electrum 2.x, BIP32-based) ------------------------------------

def electrum_seed(mnemonic: str, passphrase: str = "") -> bytes:
    """Electrum standard mnemonic -> 64-byte seed (PBKDF2 salt 'electrum')."""
    salt = ("electrum" + _normalize(passphrase)).encode("utf-8")
    return hashlib.pbkdf2_hmac("sha512", _normalize(mnemonic).encode("utf-8"), salt, 2048, 64)


def standard_legacy_addresses(mnemonic: str, *, passphrase: str = "", count: int = 5,
                              change: int = 0) -> List[Tuple[str, str]]:
    """(path, address) for an Electrum standard *legacy* wallet (P2PKH, m/<change>/i)."""
    master = hd.master_from_seed(electrum_seed(mnemonic, passphrase))
    out = []
    for i in range(count):
        path = f"m/{change}/{i}"
        k, _ = hd.derive_path(master, path)
        out.append((path, w.p2pkh(w.public_key_bytes(k, compressed=True))))
    return out


def standard_segwit_addresses(mnemonic: str, *, passphrase: str = "", count: int = 5,
                              change: int = 0) -> List[Tuple[str, str]]:
    """(path, address) for an Electrum standard *segwit* wallet (P2WPKH, m/0'/<change>/i)."""
    master = hd.master_from_seed(electrum_seed(mnemonic, passphrase))
    out = []
    for i in range(count):
        path = f"m/0'/{change}/{i}"
        k, _ = hd.derive_path(master, path)
        out.append((path, w.p2wpkh(w.public_key_bytes(k, compressed=True))))
    return out


# --- old (pre-2.0, non-BIP32) ------------------------------------------------

def _is_hex_seed(s: str) -> bool:
    s = s.strip()
    if len(s) != 32:
        return False
    try:
        int(s, 16)
        return True
    except ValueError:
        return False


def old_seed_to_hex(seed: str, wordlist: Optional[List[str]] = None) -> str:
    """Decode an old-format input to its 32-char hex seed.

    Accepts either the 32-hex-char seed directly, or a 12-word old mnemonic
    (decoded against ``wordlist``, defaulting to the bundled Electrum list).
    """
    seed = seed.strip()
    if _is_hex_seed(seed):
        return seed.lower()
    if wordlist is None:
        from .electrum_wordlist import OLD_WORDS
        wordlist = OLD_WORDS
    words = _normalize(seed).lower().split()
    if len(words) % 3 != 0:
        raise ValueError("old Electrum seed must be a multiple of 3 words (usually 12)")
    n = len(wordlist)
    idx = {wrd: i for i, wrd in enumerate(wordlist)}
    out = ""
    for i in range(len(words) // 3):
        try:
            w1 = idx[words[3 * i]]
            w2 = idx[words[3 * i + 1]] % n
            w3 = idx[words[3 * i + 2]] % n
        except KeyError as e:
            raise ValueError(f"word not in old Electrum wordlist: {e.args[0]!r}")
        x = w1 + n * ((w2 - w1) % n) + n * n * ((w3 - w2) % n)
        out += "%08x" % x
    return out


def old_unrecognized_words(seed: str, wordlist: Optional[List[str]] = None) -> List[str]:
    """Words in a (would-be old) seed phrase that are not in the old wordlist.

    Empty for a hex seed or a fully-decodable old phrase. A small non-empty list
    (1-2 words) usually means a real old seed with a typo or a wordlist gap.
    """
    if _is_hex_seed(seed.strip()):
        return []
    if wordlist is None:
        from .electrum_wordlist import OLD_WORDS
        wordlist = OLD_WORDS
    known = set(wordlist)
    return [w for w in _normalize(seed).lower().split() if w not in known]


def _old_stretch(hex_seed: str) -> int:
    seed = hex_seed.encode("utf-8")  # the ASCII of the hex string, per Electrum
    x = seed
    for _ in range(100_000):
        x = hashlib.sha256(x + seed).digest()
    return int.from_bytes(x, "big")


def _old_master_point(hex_seed: str):
    return w._scalar_mul(_old_stretch(hex_seed))  # secexp * G


def _old_sequence(mpk_point, for_change: int, n: int) -> int:
    mpk_bytes = mpk_point[0].to_bytes(32, "big") + mpk_point[1].to_bytes(32, "big")
    digest = w.sha256(w.sha256(f"{n}:{for_change}:".encode("ascii") + mpk_bytes))
    return int.from_bytes(digest, "big")


def old_addresses(seed: str, *, count: int = 5, change: int = 0,
                  wordlist: Optional[List[str]] = None) -> List[Tuple[str, str]]:
    """(label, address) for an old (pre-2.0) Electrum wallet (P2PKH, uncompressed)."""
    hex_seed = old_seed_to_hex(seed, wordlist)
    mpk = _old_master_point(hex_seed)
    out = []
    for i in range(count):
        z = _old_sequence(mpk, change, i)
        pt = w._point_add(mpk, w._scalar_mul(z))
        pub = b"\x04" + pt[0].to_bytes(32, "big") + pt[1].to_bytes(32, "big")
        out.append((f"old:{change}/{i}", w.p2pkh(pub)))
    return out
