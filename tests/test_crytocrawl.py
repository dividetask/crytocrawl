"""Tests for crytocrawl. Fully offline (no network)."""

import gzip
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crytocrawl import db, download, ingest, outputs, query  # noqa: E402

# An output dump: columns include recipient + value (satoshis).
OUTPUTS = (
    "block_id\ttransaction_hash\tindex\ttime\tvalue\trecipient\ttype\n"
    "1\taa\t0\t2009\t5000000000\tAddrCoinbase\tpubkey\n"
    "100\tbb\t0\t2010\t300000000\tAddrSpent\tpubkeyhash\n"      # later spent to 0
    "100\tbb\t1\t2010\t100000000\tAddrFunded\tpubkeyhash\n"
    "150\tcc\t0\t2011\t0\tAddrOpReturn\tnulldata\n"            # value 0 -> skipped
    "150\tcc\t1\t2011\t250\t\tnonstandard\n"                   # empty recipient -> skipped
    "200\tdd\t0\t2012\t300000000\tAddrSpent\tpubkeyhash\n"     # duplicate recipient
)

# An addresses dump (current balances). AddrSpent is absent => current balance 0.
BALANCES = (
    "address\tbalance\n"
    "AddrCoinbase\t5000000000\n"
    "AddrFunded\t100000000\n"
)


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    yield c
    c.close()


def _write(path, text, gz=False):
    if gz:
        with gzip.open(path, "wt") as fh:
            fh.write(text)
    else:
        path.write_text(text)
    return str(path)


# ---- outputs aggregation (the 'ever held a balance' set) --------------------

def test_iter_recipients_filters_zero_and_empty():
    recs = list(outputs.iter_recipients(OUTPUTS.splitlines()))
    assert recs == ["AddrCoinbase", "AddrSpent", "AddrFunded", "AddrSpent"]


def test_ingest_outputs_builds_ever_held_set(tmp_path, conn):
    f = _write(tmp_path / "blockchair_bitcoin_outputs_20120101.tsv", OUTPUTS)
    outputs.ingest_outputs(conn, [f], progress=False)
    addrs = {r["address"] for r in query.search_addresses(conn, "Addr", 100)}
    assert addrs == {"AddrCoinbase", "AddrSpent", "AddrFunded"}
    assert query.ever_held(conn, "AddrSpent") is True
    assert query.ever_held(conn, "NeverSeen") is False
    # No balances applied yet -> everything reads 0.
    assert query.get_address(conn, "AddrSpent")["balance_sat"] == 0


def test_ingest_outputs_gz_and_resume(tmp_path, conn):
    f = _write(tmp_path / "blockchair_bitcoin_outputs_20120101.tsv.gz", OUTPUTS, gz=True)
    scanned = outputs.ingest_output_file(conn, f, progress=False)
    assert scanned == 4  # 4 kept recipients (2 skipped)
    # Re-running the same file is a no-op (recorded in ingested_files).
    again = outputs.ingest_output_file(conn, f, progress=False)
    assert again == 0
    assert db.get_meta(conn, "outputs_through") == "20120101"


def test_discover_files_sorted_by_date(tmp_path):
    a = _write(tmp_path / "blockchair_bitcoin_outputs_20120301.tsv", "x")
    b = _write(tmp_path / "blockchair_bitcoin_outputs_20120101.tsv", "x")
    found = outputs.discover_files([str(tmp_path)])
    assert [os.path.basename(p) for p in found] == [
        "blockchair_bitcoin_outputs_20120101.tsv",
        "blockchair_bitcoin_outputs_20120301.tsv",
    ]


def test_outputs_header_without_value_keeps_all(conn):
    text = "block_id\trecipient\nA\tFoo\nB\tBar\n"
    recs = list(outputs.iter_recipients(text.splitlines()))
    assert recs == ["Foo", "Bar"]


def test_outputs_missing_recipient_column_errors():
    with pytest.raises(ValueError):
        list(outputs.iter_recipients(["block_id\tvalue\n", "1\t2\n"]))


# ---- current balances -------------------------------------------------------

def test_ingest_balances_sets_current_and_zeroes_spent(tmp_path, conn):
    of = _write(tmp_path / "blockchair_bitcoin_outputs_20120101.tsv", OUTPUTS)
    outputs.ingest_outputs(conn, [of], progress=False)
    bf = _write(tmp_path / "blockchair_bitcoin_addresses_latest.tsv", BALANCES)
    n = ingest.ingest_balances(conn, file=bf, progress=False)
    assert n == 2
    assert query.get_address(conn, "AddrFunded")["balance_sat"] == 100000000
    assert query.get_address(conn, "AddrFunded")["balance_btc"] == 1.0
    # AddrSpent held a balance once, now spent out -> present but 0.
    assert query.ever_held(conn, "AddrSpent") is True
    assert query.get_address(conn, "AddrSpent")["balance_sat"] == 0


def test_ingest_balances_zero_first_on_rerun(tmp_path, conn):
    of = _write(tmp_path / "blockchair_bitcoin_outputs_20120101.tsv", OUTPUTS)
    outputs.ingest_outputs(conn, [of], progress=False)
    bf = _write(tmp_path / "b1.tsv", BALANCES)
    ingest.ingest_balances(conn, file=bf, progress=False)
    # New dump where AddrFunded is now spent out (absent); AddrCoinbase changed.
    bf2 = _write(tmp_path / "b2.tsv", "address\tbalance\nAddrCoinbase\t42\n")
    ingest.ingest_balances(conn, file=bf2, progress=False)
    assert query.get_address(conn, "AddrCoinbase")["balance_sat"] == 42
    assert query.get_address(conn, "AddrFunded")["balance_sat"] == 0  # reset by zero_first


def test_balances_gz(tmp_path, conn):
    bf = _write(tmp_path / "addr.tsv.gz", BALANCES, gz=True)
    ingest.ingest_balances(conn, file=bf, progress=False)
    assert query.get_address(conn, "AddrCoinbase")["balance_sat"] == 5000000000


# ---- queries / stats --------------------------------------------------------

def test_top_and_stats(tmp_path, conn):
    of = _write(tmp_path / "blockchair_bitcoin_outputs_20120101.tsv", OUTPUTS)
    outputs.ingest_outputs(conn, [of], progress=False)
    bf = _write(tmp_path / "addr.tsv", BALANCES)
    ingest.ingest_balances(conn, file=bf, progress=False)

    top = query.top_addresses(conn, 2)
    assert [r["address"] for r in top] == ["AddrCoinbase", "AddrFunded"]

    s = query.stats(conn)
    assert s["addresses_ever_held"] == 3
    assert s["currently_funded"] == 2
    assert s["total_balance_sat"] == 5000000000 + 100000000
    assert s["outputs_through"] == "20120101"


# ---- downloader (pure logic; no network) ------------------------------------

def test_parse_index_extracts_filenames():
    html = (
        '<a href="blockchair_bitcoin_outputs_20090103.tsv.gz">x</a> '
        '<a href="blockchair_bitcoin_outputs_20090104.tsv.gz">y</a> '
        '<a href="other.txt">z</a>'
    )
    assert download.parse_index(html, "outputs") == [
        "blockchair_bitcoin_outputs_20090103.tsv.gz",
        "blockchair_bitcoin_outputs_20090104.tsv.gz",
    ]


def test_filter_dates():
    names = [
        "blockchair_bitcoin_outputs_20090103.tsv.gz",
        "blockchair_bitcoin_outputs_20150101.tsv.gz",
        "blockchair_bitcoin_outputs_20200101.tsv.gz",
    ]
    out = download._filter_dates(names, since="20100101", until="20190101")
    assert out == ["blockchair_bitcoin_outputs_20150101.tsv.gz"]


def test_with_key():
    assert download._with_key("http://x/y/", "K") == "http://x/y/?key=K"
    assert download._with_key("http://x/y/?a=1", "K") == "http://x/y/?a=1&key=K"
    assert download._with_key("http://x/y/", None) == "http://x/y/"
