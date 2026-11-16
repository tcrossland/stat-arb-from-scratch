"""Alpaca market data adapter (decision records 0003 and 0004).

Daily bars come raw (`adjustment=raw`) from the consolidated feed (`feed=sip`),
so the basis is unadjusted. Splits and dividends come from
`/v1/corporate-actions`. A download keeps what Alpaca returns (`fetch_raw`):
the ticker's bars and the action records under its symbol. The build turns
them into the `cash` and `split_ratio` columns (`apply_rules`) by the rules in
decision record 0004, so a changed rule needs a rebuild, not a download:

- the action query's `start` and `end` filter on the process date, usually the
  payable date, so it reaches `ACTION_MARGIN` beyond the bars' window and keeps
  actions by ex-date.

Only the market data host is ever called, never the trading API. The keys are
read from the environment, never from a file in the repository.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import pandas as pd

from statarb.data.schema import BAR_COLUMNS, DATE, EXCHANGE_TZ, normalise_bars
from statarb.data.sources import PriceBasis

DATA_HOST = "https://data.alpaca.markets"
BARS, ACTIONS = "/v2/stocks/bars", "/v1/corporate-actions"
KEY_ENV = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
ACTION_MARGIN = dt.timedelta(days=90)     # process dates fall up to weeks after the ex-date, and sometimes before it
MIN_INTERVAL = 60 / 190                   # seconds between requests: under the free plan's 200 a minute
BAR_LIMIT, ACTION_LIMIT = 10_000, 1_000

SPLITS = ("forward_splits", "reverse_splits")
DIVIDENDS, SPIN_OFFS, NAME_CHANGES = "cash_dividends", "spin_offs", "name_changes"

Getter = Callable[[str, Mapping[str, str]], dict[str, Any]]
Record = tuple[str, dict[str, Any]]                          # (kind, record) as Alpaca returns it


class MissingCredentialsError(RuntimeError):
    pass


class RuleError(ValueError):
    """A ticker's raw data fails a rule of decision record 0004; the build leaves the ticker out."""


class ActionDateError(RuleError):
    """An action going ex on a date inside the bars' window that has no bar."""


class MissingRawError(RuleError):
    """The rules need records or bars the download did not keep, as a snapshot taken
    by earlier code can lack. A new download fetches them."""


# Requests ----------------------------------------------------------------------------------------------


def request_url(path: str, params: Mapping[str, str]) -> str:
    """The URL of a request: always on the market data host."""
    return f"{DATA_HOST}{path}?{urllib.parse.urlencode(sorted(params.items()))}"


def keys_from_env(environ: Mapping[str, str] = os.environ) -> tuple[str, str]:
    missing = [name for name in KEY_ENV if not environ.get(name)]
    if missing:
        raise MissingCredentialsError(f"set {' and '.join(missing)} in the environment (README.md, \"Running it\")")
    return environ[KEY_ENV[0]], environ[KEY_ENV[1]]


class Client:
    """Signed GET requests to the market data host, paced under the rate limit.

    The only network access in this module. `opener`, `clock` and `sleep` are
    replaced in tests.
    """

    def __init__(
        self,
        keys: tuple[str, str] | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: float = MIN_INTERVAL,
        retries: int = 3,
    ) -> None:
        key_id, secret = keys if keys is not None else keys_from_env()
        self._headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"}
        self._opener, self._clock, self._sleep = opener, clock, sleep
        self._min_interval, self._retries = min_interval, retries
        self._last: float | None = None

    def get(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(request_url(path, params), headers=self._headers)
        for attempt in range(self._retries + 1):
            self._pace()
            try:
                with self._opener(request, timeout=60) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == self._retries:
                    raise
                self._sleep(10.0 * (attempt + 1))
        raise AssertionError("unreachable")

    def _pace(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self._min_interval:
            self._sleep(self._min_interval - (now - self._last))
            now = self._clock()
        self._last = now


def pages(get: Getter, path: str, params: Mapping[str, str]) -> list[dict[str, Any]]:
    """Every page of a paginated request."""
    out: list[dict[str, Any]] = []
    token = None
    while True:
        page = get(path, {**params, **({"page_token": token} if token else {})})
        out.append(page)
        token = page.get("next_page_token")
        if not token:
            return out


# Corporate actions -------------------------------------------------------------------------------------


def records(responses: Iterable[Mapping[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """(kind, record) pairs from corporate-action pages."""
    return [(kind, rec) for page in responses for kind, recs in (page.get("corporate_actions") or {}).items() for rec in recs or []]


def action_symbol(kind: str, rec: Mapping[str, Any]) -> str | None:
    """The symbol whose holders an action applies to."""
    return rec.get("source_symbol") if kind == SPIN_OFFS else rec.get("symbol")


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def own_actions(recs: list[tuple[str, dict[str, Any]]], symbol: str) -> list[tuple[str, dict[str, Any]]]:
    """The records filed under `symbol` that are its own actions, with an ex-date."""
    return [(kind, rec) for kind, rec in recs if kind != NAME_CHANGES and action_symbol(kind, rec) == symbol and rec.get("ex_date")]


def action_columns(
    recs: list[tuple[str, dict[str, Any]]],
    ticker: str,
) -> pd.DataFrame:
    """cash and split_ratio by ex-date from a ticker's actions. Other kinds change no basis and are left out."""
    rows = []     # (ex-date, cash per share, split ratio)
    for kind, rec in recs:
        ex = _date(rec["ex_date"])
        if kind == DIVIDENDS:
            rows.append((ex, float(rec["rate"]), 1.0))
        elif kind in SPLITS:
            rows.append((ex, 0.0, float(rec["new_rate"]) / float(rec["old_rate"])))
    frame = pd.DataFrame(rows, columns=[DATE, "cash", "split_ratio"])
    frame[DATE] = pd.to_datetime(frame[DATE]).astype("datetime64[ns]")
    return frame.groupby(DATE, as_index=False).agg(cash=("cash", "sum"), split_ratio=("split_ratio", "prod"))


# Bars --------------------------------------------------------------------------------------------------


def bar_frame(raw: list[Mapping[str, Any]]) -> pd.DataFrame:
    """Alpaca daily bars to date, open, high, low, close, volume. A bar is stamped at its New York midnight.

    A bar with no volume is left out: Alpaca returns one repeating the last
    close on a day the security had no trade on the consolidated tape, halted
    all day or trading off-exchange (Super Micro, delisted from Nasdaq from
    2018-08-23 to 2020-01-13), and that close is not a price of the day.
    """
    raw = [b for b in raw if float(b["v"]) > 0]
    if not raw:
        return pd.DataFrame({DATE: pd.Series(dtype="datetime64[ns]"), **{c: pd.Series(dtype="float64") for c in BAR_COLUMNS[1:6]}})
    stamps = pd.to_datetime([b["t"] for b in raw], utc=True).tz_convert(EXCHANGE_TZ).tz_localize(None).normalize()
    return pd.DataFrame(
        {
            DATE: stamps.astype("datetime64[ns]"),
            "open": [float(b["o"]) for b in raw],
            "high": [float(b["h"]) for b in raw],
            "low": [float(b["l"]) for b in raw],
            "close": [float(b["c"]) for b in raw],
            "volume": [float(b["v"]) for b in raw],
        }
    )


def join_actions(bars: pd.DataFrame, actions: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Bars with cash and split_ratio. An action between the first and last bar must fall on a bar date."""
    if not bars.empty:
        inside = actions[DATE].between(bars[DATE].min(), bars[DATE].max())
        orphans = sorted(set(actions.loc[inside, DATE]) - set(bars[DATE]))
        if orphans:
            raise ActionDateError(f"{ticker}: actions go ex on dates with no bar: {[d.date().isoformat() for d in orphans]}")
    out = bars.merge(actions, on=DATE, how="left")
    out["cash"] = out["cash"].fillna(0.0)
    out["split_ratio"] = out["split_ratio"].fillna(1.0)
    return normalise_bars(out)


# Raw data ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RawTicker:
    """What a download keeps for one ticker, as Alpaca returned it.

    `actions` holds the records under the ticker's symbol, by symbol, before
    any rule.
    """

    bars: tuple[Mapping[str, Any], ...]
    actions: Mapping[str, tuple[Record, ...]] = MappingProxyType({})

    @property
    def empty(self) -> bool:
        return not self.bars


def raw_actions_json(raw: RawTicker) -> bytes:
    """The action records of a `RawTicker`, as stable JSON."""
    doc = {"actions": {s: [{"kind": k, "record": r} for k, r in recs] for s, recs in raw.actions.items()}}
    return (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode()


def raw_from(bars: list[Mapping[str, Any]], actions_json: bytes) -> RawTicker:
    doc = json.loads(actions_json)
    return RawTicker(
        tuple(bars),
        MappingProxyType({s: tuple((e["kind"], e["record"]) for e in recs) for s, recs in doc["actions"].items()}),
    )


def _in_window(frame: pd.DataFrame, start: dt.date, end: dt.date) -> pd.DataFrame:
    keep = (frame[DATE] >= pd.Timestamp(start)) & (frame[DATE] < pd.Timestamp(end))
    return frame.loc[keep].reset_index(drop=True)


def apply_rules(raw: RawTicker, ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """A ticker's bars with cash and split_ratio for New York dates in [start, end), from what a download kept."""
    bars = _in_window(bar_frame(list(raw.bars)), start, end)
    if bars.empty:
        return normalise_bars(bars.assign(cash=0.0, split_ratio=1.0))

    if ticker not in raw.actions:
        raise MissingRawError(f"{ticker}: the download kept no records under {ticker}; download again")
    recs = own_actions(list(raw.actions[ticker]), ticker)
    in_window = [(k, r) for k, r in recs if start <= _date(r["ex_date"]) < end]
    actions = action_columns(in_window, ticker)
    return join_actions(bars, actions, ticker)


# Adapter -----------------------------------------------------------------------------------------------


class AlpacaSource:
    name = "alpaca"
    basis = PriceBasis.UNADJUSTED
    layout = "raw"                       # a snapshot keeps what Alpaca returned; the build applies the rules

    def __init__(self, get: Getter | None = None) -> None:
        self._get = get if get is not None else Client().get

    def source_symbol(self, ticker: str) -> str:
        return ticker                    # Alpaca writes share classes with a dot, as S&P does (BRK.B)

    def fetch(self, ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        """Bars with the rules applied: a download and a build in one."""
        return apply_rules(self.fetch_raw(ticker, start, end), self.source_symbol(ticker), start, end)

    def fetch_raw(self, ticker: str, start: dt.date, end: dt.date) -> RawTicker:
        """What a download keeps: the ticker's bars and the records under its symbol."""
        symbol = self.source_symbol(ticker)
        bars = self._raw_bars(symbol, start, end)
        if not bars:
            return RawTicker(())
        return RawTicker(tuple(bars), MappingProxyType({symbol: tuple(self._actions(symbol, start, end))}))

    def _raw_bars(self, symbol: str, start: dt.date, end: dt.date) -> list[Mapping[str, Any]]:
        params = {
            "symbols": symbol, "timeframe": "1Day", "adjustment": "raw", "feed": "sip",
            "start": start.isoformat(), "end": (end - dt.timedelta(days=1)).isoformat(), "limit": str(BAR_LIMIT),
        }
        return [b for page in pages(self._get, BARS, params) for b in (page.get("bars") or {}).get(symbol, [])]

    def _actions(self, symbol: str, start: dt.date, end: dt.date) -> list[tuple[str, dict[str, Any]]]:
        params = {
            "symbols": symbol, "start": (start - ACTION_MARGIN).isoformat(),
            "end": (end + ACTION_MARGIN).isoformat(), "limit": str(ACTION_LIMIT),
        }
        return records(pages(self._get, ACTIONS, params))
