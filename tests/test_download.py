"""Tests for the download integrity / resume logic (no network)."""

import io
import os
import sys
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crytocrawl import download  # noqa: E402

FULL = b"".join(b"%030x\n" % i for i in range(20))  # 20 lines, deterministic


class FakeResp:
    def __init__(self, status, headers, body):
        self.status = status
        self.headers = headers
        self._body = io.BytesIO(body)

    def read(self, n=-1):
        return self._body.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, responder):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: responder(req))


def test_complete_download_writes_done(tmp_path, monkeypatch):
    dest = tmp_path / "f.gz"
    _patch(monkeypatch, lambda req: FakeResp(200, {"Content-Length": str(len(FULL))}, FULL))
    n = download.download_file("http://x/f.gz", str(dest), progress=False)
    assert n == len(FULL)
    assert dest.read_bytes() == FULL
    assert (tmp_path / "f.gz.done").exists()


def test_short_read_raises_and_leaves_no_done(tmp_path, monkeypatch):
    dest = tmp_path / "f.gz"
    # server advertises full length but the body is cut short (dropped connection)
    _patch(monkeypatch, lambda req: FakeResp(200, {"Content-Length": str(len(FULL))}, FULL[:40]))
    with pytest.raises(IOError):
        download.download_file("http://x/f.gz", str(dest), progress=False)
    assert not (tmp_path / "f.gz.done").exists()   # resumable, not falsely "complete"
    assert dest.read_bytes() == FULL[:40]


def test_resume_completes_partial(tmp_path, monkeypatch):
    dest = tmp_path / "f.gz"
    dest.write_bytes(FULL[:40])  # a prior truncated attempt

    def responder(req):
        rng = req.headers.get("Range") or req.get_header("Range")
        assert rng == "bytes=40-"            # resumes from where it stopped
        rest = FULL[40:]
        return FakeResp(206, {"Content-Length": str(len(rest)),
                              "Content-Range": f"bytes 40-{len(FULL)-1}/{len(FULL)}"}, rest)

    _patch(monkeypatch, responder)
    n = download.download_file("http://x/f.gz", str(dest), progress=False)
    assert n == len(FULL)
    assert dest.read_bytes() == FULL
    assert (tmp_path / "f.gz.done").exists()


def test_ignored_range_restarts(tmp_path, monkeypatch):
    dest = tmp_path / "f.gz"
    dest.write_bytes(b"old partial junk")
    # server ignores Range and replies 200 with the whole file -> restart clean
    _patch(monkeypatch, lambda req: FakeResp(200, {"Content-Length": str(len(FULL))}, FULL))
    n = download.download_file("http://x/f.gz", str(dest), progress=False)
    assert n == len(FULL)
    assert dest.read_bytes() == FULL
