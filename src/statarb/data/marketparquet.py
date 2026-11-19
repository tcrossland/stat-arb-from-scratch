"""MarketParquet's archive, the second price source (decision record 0008).

The archive is one parquet file per trading day and dataset, holding every
symbol that traded that day. A download asks the documented API for a year's
file list with one request, fetches each file from the address the list gives,
and keeps the bytes as served under `<dataset>/<year>/<date>.parquet` in a
snapshot of layout `days`. Files are fetched several at once, since each takes
about half a second to arrive whatever the connection, and all requests
together stay under the key's rate limit. Nothing is converted on the way in: the archive is
corrected often and carries no version, so the snapshot is the only record of
what was served.

Only the daily stock and ETF datasets are ever asked for (`ASSETS`). The key is
read from the environment and sent to the API's host alone, never to the
address a file is fetched from.

Reading is by day, not by ticker: `read_days` makes one long table of the days
in a window. A symbol is kept exactly as served, with its `-DELISTED` suffix,
which says what happened after the day of the bar: it is part of a security's
key and must never be an input to a decision (docs/phases/phase-07/brief.md).
Prices are adjusted for splits as of the download and hold no dividends.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from statarb.data import cache
from statarb.data.schema import DATE, PRICE_COLUMNS, TICKER
from statarb.data.sources import PriceBasis

NAME = "marketparquet"
LAYOUT = "days"
BASIS = PriceBasis.SPLIT_ADJUSTED
HOST = "https://marketparquet.com"
MANIFEST = "/api/v1/manifest"
KEY_ENV = "MARKETPARQUET_API_KEY"
ASSETS = ("stock_daily", "etf_daily")     # decision record 0008: no intraday bars, no futures
MAX_FILES = 400                           # the most files one manifest request lists: a calendar year fits
MIN_INTERVAL = 60 / 500                   # seconds between requests: under the paid plan's 600 a minute
# Names the client for what it is. The site's edge refuses Python's default agent string.
USER_AGENT = "marketparquet-archive-client/1 (Python urllib)"

NO_FILES = "No data files in the requested range"     # the server's 404 for a range with no session in it

SYMBOL, ASSET_TYPE = "symbol", "asset_type"
# Files dated before 2026-03-27 carry the day as a midnight timestamp in `timestamp`; later ones as `date`.
DAY_FIELDS = ("date", "timestamp")
SERVED = [SYMBOL, ASSET_TYPE, *PRICE_COLUMNS, "volume"]
DAY_COLUMNS = [DATE, TICKER, ASSET_TYPE, *PRICE_COLUMNS, "volume"]


class MissingCredentialsError(RuntimeError):
    pass


class ArchiveError(ValueError):
    """The archive's file list or a file is not what the adapter was written for."""


class RefusedError(ArchiveError):
    """The server refused a request for good: its status and the reason it gave, such as a key it does not
    know (401) or a range outside the purchase (403)."""

    def __init__(self, code: int, detail: str) -> None:
        super().__init__(f"HTTP {code}: {detail}")
        self.code, self.detail = code, detail


# Requests ----------------------------------------------------------------------------------------------


def manifest_url(asset: str, start: dt.date, end: dt.date) -> str:
    """The address of the file list for `asset` over [start, end], both inclusive: always on the API's host."""
    if asset not in ASSETS:
        raise ValueError(f"{asset} is not a dataset this project reads (decision record 0008): {', '.join(ASSETS)}")
    query = urllib.parse.urlencode({"end": end.isoformat(), "start": start.isoformat()})
    return f"{HOST}{MANIFEST}/{asset}?{query}"


def key_from_env(environ: Mapping[str, str] = os.environ) -> str:
    key = environ.get(KEY_ENV, "")
    if not key:
        raise MissingCredentialsError(f"set {KEY_ENV} in the environment (docs/reproduce.md, \"What you need\")")
    return key


def year_ranges(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """[start, end], both inclusive, cut into calendar years, so each is one manifest request."""
    return [
        (max(start, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31)))
        for year in range(start.year, end.year + 1)
    ]


@dataclass(frozen=True)
class DayFile:
    asset: str
    day: dt.date
    size: int
    url: str

    @property
    def name(self) -> str:
        """Where the file is kept in a snapshot."""
        return f"{self.asset}/{self.day.year}/{self.day.isoformat()}.parquet"


def day_files(listing: Mapping[str, Any], asset: str, start: dt.date, end: dt.date) -> list[DayFile]:
    """The files a manifest response lists, in date order. Raises ArchiveError unless the response is for
    this dataset, complete, and holds one https address per day inside [start, end]."""
    entries = listing.get("files") or []
    if listing.get("asset_type") != asset:
        raise ArchiveError(f"asked for {asset}, got a list for {listing.get('asset_type')!r}")
    if listing.get("file_count") != len(entries):
        raise ArchiveError(f"{asset} {start}..{end}: the list says {listing.get('file_count')} files and holds {len(entries)}")
    if len(entries) >= MAX_FILES:
        raise ArchiveError(f"{asset} {start}..{end}: {len(entries)} files, so the list may be cut short at {MAX_FILES}")
    files = sorted(
        (DayFile(asset, dt.date.fromisoformat(e["date"]), int(e["file_size_bytes"]), e["download_url"]) for e in entries),
        key=lambda f: f.day,
    )
    days = [f.day for f in files]
    if len(set(days)) != len(days):
        raise ArchiveError(f"{asset} {start}..{end}: a day is listed twice")
    if days and not (start <= days[0] and days[-1] <= end):
        raise ArchiveError(f"{asset} {start}..{end}: the list holds days outside the range asked for")
    for f in files:
        if urllib.parse.urlsplit(f.url).scheme != "https":
            raise ArchiveError(f"{asset} {f.day}: the file's address is not https")
    return files


class Archive(Protocol):
    """What a download needs of the archive. `Client` is the one that touches the network.
    `file` is called from several threads at once."""

    def listing(self, asset: str, start: dt.date, end: dt.date) -> dict[str, Any]: ...

    def file(self, url: str) -> bytes: ...


class Client:
    """GET requests to the API and to the file addresses it returns, paced under the rate limit.

    The only network access in this module. `opener`, `clock` and `sleep` are
    replaced in tests. The key goes to the API's host alone. Safe to call from
    several threads: they share one pace, so together they stay under the limit.
    """

    def __init__(
        self,
        key: str | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: float = MIN_INTERVAL,
        retries: int = 3,
    ) -> None:
        self._key = key if key is not None else key_from_env()
        self._opener, self._clock, self._sleep = opener, clock, sleep
        self._min_interval, self._retries = min_interval, retries
        self._next: float | None = None     # the earliest time the next request may start
        self._lock = threading.Lock()

    def listing(self, asset: str, start: dt.date, end: dt.date) -> dict[str, Any]:
        """The file list for [start, end]. The server answers a range that holds no file with 404, not an
        empty list: that is returned as an empty list, and any other refusal raises RefusedError."""
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "application/json", "User-Agent": USER_AGENT}
        try:
            return json.loads(self._get(manifest_url(asset, start, end), headers))
        except RefusedError as exc:
            if exc.code == 404 and exc.detail == NO_FILES:
                return {"asset_type": asset, "file_count": 0, "files": []}
            raise

    def file(self, url: str) -> bytes:
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ArchiveError("a file's address must be https")
        return self._get(url, {"User-Agent": USER_AGENT})

    def _get(self, url: str, headers: Mapping[str, str]) -> bytes:
        request = urllib.request.Request(url, headers=dict(headers))
        for attempt in range(self._retries + 1):
            self._pace()
            try:
                with self._opener(request, timeout=120) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                # 429 is the rate limit and 5xx the server's own trouble; anything else will not pass on a retry.
                if exc.code != 429 and exc.code < 500:
                    raise RefusedError(exc.code, _detail(exc)) from None
                if attempt == self._retries:
                    raise
                self._sleep(_retry_after(exc, attempt))
            except (urllib.error.URLError, TimeoutError):
                if attempt == self._retries:
                    raise
                self._sleep(10.0 * (attempt + 1))
        raise AssertionError("unreachable")

    def _pace(self) -> None:
        """Wait for this request's turn: each takes the next slot, `min_interval` after the one before."""
        with self._lock:
            now = self._clock()
            turn = now if self._next is None else max(now, self._next)
            self._next = turn + self._min_interval
        if turn > now:
            self._sleep(turn - now)


def _detail(exc: urllib.error.HTTPError) -> str:
    """The reason in the server's error body, `{"detail": ...}`, or the status line when it gives none."""
    try:
        return str(json.loads(exc.read())["detail"])
    except Exception:  # noqa: BLE001 - whatever the body is, the status still says what happened
        return str(exc.reason)


def _retry_after(exc: urllib.error.HTTPError, attempt: int) -> float:
    """The wait the server asks for (`Retry-After`, in seconds), or a growing one when it names none."""
    asked = (exc.headers.get("Retry-After") if exc.headers else None) or ""
    return float(asked) if asked.isdigit() else 10.0 * (attempt + 1)


# Download ----------------------------------------------------------------------------------------------


def download(
    archive: Archive,
    raw_root: Path,
    assets: Sequence[str],
    start: dt.date,
    end: dt.date,
    today: dt.date,
    retries: int = 3,
    workers: int = 1,
    log: Callable[[str], None] = lambda message: None,
) -> Path:
    """One snapshot of every day file of `assets` over [start, end], kept as served; returns its path.

    The snapshot is named by `today`, New York's date at the time of the download. A file whose size is not
    the one its list gives is fetched again, and the download fails if it still differs: a snapshot with a
    hole is not written. Up to `workers` files are fetched at once; they are written in date order by this
    thread alone, and a failure stops the rest. `log` is given one line as each year of a dataset finishes. It also fails when a dataset's last file is before `end`, so a snapshot is never
    taken before the archive holds the last session asked for.
    """
    if end >= today:
        raise ArchiveError(f"the last session asked for, {end}, is not before the download date {today}")
    writer = cache.SnapshotWriter(raw_root, NAME, today)
    days: dict[str, dict[str, Any]] = {}
    years = year_ranges(start, end)
    steps, step = len(assets) * len(years), 0
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        for asset in assets:
            kept: list[DayFile] = []
            for first, last in years:
                files = day_files(archive.listing(asset, first, last), asset, first, last)
                served = pool.map(lambda f: _served(archive, f, retries), files)
                for f, data in zip(files, served, strict=True):
                    writer.write_bytes(f.name, data)
                kept += files
                step += 1
                megabytes = sum(f.size for f in files) / 1e6
                log(f"{step}/{steps} {asset} {first.year}: {len(files)} files, {megabytes:.1f} MB")
            if not kept or kept[-1].day != end:
                found = kept[-1].day if kept else "nothing"
                raise ArchiveError(f"{asset}: the archive's last file is {found}, not the last session asked for, {end}")
            days[asset] = {"files": len(kept), "first": kept[0].day.isoformat(), "last": kept[-1].day.isoformat()}
    finally:
        # On a failure or an interrupt, fetches not yet started are dropped and those under way are waited for.
        pool.shutdown(wait=True, cancel_futures=True)
    return writer.commit(
        {
            "source": NAME,
            "basis": str(BASIS),
            "layout": LAYOUT,
            "client": USER_AGENT,
            "start": start.isoformat(),
            "end_exclusive": (end + dt.timedelta(days=1)).isoformat(),
            "downloaded_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "assets": list(assets),
            "days": days,
        }
    )


def _served(archive: Archive, f: DayFile, retries: int) -> bytes:
    for _ in range(retries + 1):
        data = archive.file(f.url)
        if len(data) == f.size:
            return data
    raise ArchiveError(f"{f.asset} {f.day}: {len(data)} bytes served, {f.size} listed")


# Reading -----------------------------------------------------------------------------------------------


def snapshot_days(path: Path, asset: str) -> list[dt.date]:
    """The days a snapshot holds for a dataset, in order, from its file names alone."""
    return sorted(dt.date.fromisoformat(p.stem) for p in (path / asset).glob("*/*.parquet"))


def read_day(data: bytes | Path, day: dt.date) -> pd.DataFrame:
    """One day file as `DAY_COLUMNS`, the symbol as served in `ticker`. Raises ArchiveError unless every row
    is of `day` and each symbol appears once."""
    table = pq.read_table(io.BytesIO(data) if isinstance(data, bytes) else data)
    fields = [name for name in DAY_FIELDS if name in table.column_names]
    missing = sorted(set(SERVED) - set(table.column_names))
    if len(fields) != 1 or missing:
        raise ArchiveError(f"{day}: columns {table.column_names} are not the archive's daily schema")
    stamps = table[fields[0]].cast(pa.timestamp("us")).to_pandas()
    if not (stamps == pd.Timestamp(day)).all():
        raise ArchiveError(f"{day}: the file holds rows of another day or time")
    frame = table.select(SERVED).to_pandas().rename(columns={SYMBOL: TICKER})
    if frame[TICKER].duplicated().any():
        raise ArchiveError(f"{day}: a symbol appears twice")
    frame[DATE] = pd.Timestamp(day).as_unit("ns")
    return frame.astype(dict.fromkeys([*PRICE_COLUMNS, "volume"], "float64"))[DAY_COLUMNS]


def read_days(path: Path, asset: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """A snapshot's bars for trading dates in [start, end), one row per date and symbol, sorted by both.

    Only the files of days inside the window are opened, so a cut is a cut: nothing outside it is read.
    """
    days = [day for day in snapshot_days(path, asset) if start <= day < end]
    frames = [read_day(path / asset / str(day.year) / f"{day.isoformat()}.parquet", day) for day in days]
    if not frames:
        return pd.DataFrame(columns=DAY_COLUMNS).astype(
            {DATE: "datetime64[ns]", TICKER: "str", ASSET_TYPE: "str", **dict.fromkeys([*PRICE_COLUMNS, "volume"], "float64")}
        )
    return pd.concat(frames, ignore_index=True).sort_values([DATE, TICKER], kind="mergesort").reset_index(drop=True)
