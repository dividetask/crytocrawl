"""Tests for the seed 'has it ever been used?' checker (offline)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crytocrawl import seedcheck  # noqa: E402

ABANDON = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
# Known BIP84 receive[0] / [1] for ABANDON (official vectors).
KNOWN_BIP84_0 = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"


def test_addresses_include_receive_and_change():
    addrs = seedcheck.addresses_for_seed(ABANDON, count=4)
    # 4 BIP standards x 4 indices x 2 chains = 32, plus electrum legacy/segwit
    # (4x2 each) = 16 -> 48 (old is skipped: ABANDON isn't an old seed).
    assert KNOWN_BIP84_0 in addrs
    # receive chain present
    paths = {p for (_a, p) in addrs.values()}
    assert any(p.endswith("/0/0") for p in paths)   # receive index 0
    assert any("/1/0" in p for p in paths)          # change index 0


def test_check_seed_yes(tmp_path):
    f = tmp_path / "used.txt"
    f.write_text(KNOWN_BIP84_0 + "\n")
    used, matches = seedcheck.check_seed(ABANDON, addresses_file=str(f), count=4)
    assert used is True
    assert any(m["address"] == KNOWN_BIP84_0 for m in matches)
    assert matches[0]["algorithm"] == "BIP84"


def test_check_seed_no(tmp_path):
    f = tmp_path / "used.txt"
    f.write_text("1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n")
    used, matches = seedcheck.check_seed(ABANDON, addresses_file=str(f), count=4)
    assert used is False and matches == []


def test_change_address_match(tmp_path):
    # take an actual change address (chain 1) and ensure it's detected
    addrs = seedcheck.addresses_for_seed(ABANDON, count=4)
    change_addr = next(a for a, (_algo, p) in addrs.items() if "/1/0" in p)
    f = tmp_path / "used.txt"
    f.write_text(change_addr + "\n")
    used, matches = seedcheck.check_seed(ABANDON, addresses_file=str(f), count=4)
    assert used is True
    assert matches[0]["address"] == change_addr


def test_cli_yes_no_and_exit_codes(tmp_path, capsys):
    f = tmp_path / "used.txt"
    f.write_text(KNOWN_BIP84_0 + "\n")
    rc = seedcheck.main([ABANDON, "--file", str(f)])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "yes"

    f2 = tmp_path / "empty.txt"
    f2.write_text("1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n")
    rc = seedcheck.main([ABANDON, "--file", str(f2)])
    assert rc == 1
    assert capsys.readouterr().out.strip() == "no"


def test_cli_multiple_seeds(tmp_path, capsys):
    f = tmp_path / "used.txt"
    f.write_text(KNOWN_BIP84_0 + "\n")
    seeds = tmp_path / "seeds.txt"
    seeds.write_text(ABANDON + "\n" + "legal winner thank year wave sausage worth useful legal winner thank yellow\n")
    rc = seedcheck.main(["--seed-file", str(seeds), "--file", str(f)])
    assert rc == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].startswith("yes")
    assert lines[1].startswith("no")
