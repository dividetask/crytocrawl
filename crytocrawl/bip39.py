"""BIP39 wordlist membership and checksum validation, used to *identify* a seed
(not to derive it). A valid checksum means the 12/24 words are internally
consistent -- a strong signal the phrase was transcribed correctly.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import List, Optional


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKD", text).split()).lower()


def _words() -> List[str]:
    from .bip39_wordlist import BIP39_WORDS
    return BIP39_WORDS


def bip39_unrecognized_words(mnemonic: str) -> List[str]:
    known = set(_words())
    return [w for w in _normalize(mnemonic).split() if w not in known]


def bip39_checksum_valid(mnemonic: str) -> bool:
    """True iff the mnemonic is a well-formed BIP39 phrase with a valid checksum."""
    words = _normalize(mnemonic).split()
    if len(words) not in (12, 15, 18, 21, 24):
        return False
    index = {w: i for i, w in enumerate(_words())}
    try:
        bits = "".join(f"{index[w]:011b}" for w in words)
    except KeyError:
        return False
    ent_len = len(words) * 11 * 32 // 33   # entropy bits
    cs_len = len(words) * 11 - ent_len     # checksum bits
    entropy = int(bits[:ent_len], 2).to_bytes(ent_len // 8, "big")
    digest = hashlib.sha256(entropy).digest()
    expected = "".join(f"{b:08b}" for b in digest)[:cs_len]
    return bits[ent_len:] == expected
