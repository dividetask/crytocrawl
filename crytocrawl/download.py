"""Download Blockchair dump files (resumable, polite, single-threaded).

The full output-dump history is large (one file per day since 2009, hundreds of
GB compressed), so downloads support HTTP range-resume and record nothing in
the DB themselves — they just populate a local directory that
:mod:`crytocrawl.outputs` then aggregates.

Blockchair gates the full historical archive behind an API key on some plans;
set ``BLOCKCHAIR_API_KEY`` (or pass ``api_key=``) and it is appended as
``?key=...``. The single "latest" files are generally free.
"""

from __future__ import annotations

import os
import re
import sys
import time
import urllib.request
from typing import List, Optional

BASE = "https://gz.blockchair.com/bitcoin"
_USER_AGENT = "crytocrawl/0.2 (+https://github.com/dividetask/crytocrawl)"

# Free, no-API-key single-file sources (LoyceV's public dumps). Filenames can
# change over time, so these are sensible defaults you can override with --url.
LOYCE_SOURCES = {
    # Every address that ever appeared -> the "ever held a balance" set.
    "loyce-all": "http://alladdresses.loyce.club/Bitcoin_addresses_LATEST.txt.gz",
    # Addresses with a current balance (address<TAB>balance).
    "loyce-balance": "http://addresses.loyce.club/blockchair_bitcoin_addresses_latest.tsv.gz",
}


def download_url(
    url: str, dest_dir: str, *, resume: bool = True, progress: bool = True
) -> str:
    """Download a single file ``url`` into ``dest_dir``; return its local path."""
    os.makedirs(dest_dir, exist_ok=True)
    name = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or "download"
    dest = os.path.join(dest_dir, name)
    download_file(url, dest, resume=resume, progress=progress)
    return dest


def _index_url(dataset: str) -> str:
    return f"{BASE}/{dataset}/"


def _with_key(url: str, api_key: Optional[str]) -> str:
    if not api_key:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}key={api_key}"


def parse_index(html: str, dataset: str) -> List[str]:
    """Return dump filenames for ``dataset`` referenced in a directory listing."""
    pat = re.compile(rf"blockchair_bitcoin_{re.escape(dataset)}_\d{{8}}\.tsv\.gz")
    return sorted(set(pat.findall(html)))


def list_files(dataset: str, *, api_key: Optional[str] = None, timeout: float = 60.0) -> List[str]:
    """Fetch and parse the remote directory listing for ``dataset``."""
    url = _with_key(_index_url(dataset), api_key)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        html = resp.read().decode("utf-8", "replace")
    return parse_index(html, dataset)


def _file_date(name: str) -> str:
    m = re.search(r"_(\d{8})\.tsv\.gz$", name)
    return m.group(1) if m else ""


def _filter_dates(names: List[str], since: Optional[str], until: Optional[str]) -> List[str]:
    out = []
    for n in names:
        d = _file_date(n)
        if since and d and d < since:
            continue
        if until and d and d > until:
            continue
        out.append(n)
    return out


def download_file(
    url: str, dest: str, *, api_key: Optional[str] = None, resume: bool = True,
    timeout: float = 120.0, progress: bool = True,
) -> int:
    """Download ``url`` to ``dest`` with optional byte-range resume.

    Returns the total file size in bytes. If a ``.done`` marker or a fully
    downloaded file already exists, it is left untouched.
    """
    done_marker = dest + ".done"
    if os.path.exists(done_marker) and os.path.exists(dest):
        if progress:
            print(f"  have {os.path.basename(dest)}", file=sys.stderr)
        return os.path.getsize(dest)

    full_url = _with_key(url, api_key)
    headers = {"User-Agent": _USER_AGENT}
    existing = os.path.getsize(dest) if (resume and os.path.exists(dest)) else 0
    if existing:
        headers["Range"] = f"bytes={existing}-"

    req = urllib.request.Request(full_url, headers=headers)
    mode = "ab" if existing else "wb"
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, mode) as fh:  # noqa: S310
        # If the server ignored Range (status 200) restart from scratch.
        if existing and resp.status == 200:
            fh.close()
            fh = open(dest, "wb")
        downloaded = existing
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            downloaded += len(chunk)
            if progress:
                print(f"\r  {os.path.basename(dest)}: {downloaded/1e6:,.1f} MB", end="", file=sys.stderr)
    open(done_marker, "w").close()
    if progress:
        print(f"\r  {os.path.basename(dest)}: {downloaded/1e6:,.1f} MB done", file=sys.stderr)
    return downloaded


def download_dataset(
    dataset: str, dest_dir: str, *, since: Optional[str] = None, until: Optional[str] = None,
    api_key: Optional[str] = None, sleep: float = 1.0, progress: bool = True,
) -> List[str]:
    """Download all (date-filtered) files of ``dataset`` into ``dest_dir``.

    Returns the list of local file paths. Re-running only fetches what's missing.
    """
    os.makedirs(dest_dir, exist_ok=True)
    api_key = api_key or os.environ.get("BLOCKCHAIR_API_KEY")
    names = _filter_dates(list_files(dataset, api_key=api_key), since, until)
    if progress:
        print(f"{len(names)} {dataset} file(s) to consider", file=sys.stderr)
    paths = []
    for name in names:
        dest = os.path.join(dest_dir, name)
        download_file(f"{_index_url(dataset)}{name}", dest, api_key=api_key, progress=progress)
        paths.append(dest)
        if sleep:
            time.sleep(sleep)
    return paths
