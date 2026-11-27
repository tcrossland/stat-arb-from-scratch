"""Synthetic auction responses and snapshots for the auction tests. Every price is made up."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from statarb.data import auctions, cache

EXCHANGE_TABLE = {
    "A": "NYSE American (AMEX)", "N": "New York Stock Exchange", "P": "NYSE Arca", "Q": "NASDAQ OMX",
    "V": "IEX", "Z": "Cboe BZX",
}
CONDITIONS = {"6": "Market Center Closing Trade", "M": "Market Center Official Close",
              "O": "Market Center Opening Trade", "Q": "Market Center Official Open"}


def stamp(day: pd.Timestamp, hour: int, minute: int, fraction: str = "") -> str:
    moment = pd.Timestamp(day).replace(hour=hour, minute=minute).tz_localize("America/New_York").tz_convert("UTC")
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + (f".{fraction}" if fraction else "") + "Z"


def auction_day(day: pd.Timestamp, opens: list[tuple[str, str, float, float | None]],
                closes: list[tuple[str, str, float, float | None]]) -> dict[str, Any]:
    """One day of the endpoint's response. Each print is (exchange, condition, price, size or None)."""
    def one(x: str, c: str, p: float, s: float | None, hour: int, minute: int, i: int) -> dict[str, Any]:
        out = {"x": x, "c": c, "p": p, "t": stamp(day, hour, minute, f"{i + 1:03d}")}
        if s is not None:
            out["s"] = s
        return out

    return {
        "d": pd.Timestamp(day).date().isoformat(),
        "o": [one(*q, 9, 30, i) for i, q in enumerate(opens)],
        "c": [one(*q, 16, 0, i) for i, q in enumerate(closes)],
    }


def fake_auctions(days: Mapping[str, list[dict[str, Any]]], page_size: int = 10_000, fail: frozenset[str] = frozenset()):
    """A getter serving the auctions endpoint and the code tables. A page holds at most `page_size` prints, so a day
    can be split across pages, as the limit counts data points. Requests are kept in `calls`."""
    calls: list[tuple[str, dict[str, str]]] = []

    def get(path: str, params: Mapping[str, str]) -> dict[str, Any]:
        calls.append((path, dict(params)))
        if path == auctions.EXCHANGES:
            return dict(EXCHANGE_TABLE)
        if path == auctions.CONDITIONS:
            return dict(CONDITIONS)
        assert path == auctions.AUCTIONS
        symbol = params["symbols"]
        if symbol in fail:
            raise OSError("synthetic failure")
        start = pd.Timestamp(params["start"]).date()
        end = pd.Timestamp(params["end"]).tz_convert("America/New_York").date()
        flat = [
            (d["d"], key, p)
            for d in days.get(symbol, [])
            if start <= dt.date.fromisoformat(d["d"]) <= end
            for key in ("o", "c")
            for p in d[key]
        ]
        offset = int(params.get("page_token") or 0)
        chunk = flat[offset : offset + page_size]
        out: list[dict[str, Any]] = []
        for d, key, p in chunk:
            if not out or out[-1]["d"] != d:
                out.append({"d": d, "o": [], "c": []})
            out[-1][key].append(p)
        token = str(offset + page_size) if offset + page_size < len(flat) else None
        return {"auctions": {symbol: out} if out else {}, "next_page_token": token}

    get.calls = calls
    return get


def bar_snapshot(raw_root: Path, day: dt.date, bars: Mapping[str, pd.DataFrame]) -> Path:
    """A raw Alpaca bar snapshot of `bars` (date, open, close per ticker), as the build's download writes one."""
    writer = cache.SnapshotWriter(raw_root, "alpaca", day)
    for ticker, frame in bars.items():
        rows = pd.DataFrame({
            "t": [stamp(d, 0, 0) for d in frame["date"]], "o": frame["open"], "h": frame[["open", "close"]].max(axis=1),
            "l": frame[["open", "close"]].min(axis=1), "c": frame["close"], "v": 1000.0, "n": 10, "vw": frame["close"],
        })
        writer.write_frame(f"bars/{ticker}", rows, sort_by=["t"])
        writer.write_bytes(f"actions/{ticker}.json", b"{}")
    return writer.commit({"source": "alpaca", "basis": "unadjusted", "layout": "raw", "start": "2016-01-01",
                          "end_exclusive": day.isoformat(), "tickers": sorted(bars), "no_data": [], "failed": {}})
