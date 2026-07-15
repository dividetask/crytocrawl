"""Identify what kind of seed a phrase is, to explain a surprising result.

Reports which wordlist(s) the words belong to, whether the BIP39 checksum is
valid, whether it's a valid Electrum 2.x seed, and whether it decodes as an old
(pre-2.0) Electrum seed -- then a plain-language verdict.
"""

from __future__ import annotations

from typing import Optional

from . import bip39
from . import electrum as el


def identify_seed(seed: str) -> dict:
    words = seed.split()
    bip39_unknown = bip39.bip39_unrecognized_words(seed)
    old_unknown = el.old_unrecognized_words(seed)
    try:
        el.old_seed_to_hex(seed)
        old_decodable = True
    except ValueError:
        old_decodable = False
    return {
        "word_count": len(words),
        "all_words_bip39": not bip39_unknown,
        "bip39_unrecognized": bip39_unknown,
        "bip39_checksum_valid": bip39.bip39_checksum_valid(seed),
        "electrum_seed_type": el.electrum_seed_type(seed),
        "all_words_old_electrum": not old_unknown,
        "old_electrum_decodable": old_decodable,
    }


def describe_seed(seed: str) -> str:
    r = identify_seed(seed)
    lines = [f"word count: {r['word_count']}"]

    if r["bip39_checksum_valid"]:
        lines.append("verdict: valid BIP39 seed (checksum OK) -> a standard/hardware "
                     "wallet. Check BIP44/49/84/86 (seedcheck already does).")
    elif r["electrum_seed_type"]:
        lines.append(f"verdict: valid Electrum 2.x '{r['electrum_seed_type']}' seed -> "
                     "the Electrum-Legacy/Segwit schemes apply.")
    elif r["old_electrum_decodable"]:
        lines.append("verdict: decodes as an old (pre-2.0) Electrum seed -> the "
                     "Electrum-Old scheme applies.")
    elif r["all_words_bip39"]:
        lines.append("verdict: all words are BIP39 words, but the CHECKSUM IS INVALID. "
                     "That almost always means a transcription error -- a wrong, "
                     "misspelled, swapped, or out-of-order word. Every derived address "
                     "would then be wrong, which explains a 'no' on a funded wallet. "
                     "Double-check the phrase word by word against the original.")
    else:
        bad = ", ".join(r["bip39_unrecognized"]) or "(none)"
        lines.append("verdict: not a valid BIP39, Electrum 2.x, or old-Electrum seed. "
                     f"Words not in the BIP39 list: {bad}. Likely a transcription error "
                     "or a different wallet's wordlist.")

    if r["bip39_unrecognized"] and not r["all_words_bip39"]:
        lines.append(f"BIP39: {len(r['bip39_unrecognized'])} word(s) not in the BIP39 list: "
                     f"{', '.join(r['bip39_unrecognized'])}")
    return "\n".join(lines)
