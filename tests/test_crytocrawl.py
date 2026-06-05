"""Tests for crytocrawl. No network access required (the API is mocked)."""

import gzip
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crytocrawl import db, enrich, ingest, query  # noqa: E402

SAMPLE = (
    "address\tbalance\n"
    "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa\t6857585654\n"
    "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4\t100000000\n"
    "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy\t250\n"
)


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    yield c
    c.close()


def _gz_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(text.encode())
    return buf.getvalue()


def test_parse_rows_skips_header_and_blank():
    rows = list(ingest.parse_rows(SAMPLE.splitlines()))
    assert rows == [
        ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", 6857585654),
        ("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4", 100000000),
        ("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", 250),
    ]


def test_ingest_from_plain_file(tmp_path, conn):
    f = tmp_path / "dump.tsv"
    f.write_text(SAMPLE)
    n = ingest.ingest_dump(conn, file=str(f), progress=False)
    assert n == 3
    assert query.count_addresses(conn) == 3
    row = query.get_address(conn, "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
    assert row["balance_sat"] == 100000000
    assert row["balance_btc"] == 1.0
    assert row["tx_count"] is None  # not enriched yet


def test_ingest_from_gz_file(tmp_path, conn):
    f = tmp_path / "dump.tsv.gz"
    f.write_bytes(_gz_bytes(SAMPLE))
    n = ingest.ingest_dump(conn, file=str(f), progress=False)
    assert n == 3
    assert query.get_address(conn, "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")["balance_sat"] == 250


def test_ingest_is_idempotent_and_updates(tmp_path, conn):
    f = tmp_path / "dump.tsv"
    f.write_text(SAMPLE)
    ingest.ingest_dump(conn, file=str(f), progress=False)
    # New dump: same address, changed balance.
    f.write_text("address\tbalance\n1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa\t42\n")
    ingest.ingest_dump(conn, file=str(f), progress=False)
    assert query.count_addresses(conn) == 3  # old rows preserved
    assert query.get_address(conn, "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")["balance_sat"] == 42


def test_zero_missing(tmp_path, conn):
    f = tmp_path / "dump.tsv"
    f.write_text(SAMPLE)
    ingest.ingest_dump(conn, file=str(f), progress=False)
    f.write_text("address\tbalance\n3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy\t999\n")
    ingest.ingest_dump(conn, file=str(f), progress=False, zero_missing=True)
    assert query.get_address(conn, "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")["balance_sat"] == 0
    assert query.get_address(conn, "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")["balance_sat"] == 999


def test_top_and_stats(tmp_path, conn):
    f = tmp_path / "dump.tsv"
    f.write_text(SAMPLE)
    ingest.ingest_dump(conn, file=str(f), progress=False)
    top = query.top_addresses(conn, 2)
    assert [r["address"] for r in top] == [
        "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
    ]
    s = query.stats(conn)
    assert s["addresses"] == 3
    assert s["total_balance_sat"] == 6857585654 + 100000000 + 250
    assert s["enriched_with_tx_count"] == 0


def test_search_prefix(tmp_path, conn):
    f = tmp_path / "dump.tsv"
    f.write_text(SAMPLE)
    ingest.ingest_dump(conn, file=str(f), progress=False)
    res = query.search_addresses(conn, "bc1", 10)
    assert len(res) == 1
    assert res[0]["address"].startswith("bc1")


def test_enrich_with_mock_fetcher(tmp_path, conn):
    f = tmp_path / "dump.tsv"
    f.write_text(SAMPLE)
    ingest.ingest_dump(conn, file=str(f), progress=False)

    calls = []

    def fake_fetcher(addr):
        calls.append(addr)
        return {"balance_sat": 777, "tx_count": 5}

    pend = enrich.pending_addresses(conn, 10)
    assert len(pend) == 3
    n = enrich.enrich_addresses(conn, pend, fetcher=fake_fetcher)
    assert n == 3
    row = query.get_address(conn, "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
    assert row["tx_count"] == 5
    assert row["balance_sat"] == 777
    assert enrich.pending_addresses(conn, 10) == []


def test_enrich_upserts_new_watchlist_address(conn):
    def fake_fetcher(addr):
        return {"balance_sat": 12345, "tx_count": 9}

    n = enrich.enrich_addresses(conn, ["1NewWatchedAddr"], fetcher=fake_fetcher)
    assert n == 1
    row = query.get_address(conn, "1NewWatchedAddr")
    assert row["tx_count"] == 9
    assert row["balance_sat"] == 12345


def test_fetch_retry_gives_up_on_bad_address():
    import urllib.error

    def boom(addr):
        raise urllib.error.HTTPError(addr, 400, "Bad Request", {}, None)

    assert enrich._fetch_with_retry(boom, "garbage") is None


def test_parse_address_stats_payload():
    payload = {
        "chain_stats": {"funded_txo_sum": 1000, "spent_txo_sum": 200, "tx_count": 4},
        "mempool_stats": {"funded_txo_sum": 0, "spent_txo_sum": 0, "tx_count": 1},
    }
    import json as _json
    import urllib.request

    class FakeResp:
        def __init__(self, data):
            self._data = data
        def read(self):
            return self._data
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        return FakeResp(_json.dumps(payload).encode())

    orig = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        stats = enrich.fetch_address_stats("1abc")
    finally:
        urllib.request.urlopen = orig
    assert stats == {"balance_sat": 800, "tx_count": 5}
