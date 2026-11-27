"""Alpaca's historical auctions, for measuring the listing exchange's auction prices (docs/plans/auction-closes.md).

`GET /v2/stocks/auctions` returns, for each symbol and day, the opening (`o`)
and closing (`c`) auction prints of every market centre: price `p`, size `s`
(sometimes absent), timestamp `t`, exchange code `x` and condition `c`, each
price, exchange and condition triple once, with its earliest timestamp. A
download keeps them in long form, one row per print, so a day split across two
pages is still one day's prints. Nothing here decides which print is the
listing exchange's: `statarb.data.auction_counts` does, from the listing
exchanges of `config/listings.toml`.

The download is measurement only. It changes no build input, writes a raw
snapshot of its own (`data/raw/alpaca-auctions/<download date>/`), and reads no
forward day: its last date must fall before the forward run's first session,
and a print dated after it is dropped and counted in the manifest.

Requests go through `statarb.data.alpaca.Client`, so only the market data host
is called, under the same pacing and retries as the bar download.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from statarb.data import cache
from statarb.data.alpaca import Getter, pages
from statarb.data.schema import DATE, EXCHANGE_TZ

SOURCE = "alpaca-auctions"
AUCTIONS = "/v2/stocks/auctions"
EXCHANGES = "/v2/stocks/meta/exchanges"
CONDITIONS = "/v2/stocks/meta/conditions/trade"
TAPES = ("A", "B", "C")
LIMIT = 10_000
SESSIONS = {"o": "open", "c": "close"}
PRINTS_DIR, META_DIR = "prints", "meta"
PRINT_COLUMNS = [DATE, "session", "t", "x", "c", "p", "s"]


class ForwardDayError(ValueError):
    """A last date on or after the forward run's first session (decision record 0007, item 4)."""


@dataclass(frozen=True)
class Exchange:
    code: str                  # Alpaca's exchange code, as `x` in a print
    names: tuple[str, ...]     # one of these appears in Alpaca's name for the code


@dataclass(frozen=True)
class Settings:
    start: dt.date
    last: dt.date              # the last date requested, inclusive
    asof: dt.date              # fixes which entity a symbol names, as the bar snapshot did
    pause_seconds: float
    retries: int
    snapshot: str              # the pinned snapshot's download date, or empty
    digest: str
    tolerance: float           # a price further than this from the bar's differs
    exchanges: Mapping[str, Exchange]


def parse_settings(cfg: Mapping[str, Any], first_session: dt.date | None) -> Settings:
    """`config/auctions.toml` as settings. Refuses a last date on or after `first_session`."""
    d, s = cfg["download"], cfg["snapshot"]
    last = d["last"]
    if first_session is not None and last >= first_session:
        raise ForwardDayError(f"auctions: last date {last} is on or after the forward run's first session {first_session}")
    if d["start"] > last:
        raise ValueError(f"auctions: start {d['start']} is after the last date {last}")
    exchanges = {name: Exchange(e["code"], tuple(e["names"])) for name, e in cfg["exchanges"].items()}
    codes = [e.code for e in exchanges.values()]
    if len(set(codes)) != len(codes):
        raise ValueError(f"auctions: two exchanges share a code: {sorted(codes)}")
    return Settings(
        start=d["start"], last=last, asof=d["asof"], pause_seconds=float(d["pause_seconds"]), retries=int(d["retries"]),
        snapshot=s.get("date", ""), digest=s.get("digest", ""), tolerance=float(cfg["compare"]["tolerance"]),
        exchanges=exchanges,
    )


def end_of_day(day: dt.date) -> str:
    """The last instant of a New York date as RFC-3339, so an inclusive `end` keeps that day's closing auction."""
    moment = dt.datetime.combine(day, dt.time(23, 59, 59), tzinfo=ZoneInfo(EXCHANGE_TZ))
    return moment.isoformat()


def query(symbol: str, start: dt.date, last: dt.date, asof: dt.date) -> dict[str, str]:
    return {
        "symbols": symbol, "feed": "sip", "start": start.isoformat(), "end": end_of_day(last),
        "asof": asof.isoformat(), "limit": str(LIMIT), "sort": "asc",
    }


def empty_prints() -> pd.DataFrame:
    return pd.DataFrame({
        DATE: pd.Series(dtype="datetime64[ns]"), "session": pd.Series(dtype="object"), "t": pd.Series(dtype="object"),
        "x": pd.Series(dtype="object"), "c": pd.Series(dtype="object"), "p": pd.Series(dtype="float64"),
        "s": pd.Series(dtype="float64"),
    })


def prints(responses: Iterable[Mapping[str, Any]], symbol: str) -> pd.DataFrame:
    """Every auction print of `symbol` in the responses, one row each, in `PRINT_COLUMNS`. A missing size is NaN."""
    rows = [
        (day["d"], SESSIONS[key], p["t"], p["x"], p["c"], float(p["p"]), float(p["s"]) if p.get("s") is not None else float("nan"))
        for page in responses
        for day in (page.get("auctions") or {}).get(symbol, [])
        for key in SESSIONS
        for p in day.get(key) or []
    ]
    if not rows:
        return empty_prints()
    frame = pd.DataFrame(rows, columns=PRINT_COLUMNS)
    frame[DATE] = pd.to_datetime(frame[DATE]).astype("datetime64[ns]")
    return frame


def split_after(frame: pd.DataFrame, last: dt.date) -> tuple[pd.DataFrame, int]:
    """(the prints dated on or before `last`, how many were dated after it)."""
    after = frame[DATE] > pd.Timestamp(last)
    return frame.loc[~after].reset_index(drop=True), int(after.sum())


class AuctionSource:
    name = SOURCE

    def __init__(self, get: Getter) -> None:
        self._get = get

    def fetch(self, symbol: str, start: dt.date, last: dt.date, asof: dt.date) -> tuple[pd.DataFrame, int]:
        """(the symbol's prints from `start` to `last`, how many prints dated after `last` were dropped)."""
        return split_after(prints(pages(self._get, AUCTIONS, query(symbol, start, last, asof)), symbol), last)

    def meta(self) -> dict[str, dict[str, Any]]:
        """Alpaca's exchange codes and each tape's trade condition codes, by the file name a snapshot keeps them under."""
        out = {"exchanges.json": self._get(EXCHANGES, {})}
        for tape in TAPES:
            out[f"conditions-{tape}.json"] = self._get(CONDITIONS, {"tape": tape})
        return out


def counting(get: Getter) -> tuple[Getter, Callable[[], int]]:
    """A getter that counts its requests, and the count."""
    n = {"requests": 0}

    def counted(path: str, params: Mapping[str, str]) -> dict[str, Any]:
        n["requests"] += 1
        return get(path, params)

    return counted, lambda: n["requests"]


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def download(
    get: Getter,
    raw_root: Path,
    tickers: list[str],
    settings: Settings,
    today: dt.date,
    of_snapshot: str,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """One snapshot of every ticker's auction prints and Alpaca's code tables, named for `today`. A ticker whose
    requests still fail after the retries is listed under "failed" in the manifest, not fatal."""
    get, requests = counting(get)
    source = AuctionSource(get)
    writer = cache.SnapshotWriter(raw_root, SOURCE, today)
    for name, table in source.meta().items():
        writer.write_bytes(f"{META_DIR}/{name}", (json.dumps(table, indent=1, sort_keys=True) + "\n").encode())
    no_data: list[str] = []
    failed: dict[str, str] = {}
    dropped: dict[str, int] = {}
    for i, ticker in enumerate(sorted(tickers), start=1):
        frame = None
        for attempt in range(settings.retries + 1):
            try:
                frame, after = source.fetch(ticker, settings.start, settings.last, settings.asof)
                break
            except Exception as exc:  # noqa: BLE001 - network and parsing errors are recorded, not fatal
                if attempt == settings.retries:
                    failed[ticker] = f"{type(exc).__name__}: {exc}"
                else:
                    sleep(settings.pause_seconds * 2 ** (attempt + 2))
        if frame is not None:
            if after:
                dropped[ticker] = after
            if frame.empty:
                no_data.append(ticker)
            else:
                writer.write_frame(f"{PRINTS_DIR}/{ticker}", frame, sort_by=[DATE, "session", "x", "c", "t", "p"])
        if i % 50 == 0:
            _log(f"auctions: {i}/{len(tickers)}")
        sleep(settings.pause_seconds)
    manifest = {
        "source": SOURCE,
        "endpoint": AUCTIONS,
        "feed": "sip",
        "of_snapshot": of_snapshot,
        "start": settings.start.isoformat(),
        "last": settings.last.isoformat(),
        "asof": settings.asof.isoformat(),
        "downloaded_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "requests": requests(),
        "tickers": sorted(tickers),
        "no_data": sorted(no_data),
        "failed": dict(sorted(failed.items())),
        "dropped_after_last": dict(sorted(dropped.items())),
    }
    path = writer.commit(manifest)
    _log(f"auctions: saved to {path}; {requests()} requests, no data {len(no_data)}, failed {len(failed)}")
    _log(f"to report from it, set in [snapshot] of config/auctions.toml: date = \"{today}\", "
         f"digest = \"{cache.read_manifest(path)['digest']}\"")
    return path


def read_prints(path: Path, ticker: str) -> pd.DataFrame:
    """One ticker's prints from a snapshot, or none."""
    file = path / PRINTS_DIR / f"{ticker}.parquet"
    return cache.read_frame(path / PRINTS_DIR, ticker) if file.is_file() else empty_prints()


def read_meta(path: Path, name: str) -> dict[str, Any]:
    return json.loads((path / META_DIR / name).read_text())


def check_exchanges(exchanges: Mapping[str, Exchange], table: Mapping[str, str]) -> None:
    """Refuse a configured code Alpaca's exchange table lacks, or names otherwise than the config expects."""
    for name, e in exchanges.items():
        published = table.get(e.code)
        if published is None:
            raise ValueError(f"auctions: exchange code {e.code!r} ({name}) is not in Alpaca's exchange table")
        if not any(n.lower() in str(published).lower() for n in e.names):
            raise ValueError(f"auctions: Alpaca names code {e.code!r} {published!r}, not one of {list(e.names)} ({name})")
