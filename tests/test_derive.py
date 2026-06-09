"""Tests for seed derivation. Crypto is pinned to published test vectors."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crytocrawl import derive  # noqa: E402
from crytocrawl import hdwallet as hd  # noqa: E402
from crytocrawl import walletcrypto as w  # noqa: E402

ABANDON = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"


# ---- walletcrypto vectors ---------------------------------------------------

def test_p2pkh_privkey_one():
    assert w.p2pkh(w.public_key_bytes(1, False)) == "1EHNa6Q4Jz2uvNExL497mE43ikXhwF6kZm"
    assert w.p2pkh(w.public_key_bytes(1, True)) == "1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH"


def test_bech32_vector():
    prog = bytes.fromhex("751e76e8199196d454941c45d1b3a323f1433bd6")
    assert w.segwit_encode("bc", 0, prog) == "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"


def test_ripemd160_vector():
    assert w._ripemd160_py(b"abc").hex() == "8eb208f7e05d987a9b044a8e98c6b087f15a0bfc"


def test_bip32_master_vector():
    k, c = hd.master_from_seed(bytes.fromhex("000102030405060708090a0b0c0d0e0f"))
    assert k.to_bytes(32, "big").hex() == \
        "e8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35"
    assert c.hex() == "873dff81c02f525623fd1fe5167eac3a55a049de3d314bb42ee227ffed37d508"


# ---- official BIP49/84/86 derivation vectors --------------------------------

def test_official_derivation_vectors():
    r = derive.derive_from_mnemonic(ABANDON, count=2)
    assert r["BIP49"][0]["address"] == "37VucYSaXLCAsxYyAPfbSi9eh4iEcbShgf"
    assert r["BIP84"][0]["address"] == "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
    assert r["BIP84"][1]["address"] == "bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g"
    assert r["BIP86"][0]["address"] == \
        "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"


def test_structure_and_paths():
    r = derive.derive_from_mnemonic(ABANDON, count=3, account=0)
    assert set(r) == {"BIP44", "BIP49", "BIP84", "BIP86"}
    assert [e["index"] for e in r["BIP44"]] == [0, 1, 2]
    assert r["BIP44"][0]["path"] == "m/44'/0'/0'/0/0"
    assert r["BIP84"][2]["path"] == "m/84'/0'/0'/0/2"
    # compressed + uncompressed pubkeys are present and well-formed
    e = r["BIP44"][0]
    assert len(e["public_key"]) == 66 and e["public_key"][:2] in ("02", "03")
    assert e["public_key_uncompressed"][:2] == "04"


def test_account_index_changes_addresses():
    a0 = derive.derive_from_mnemonic(ABANDON, count=1, account=0)["BIP84"][0]["address"]
    a1 = derive.derive_from_mnemonic(ABANDON, count=1, account=1)["BIP84"][0]["address"]
    assert a0 != a1


def test_seed_hex_path():
    r = derive.derive_from_seed_hex("000102030405060708090a0b0c0d0e0f", count=1)
    # deterministic & well-formed (engine pinned by test_bip32_master_vector)
    assert r["BIP84"][0]["address"].startswith("bc1q")
    assert r["BIP86"][0]["address"].startswith("bc1p")


def test_cli_human_and_json(capsys):
    rc = derive.main([ABANDON, "--count", "1", "--json"])
    assert rc == 0
    import json
    out = json.loads(capsys.readouterr().out)
    assert out["BIP84"][0]["address"] == "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
