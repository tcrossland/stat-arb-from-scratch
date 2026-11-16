"""Alpaca market data adapter (decision records 0003 and 0004).

Daily bars come raw (`adjustment=raw`) from the consolidated feed (`feed=sip`),
so the basis is unadjusted. Splits, dividends and spin-offs come from
`/v1/corporate-actions`. A download keeps what Alpaca returns (`fetch_raw`):
the ticker's bars, the action records under each symbol it has held, and the
bars of each security it spun off. The build turns them into the `cash` and
`split_ratio` columns (`apply_rules`) by the rules in decision record 0004, so
a changed rule or correction needs a rebuild, not a download:

- the action query's `start` and `end` filter on the process date, usually the
  payable date, so it reaches `ACTION_MARGIN` beyond the bars' window and keeps
  actions by ex-date;
- a dividend Alpaca reports net of withholding tax is grossed up from
  `config/alpaca.toml`;
- a spin-off is cash: the share ratio times the spun-off security's close;
- a ticker's actions follow its name changes back, each symbol only for the
  dates the ticker held it;
- a record seen twice is kept once, except the repeats `config/alpaca.toml`
  lists as separate dividends;
- `config/alpaca.toml` lists, each with its primary source, the records to drop
  and the dividends Alpaca has no record of.

Only the market data host is ever called, never the trading API. The keys are
read from the environment, never from a file in the repository.
"""

from __future__ import annotations

import datetime as dt
import itertools
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
SPIN_OFF_SEARCH = dt.timedelta(days=10)   # how far after the ex-date, or the payable date when later, to look for a close
SPIN_OFF_FETCH = dt.timedelta(days=30)    # how far a download keeps a spun-off security's bars: past any search window
MIN_INTERVAL = 60 / 190                   # seconds between requests: under the free plan's 200 a minute
BAR_LIMIT, ACTION_LIMIT = 10_000, 1_000

SPLITS = ("forward_splits", "reverse_splits")
DIVIDENDS, SPIN_OFFS, NAME_CHANGES = "cash_dividends", "spin_offs", "name_changes"
# Fields that describe how a record was filed, not the event; records equal apart from them are one event.
# The CUSIP is among them: Alpaca files some dividends twice, under a security's old and new CUSIP.
FILING_FIELDS = frozenset({"id", "cusip", "special", "process_date", "payable_date", "record_date", "due_bill_redemption_date"})

Getter = Callable[[str, Mapping[str, str]], dict[str, Any]]
SpinOffClose = Callable[[str, dt.date, dt.date], float]     # (symbol, first day, last day) -> first close
Record = tuple[str, dict[str, Any]]                          # (kind, record) as Alpaca returns it


class MissingCredentialsError(RuntimeError):
    pass


class RuleError(ValueError):
    """A ticker's raw data fails a rule of decision record 0004; the build leaves the ticker out."""


class WithholdingError(RuleError):
    """A dividend flagged foreign for a ticker `config/alpaca.toml` does not cover."""


class ActionDateError(RuleError):
    """An action going ex on a date inside the bars' window that has no bar."""


class SpinOffPriceError(RuleError):
    """No close yet for a spun-off security, so the parent's cash cannot be valued."""


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


# Withholding -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NetPeriod:
    """Ex-dates from `start` to `end` (inclusive; open when None) on which Alpaca reports amounts net of `rate`."""

    rate: float
    start: dt.date
    end: dt.date | None = None
    gross_dates: frozenset[dt.date] = frozenset()

    def covers(self, ex: dt.date) -> bool:
        return self.start <= ex and (self.end is None or ex <= self.end) and ex not in self.gross_dates


@dataclass(frozen=True)
class Withholding:
    net: Mapping[str, tuple[NetPeriod, ...]]
    gross: frozenset[str]


def parse_withholding(cfg: Mapping[str, Any]) -> Withholding:
    """`config/alpaca.toml`: `[[net]]` periods by ticker and the `gross` list."""
    net: dict[str, list[NetPeriod]] = {}
    for entry in cfg.get("net", []):
        missing = {"ticker", "rate", "start", "country", "source"} - set(entry)
        if missing:
            raise ValueError(f"withholding entry {entry.get('ticker')} lacks {sorted(missing)}")
        rate = float(entry["rate"])
        if not 0.0 < rate < 1.0:
            raise ValueError(f"withholding rate for {entry['ticker']} must be in (0, 1): {rate}")
        period = NetPeriod(rate, entry["start"], entry.get("end"), frozenset(entry.get("gross_dates", [])))
        if period.end is not None and period.end < period.start:
            raise ValueError(f"withholding period for {entry['ticker']} ends before it starts")
        net.setdefault(entry["ticker"], []).append(period)
    gross = frozenset(cfg.get("gross", []))
    both = sorted(gross & set(net))
    if both:
        raise ValueError(f"tickers both net and gross in withholding: {both}")
    for ticker, periods in net.items():
        ordered = sorted(periods, key=lambda p: p.start)
        for a, b in itertools.pairwise(ordered):
            if a.end is None or a.end >= b.start:
                raise ValueError(f"withholding periods for {ticker} overlap")
    return Withholding({t: tuple(sorted(p, key=lambda x: x.start)) for t, p in net.items()}, gross)


def gross_dividend(withholding: Withholding, ticker: str, ex: dt.date, rate: float, foreign: bool) -> float:
    """The dividend before withholding tax. Only amounts flagged foreign are ever net."""
    if not foreign:
        return rate
    if ticker in withholding.gross:
        return rate
    if ticker not in withholding.net:
        raise WithholdingError(f"{ticker}: dividend going ex {ex} is flagged foreign; add it to config/alpaca.toml")
    for period in withholding.net[ticker]:
        if period.covers(ex):
            return rate / (1.0 - period.rate)
    return rate


# Corporate actions -------------------------------------------------------------------------------------

Repeat = tuple[str, dt.date]    # a symbol and ex-date whose repeated records are separate events


def _require(section: str, entry: Mapping[str, Any], keys: set[str]) -> None:
    missing = keys - set(entry)
    if missing:
        raise ValueError(f"{section} entry {entry.get('symbol', entry.get('new_symbol'))} lacks {sorted(missing)}")


def parse_repeats(cfg: Mapping[str, Any]) -> frozenset[Repeat]:
    """`config/alpaca.toml`: the `[[repeat]]` entries, each a symbol and ex-date with a note and a source."""
    out = set()
    for entry in cfg.get("repeat", []):
        _require("repeat", entry, {"symbol", "ex_date", "note", "source"})
        out.add((entry["symbol"], entry["ex_date"]))
    return frozenset(out)


@dataclass(frozen=True)
class Drop:
    """A record Alpaca files that is not this security's action: by symbol, kind and ex-date, and amount when given."""

    symbol: str
    kind: str
    ex_date: dt.date
    rate: float | None = None

    def matches(self, kind: str, rec: Mapping[str, Any]) -> bool:
        return (
            kind == self.kind
            and action_symbol(kind, rec) == self.symbol
            and bool(rec.get("ex_date"))
            and _date(rec["ex_date"]) == self.ex_date
            and (self.rate is None or abs(float(rec.get("rate", "nan")) - self.rate) < 1e-9)
        )


@dataclass(frozen=True)
class Corrections:
    """Hand-checked corrections to Alpaca's corporate actions, from `config/alpaca.toml` (decision record 0004).

    `added` holds Alpaca-shaped records by the symbol they are filed under:
    dividends Alpaca has no record of.
    """

    repeats: frozenset[Repeat] = frozenset()
    drops: tuple[Drop, ...] = ()
    added: Mapping[str, tuple[Record, ...]] = MappingProxyType({})


ADD_KINDS = (DIVIDENDS,)


def _ex_dates(section: str, entry: Mapping[str, Any]) -> list[dt.date]:
    """An entry's `ex_date`, or its `ex_dates` when one correction applies on several."""
    if ("ex_date" in entry) == ("ex_dates" in entry):
        raise ValueError(f"{section} entry {entry.get('symbol')} needs exactly one of ex_date and ex_dates")
    return [entry["ex_date"]] if "ex_date" in entry else list(entry["ex_dates"])


def _added_records(entry: Mapping[str, Any]) -> list[tuple[str, Record]]:
    """(symbol it is filed under, record) for each ex-date of an `[[add]]` entry."""
    return [_added_record(entry, ex) for ex in _ex_dates("add", entry)]


def _added_record(entry: Mapping[str, Any], ex: dt.date) -> tuple[str, Record]:
    _require("add", entry, {"symbol", "kind", "note", "source"})
    kind, symbol = entry["kind"], entry["symbol"]
    base = {"id": f"config:{kind}:{symbol}:{ex.isoformat()}", "ex_date": ex.isoformat()}
    if kind == DIVIDENDS:
        _require("add", entry, {"rate"})
        return symbol, (kind, {**base, "symbol": symbol, "rate": float(entry["rate"]), "foreign": False})
    raise ValueError(f"add entry {symbol} {ex}: kind must be one of {ADD_KINDS}, not {kind!r}")


def parse_corrections(cfg: Mapping[str, Any]) -> Corrections:
    """`config/alpaca.toml`: `[[repeat]]`, `[[drop]]` and `[[add]]`, each with its source."""
    drops = []
    for entry in cfg.get("drop", []):
        _require("drop", entry, {"symbol", "kind", "note", "source"})
        rate = None if entry.get("rate") is None else float(entry["rate"])
        drops += [Drop(entry["symbol"], entry["kind"], ex, rate) for ex in _ex_dates("drop", entry)]
    added: dict[str, list[Record]] = {}
    listed = [r for e in cfg.get("add", []) for r in _added_records(e)]
    for symbol, rec in listed:
        added.setdefault(symbol, []).append(rec)
    return Corrections(
        parse_repeats(cfg), tuple(drops), MappingProxyType({s: tuple(r) for s, r in added.items()})
    )


@dataclass(frozen=True)
class Rules:
    """Everything `config/alpaca.toml` sets: the withholding rules and the corrections."""

    withholding: Withholding
    corrections: Corrections = Corrections()


def parse_rules(cfg: Mapping[str, Any]) -> Rules:
    return Rules(parse_withholding(cfg), parse_corrections(cfg))


def corrected(symbol: str, recs: list[Record], corrections: Corrections) -> tuple[list[Record], list[Record]]:
    """(records, dropped): the records filed under `symbol`, less the listed drops, plus the listed additions."""
    dropped = [(k, r) for k, r in recs if any(d.matches(k, r) for d in corrections.drops)]
    kept = [(k, r) for k, r in recs if not any(d.matches(k, r) for d in corrections.drops)]
    return kept + list(corrections.added.get(symbol, ())), dropped


def records(responses: Iterable[Mapping[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """(kind, record) pairs from corporate-action pages."""
    return [(kind, rec) for page in responses for kind, recs in (page.get("corporate_actions") or {}).items() for rec in recs or []]


def action_symbol(kind: str, rec: Mapping[str, Any]) -> str | None:
    """The symbol whose holders an action applies to."""
    return rec.get("source_symbol") if kind == SPIN_OFFS else rec.get("symbol")


def dedupe(
    recs: list[tuple[str, dict[str, Any]]], repeats: frozenset[Repeat] = frozenset()
) -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[str, dict[str, Any]]]]:
    """(kept, dropped): one record per id, then one per event (records equal apart from FILING_FIELDS),
    except for the symbols and ex-dates in `repeats`, whose records are all separate events."""
    kept: list[tuple[str, dict[str, Any]]] = []
    dropped: list[tuple[str, dict[str, Any]]] = []
    ids: set[str] = set()
    events: set[tuple[Any, ...]] = set()
    for kind, rec in recs:
        event = (kind, *sorted((k, json.dumps(v)) for k, v in rec.items() if k not in FILING_FIELDS))
        if rec.get("id") in ids:
            continue                      # the same record from another page or query
        ids.add(rec.get("id"))
        listed = (action_symbol(kind, rec), _date(rec["ex_date"]) if rec.get("ex_date") else None) in repeats
        if event in events and not listed:
            dropped.append((kind, rec))
            continue
        events.add(event)
        kept.append((kind, rec))
    return kept, dropped


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


@dataclass(frozen=True)
class SymbolWindow:
    """A symbol the ticker held, for ex-dates from `start` (inclusive) to `end` (exclusive); None is open."""

    symbol: str
    start: dt.date | None
    end: dt.date | None

    def holds(self, ex: dt.date) -> bool:
        return (self.start is None or ex >= self.start) and (self.end is None or ex < self.end)


def renames_into(recs: list[tuple[str, dict[str, Any]]], symbol: str, before: dt.date | None) -> list[tuple[str, dt.date]]:
    """(old symbol, date) of each name change into `symbol`, before `before` when given."""
    out = []
    for kind, rec in recs:
        if kind == NAME_CHANGES and rec.get("new_symbol") == symbol and rec.get("old_symbol") != symbol:
            day = _date(rec["process_date"])
            if before is None or day < before:
                out.append((rec["old_symbol"], day))
    return sorted(out, key=lambda c: c[1])


def ticker_actions(
    query: Callable[[str], list[tuple[str, dict[str, Any]]]], ticker: str
) -> tuple[list[tuple[str, dict[str, Any]]], list[SymbolWindow]]:
    """Every action of `ticker`, following its name changes back.

    `query(symbol)` returns the records filed under a symbol. A symbol's own
    records count only while the ticker held it: from the latest name change
    into it (earlier records under the same symbol belong to another security)
    until the change away from it. A ticker can hold a symbol more than once
    (FISV, then FI, then FISV again), so each holding is its own window; every
    step goes to an earlier date, so the walk ends.
    """
    found: list[tuple[str, dict[str, Any]]] = []
    windows: list[SymbolWindow] = []
    pending: list[tuple[str, dt.date | None]] = [(ticker, None)]
    filed: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    while pending:
        symbol, until = pending.pop()
        if symbol not in filed:
            filed[symbol] = query(symbol)
        recs = filed[symbol]
        changes = renames_into(recs, symbol, until)
        window = SymbolWindow(symbol, changes[-1][1] if changes else None, until)
        windows.append(window)
        found += [
            (kind, rec) for kind, rec in recs
            if kind != NAME_CHANGES and action_symbol(kind, rec) == symbol and rec.get("ex_date") and window.holds(_date(rec["ex_date"]))
        ]
        pending += changes
    return found, windows


def action_columns(
    recs: list[tuple[str, dict[str, Any]]],
    ticker: str,
    withholding: Withholding,
    spin_off_close: SpinOffClose,
    end: dt.date,
) -> pd.DataFrame:
    """cash and split_ratio by ex-date from a ticker's actions. Other kinds change no basis and are left out.

    A spin-off is cash: the share ratio times the spun-off security's first
    close from the ex-date, searched up to `SPIN_OFF_SEARCH` after the ex-date
    or the payable date, whichever is later. The ratio counts the shares held at
    the record date, so on an ex-date with a split the cash is per share before
    it, and is divided by the split ratio to put it on today's shares (Honeywell,
    2026-06-29: 0.5 HONA per share and a one-for-two reverse split).
    """
    rows = []     # (ex-date, cash per share after any split, cash per share before it, split ratio)
    for kind, rec in recs:
        ex = _date(rec["ex_date"])
        if kind == DIVIDENDS:
            rows.append((ex, gross_dividend(withholding, ticker, ex, float(rec["rate"]), bool(rec.get("foreign"))), 0.0, 1.0))
        elif kind in SPLITS:
            rows.append((ex, 0.0, 0.0, float(rec["new_rate"]) / float(rec["old_rate"])))
        elif kind == SPIN_OFFS:
            ratio = float(rec["new_rate"]) / float(rec["source_rate"])
            last = min(_search_from(rec) + SPIN_OFF_SEARCH, end)
            rows.append((ex, 0.0, ratio * spin_off_close(rec["new_symbol"], ex, last), 1.0))
    frame = pd.DataFrame(rows, columns=[DATE, "cash", "cash_before", "split_ratio"])
    frame[DATE] = pd.to_datetime(frame[DATE]).astype("datetime64[ns]")
    daily = frame.groupby(DATE, as_index=False).agg(
        cash=("cash", "sum"), cash_before=("cash_before", "sum"), split_ratio=("split_ratio", "prod")
    )
    return daily.assign(cash=daily["cash"] + daily["cash_before"] / daily["split_ratio"])[[DATE, "cash", "split_ratio"]]


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
class SpinOffBars:
    """A spun-off security's bars as Alpaca returned them, for New York dates from `first` to `end` (exclusive)."""

    symbol: str
    first: dt.date
    end: dt.date
    bars: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class RawTicker:
    """What a download keeps for one ticker, as Alpaca returned it.

    `actions` holds the records under each symbol the ticker has held, by that
    symbol, before any rule; `spin_off_bars` the bars of each security spun off
    in the window.
    """

    bars: tuple[Mapping[str, Any], ...]
    actions: Mapping[str, tuple[Record, ...]] = MappingProxyType({})
    spin_off_bars: tuple[SpinOffBars, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.bars


def raw_actions_json(raw: RawTicker) -> bytes:
    """The action records and spin-off bars of a `RawTicker`, as stable JSON."""
    doc = {
        "actions": {s: [{"kind": k, "record": r} for k, r in recs] for s, recs in raw.actions.items()},
        "spin_off_bars": [
            {"symbol": f.symbol, "first": f.first.isoformat(), "end": f.end.isoformat(), "bars": list(f.bars)} for f in raw.spin_off_bars
        ],
    }
    return (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode()


def raw_from(bars: list[Mapping[str, Any]], actions_json: bytes) -> RawTicker:
    doc = json.loads(actions_json)
    return RawTicker(
        tuple(bars),
        MappingProxyType({s: tuple((e["kind"], e["record"]) for e in recs) for s, recs in doc["actions"].items()}),
        tuple(SpinOffBars(f["symbol"], _date(f["first"]), _date(f["end"]), tuple(f["bars"])) for f in doc["spin_off_bars"]),
    )


def _in_window(frame: pd.DataFrame, start: dt.date, end: dt.date) -> pd.DataFrame:
    keep = (frame[DATE] >= pd.Timestamp(start)) & (frame[DATE] < pd.Timestamp(end))
    return frame.loc[keep].reset_index(drop=True)


def _search_from(rec: Mapping[str, Any]) -> dt.date:
    """The day a spun-off security's close is searched from: the ex-date, or the payable date when later."""
    ex = _date(rec["ex_date"])
    return max(ex, _date(rec["payable_date"])) if rec.get("payable_date") else ex


def stored_close(fetched: tuple[SpinOffBars, ...], symbol: str, ex: dt.date, last: dt.date) -> float:
    """The first close of `symbol` from `ex` to `last` (exclusive) among the bars a download kept."""
    for f in fetched:
        if f.symbol == symbol and f.first <= ex and last <= f.end:
            bars = _in_window(bar_frame(list(f.bars)), ex, last)
            if bars.empty:
                raise SpinOffPriceError(f"no close for spun-off {symbol} from {ex} to {last}")
            return float(bars["close"].iloc[0])
    raise MissingRawError(f"the download kept no bars of spun-off {symbol} from {ex}; download again")


def apply_rules(raw: RawTicker, ticker: str, rules: Rules, start: dt.date, end: dt.date) -> pd.DataFrame:
    """A ticker's bars with cash and split_ratio for New York dates in [start, end), from what a download kept."""
    bars = _in_window(bar_frame(list(raw.bars)), start, end)
    if bars.empty:
        return normalise_bars(bars.assign(cash=0.0, split_ratio=1.0))

    def query(symbol: str) -> list[Record]:
        if symbol not in raw.actions:
            raise MissingRawError(f"{ticker}: the download kept no records under {symbol}; download again")
        return corrected(symbol, list(raw.actions[symbol]), rules.corrections)[0]

    recs, _ = ticker_actions(query, ticker)
    recs, _ = dedupe(recs, rules.corrections.repeats)
    in_window = [(k, r) for k, r in recs if start <= _date(r["ex_date"]) < end]

    def spin_off_close(symbol: str, ex: dt.date, last: dt.date) -> float:
        return stored_close(raw.spin_off_bars, symbol, ex, last)

    actions = action_columns(in_window, ticker, rules.withholding, spin_off_close, end)
    return join_actions(bars, actions, ticker)


# Adapter -----------------------------------------------------------------------------------------------


class AlpacaSource:
    name = "alpaca"
    basis = PriceBasis.UNADJUSTED
    layout = "raw"                       # a snapshot keeps what Alpaca returned; the build applies the rules

    def __init__(self, rules: Rules, get: Getter | None = None) -> None:
        self._rules = rules
        self._get = get if get is not None else Client().get

    def source_symbol(self, ticker: str) -> str:
        return ticker                    # Alpaca writes share classes with a dot, as S&P does (BRK.B)

    def fetch(self, ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        """Bars with the rules applied: a download and a build in one."""
        return apply_rules(self.fetch_raw(ticker, start, end), self.source_symbol(ticker), self._rules, start, end)

    def fetch_raw(self, ticker: str, start: dt.date, end: dt.date) -> RawTicker:
        """What a download keeps: the ticker's bars, the records under each symbol it has held, and spun-off bars.

        The symbols follow Alpaca's name changes back, as the build will. The
        spun-off bars cover every spin-off in the window under those symbols,
        before or after the corrections, from its ex-date to `SPIN_OFF_FETCH`
        past the day the build searches from.
        """
        symbol = self.source_symbol(ticker)
        bars = self._raw_bars(symbol, start, end)
        if not bars:
            return RawTicker(())
        filed: dict[str, list[Record]] = {}

        def query(s: str) -> list[Record]:
            filed[s] = self._actions(s, start, end)
            return corrected(s, filed[s], self._rules.corrections)[0]

        found, _ = ticker_actions(query, symbol)
        own = [(k, r) for s, recs in filed.items() for k, r in recs if action_symbol(k, r) == s]
        wanted: dict[tuple[str, dt.date], dt.date] = {}
        for kind, rec in [*found, *own]:
            if kind == SPIN_OFFS and "new_symbol" in rec and rec.get("ex_date") and start <= _date(rec["ex_date"]) < end:
                key = (rec["new_symbol"], _date(rec["ex_date"]))
                wanted[key] = max(wanted.get(key, key[1]), min(_search_from(rec) + SPIN_OFF_FETCH, end))
        spun = tuple(SpinOffBars(s, ex, last, tuple(self._raw_bars(s, ex, last))) for (s, ex), last in sorted(wanted.items()))
        return RawTicker(tuple(bars), MappingProxyType({s: tuple(r) for s, r in filed.items()}), spun)

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
