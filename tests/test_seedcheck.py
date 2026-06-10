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


SENTINELS = ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "12c6DSiU4Rq3P4ZxziKxzrL5LmMBrzjrJX")


def _sorted_file(tmp_path, extra):
    import subprocess
    p = tmp_path / "sorted.txt"
    lines = list(SENTINELS) + list(extra)
    p.write_text("\n".join(sorted(lines, key=lambda s: s.encode())) + "\n")
    return str(p)


def test_bisect_file_yes_and_no(tmp_path):
    path = _sorted_file(tmp_path, [KNOWN_BIP84_0])
    found = seedcheck.bisect_file([KNOWN_BIP84_0, "1zzzzzNotPresentzzzzzzzzzzzzzzzzzz"], path)
    assert found == {KNOWN_BIP84_0}


def test_bisect_file_sentinel_guard(tmp_path):
    import pytest
    p = tmp_path / "nosent.txt"
    p.write_text(KNOWN_BIP84_0 + "\n")  # sorted but missing the sentinels
    with pytest.raises(RuntimeError):
        seedcheck.bisect_file([KNOWN_BIP84_0], p.as_posix())
    # --no-verify bypasses the guard
    assert seedcheck.bisect_file([KNOWN_BIP84_0], p.as_posix(), verify=False) == {KNOWN_BIP84_0}


def test_bisect_file_rejects_gzip(tmp_path):
    import gzip
    import pytest
    p = tmp_path / "f.txt"
    with gzip.open(p, "wt") as fh:
        fh.write("\n".join(SENTINELS) + "\n")
    with pytest.raises(ValueError):
        seedcheck.bisect_file([KNOWN_BIP84_0], p.as_posix())


def test_bisect_file_truncation_guard(tmp_path):
    import pytest
    # sentinels present, but NO bc1... block at all (base58-only / truncated)
    p = tmp_path / "trunc.txt"
    lines = list(SENTINELS) + ["3FkenCiXpSLqD8L79intRNXUgjRoH9sjXa"]
    p.write_text("\n".join(sorted(lines, key=lambda s: s.encode())) + "\n")
    with pytest.raises(RuntimeError, match="coverage self-check"):
        seedcheck.bisect_file([KNOWN_BIP84_0], p.as_posix())
    assert seedcheck.bisect_file([KNOWN_BIP84_0], p.as_posix(), verify=False) == set()


def test_bisect_file_trailing_non_address_lines_ok(tmp_path):
    # real-world: a bc1 block IS present, but the list has trailing lines that
    # sort AFTER it (e.g. "s-ff..."). Verify must pass and lookups still work.
    p = tmp_path / "withjunk.txt"
    lines = list(SENTINELS) + [KNOWN_BIP84_0, "s-ffsomethingthatisnotanaddress", "zzz-trailer"]
    p.write_text("\n".join(sorted(lines, key=lambda s: s.encode())) + "\n")
    found = seedcheck.bisect_file([KNOWN_BIP84_0, "1zNotPresentzzzzzzzzzzzzzzzzzzzzzz"], p.as_posix())
    assert found == {KNOWN_BIP84_0}


def test_binary_search_matches_brute_force(tmp_path):
    """Exhaustively check the binary search (incl. every line boundary) against
    a brute-force scan, so an offset landing on a boundary can't miss a line."""
    import os
    import random
    rnd = random.Random(0)
    alpha = "01239abxz-"
    p = tmp_path / "t.txt"
    bad = 0
    for _ in range(1500):
        words = sorted({"".join(rnd.choice(alpha) for _ in range(rnd.randint(1, 6)))
                        for _ in range(rnd.randint(1, 10))}, key=lambda s: s.encode())
        p.write_bytes(("\n".join(words) + "\n").encode())
        wb = [w.encode() for w in words]
        with open(p, "rb") as fh:
            size = os.fstat(fh.fileno()).st_size
            keys = wb + [("".join(rnd.choice(alpha) for _ in range(rnd.randint(1, 6)))).encode()
                         for _ in range(4)]
            for k in keys:
                if seedcheck._contains_sorted(fh, size, k) != (k in wb):
                    bad += 1
                if seedcheck._first_ge(fh, size, k) != next((w for w in wb if w >= k), b""):
                    bad += 1
    assert bad == 0


def test_check_seed_via_sorted_file(tmp_path):
    path = _sorted_file(tmp_path, [KNOWN_BIP84_0])
    used, matches = seedcheck.check_seed(ABANDON, sorted_file=path, count=4)
    assert used is True and matches[0]["address"] == KNOWN_BIP84_0


def test_cli_address_direct_check(tmp_path, capsys):
    f = tmp_path / "used.txt"
    f.write_text(KNOWN_BIP84_0 + "\n")
    rc = seedcheck.main(["-a", KNOWN_BIP84_0, "--file", str(f)])
    assert rc == 0 and capsys.readouterr().out.strip().startswith("yes")
    rc = seedcheck.main(["-a", "1SomeAddressNotInTheListXXXXXXXXXX", "--file", str(f)])
    assert rc == 1 and capsys.readouterr().out.strip().startswith("no")


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
