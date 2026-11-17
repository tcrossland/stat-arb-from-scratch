"""Test helpers: synthetic sources built from synthetic, unadjusted truth data. No real data."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from statarb.data.schema import BAR_COLUMNS, normalise_bars
from statarb.data.sources import PriceBasis
from statarb.factors.pca import PcaFactorModel, PcaModelConfig

FIXTURES = Path(__file__).parent / "fixtures"


def synthetic_truth(
    dates: pd.DatetimeIndex,
    seed: int,
    price: float = 100.0,
    volume: float = 1_000_000.0,
    splits: dict[pd.Timestamp, float] | None = None,
    cash: dict[pd.Timestamp, float] | None = None,
) -> pd.DataFrame:
    """Unadjusted bars with a random walk close, for any number of days."""
    rng = np.random.default_rng(seed)
    splits = splits or {}
    cash = cash or {}
    rows = []
    for d in dates:
        if d in splits:
            price /= splits[d]
            volume *= splits[d]
        price *= float(np.exp(0.01 * rng.standard_normal()))
        rows.append(
            {
                "date": d,
                "open": price * 1.001,
                "high": price * 1.005,
                "low": price * 0.995,
                "close": price,
                "volume": float(round(volume * float(np.exp(0.3 * rng.standard_normal())))),
                "cash": cash.get(d, 0.0),
                "split_ratio": splits.get(d, 1.0),
            }
        )
    return pd.DataFrame(rows).astype({"date": "datetime64[ns]"})


def truth_fixture() -> pd.DataFrame:
    """A month of one ticker with a 4:1 split, two dividends and a 2:1 split."""
    return synthetic_truth(
        pd.bdate_range("2020-01-02", "2020-02-04"),
        seed=7,
        price=400.0,
        splits={pd.Timestamp("2020-01-15"): 4.0, pd.Timestamp("2020-01-29"): 2.0},
        cash={pd.Timestamp("2020-01-09"): 0.8, pd.Timestamp("2020-01-23"): 0.21},
    )


class SplitAdjustedSource:
    """A synthetic source whose bars are split-adjusted as of the download date `end`, not dividend-adjusted,
    with cash and volume on the same basis. Written independently of statarb.data.canonical, so the
    canonical step is checked against a basis it did not produce."""

    name = "synthetic"
    basis = PriceBasis.SPLIT_ADJUSTED
    layout = "bars"

    def __init__(self, truths: dict[str, pd.DataFrame]) -> None:
        self._truths = truths

    def source_symbol(self, ticker: str) -> str:
        return ticker

    def fetch(self, ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        if ticker not in self._truths:
            return normalise_bars(pd.DataFrame({c: [] for c in BAR_COLUMNS}))
        t = self._truths[ticker]
        t = t.loc[t["date"] < pd.Timestamp(end)].reset_index(drop=True)
        ratios = t["split_ratio"].tolist()
        factor = np.array([float(np.prod(ratios[i + 1 :])) for i in range(len(ratios))])
        out = t.assign(
            **{c: t[c].to_numpy() / factor for c in ("open", "high", "low", "close", "cash")},
            volume=t["volume"].to_numpy() * factor,
        )
        return normalise_bars(out.loc[out["date"] >= pd.Timestamp(start)])


def constituents_html() -> str:
    return (FIXTURES / "wikipedia" / "constituents.html").read_text()


def fake_wikipedia_api(html: str, revid: int = 123456):
    calls: list[dict[str, str]] = []

    def api(params: dict[str, str]) -> dict:
        calls.append(params)
        return {"parse": {"title": "x", "pageid": 1, "revid": revid, "text": html}}

    api.calls = calls  # type: ignore[attr-defined]
    return api


def fake_alpaca(truths: dict[str, pd.DataFrame], extra: list[tuple[str, dict]] | None = None, page_size: int = 10_000):
    """A getter for AlpacaSource(get=...) that serves bars and corporate actions from unadjusted truth data.

    Dividends and splits in the truth become action records processed 14 days
    after their ex-date, and the action query filters on the process date, as
    Alpaca's does. `extra` adds (kind, record) pairs. Requests are kept in `calls`.
    """
    extra = extra or []
    calls: list[tuple[str, dict[str, str]]] = []

    def stamp(day: pd.Timestamp) -> str:
        return pd.Timestamp(day).tz_localize("America/New_York").tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")

    def truth_actions(symbol: str, truth: pd.DataFrame) -> list[tuple[str, dict]]:
        out = []
        for row in truth.itertuples():
            ex = row.date.date()
            processed = (ex + dt.timedelta(days=14)).isoformat()
            if row.cash:
                out.append(("cash_dividends", {"id": f"{symbol}-d-{ex}", "symbol": symbol, "ex_date": ex.isoformat(),
                                               "process_date": processed, "rate": row.cash, "foreign": False}))
            if row.split_ratio != 1.0:
                out.append(("forward_splits", {"id": f"{symbol}-s-{ex}", "symbol": symbol, "ex_date": ex.isoformat(),
                                               "process_date": processed, "old_rate": 1.0, "new_rate": row.split_ratio}))
        return out

    def mentions(rec: dict, symbol: str) -> bool:
        return symbol in {rec.get(k) for k in ("symbol", "source_symbol", "new_symbol", "old_symbol")}

    def get(path: str, params: dict[str, str]) -> dict:
        calls.append((path, dict(params)))
        symbol = params["symbols"]
        start, end = pd.Timestamp(params["start"]), pd.Timestamp(params["end"])
        offset = int(params.get("page_token") or 0)
        if path == "/v2/stocks/bars":
            truth = truths.get(symbol)
            bars = [] if truth is None else [
                {"t": stamp(r.date), "o": r.open, "h": r.high, "l": r.low, "c": r.close, "v": r.volume, "n": 1, "vw": r.close}
                for r in truth.itertuples() if start <= r.date <= end
            ]
            page = bars[offset : offset + page_size]
            token = str(offset + page_size) if offset + page_size < len(bars) else None
            return {"bars": {symbol: page} if page else {}, "next_page_token": token}
        recs = (truth_actions(symbol, truths[symbol]) if symbol in truths else []) + [(k, r) for k, r in extra if mentions(r, symbol)]
        recs = [(k, r) for k, r in recs if start <= pd.Timestamp(r["process_date"]) <= end]
        page = recs[offset : offset + page_size]
        grouped: dict[str, list[dict]] = {}
        for kind, rec in page:
            grouped.setdefault(kind, []).append(rec)
        token = str(offset + page_size) if offset + page_size < len(recs) else None
        return {"corporate_actions": grouped, "next_page_token": token}

    get.calls = calls  # type: ignore[attr-defined]
    return get


# Phase 1: a synthetic panel for the factor model.

FACTOR_CAL = pd.bdate_range("2020-01-01", periods=260)


def factor_panel(seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns, prices and sector intervals for SPY, two sector ETFs and four stocks, on FACTOR_CAL.

    AAA is IT throughout; BBB moves from IT to Financials halfway; CCC is in a
    sector with no ETF; DDD has a gap in its history. Betas are known: AAA 0.9
    to the market and 0.8 to its sector factor, BBB 1.1 and 1.2.
    """
    cal = FACTOR_CAL
    rng = np.random.default_rng(seed)
    n = len(cal)
    spy = rng.normal(0, 0.01, n)
    xlk = spy + rng.normal(0, 0.006, n)
    xlf = spy + rng.normal(0, 0.006, n)
    switch = cal[130]
    bbb_etf = np.where(cal < switch, xlk, xlf)
    series = {
        "SPY": spy,
        "XLK": xlk,
        "XLF": xlf,
        "AAA": 0.9 * spy + 0.8 * (xlk - spy) + rng.normal(0, 0.002, n),
        "BBB": 1.1 * spy + 1.2 * (bbb_etf - spy) + rng.normal(0, 0.002, n),
        "CCC": 1.0 * spy + rng.normal(0, 0.002, n),
        "DDD": 1.2 * spy + 0.5 * (xlk - spy) + rng.normal(0, 0.002, n),
    }
    rows = []
    for ticker, ret in series.items():
        for i, day in enumerate(cal):
            if ticker == "DDD" and 50 <= i < 70:
                continue
            rows.append((day, ticker, ret[i], 1.0))
    returns = pd.DataFrame(rows, columns=["date", "ticker", "ret", "split_ratio"])
    prices = returns[["date", "ticker"]].assign(close=100.0, volume=1e6 * np.exp(rng.normal(0, 0.2, len(returns))))
    sectors = pd.DataFrame(
        [
            ("AAA", "Information Technology", cal[0], pd.NaT),
            ("BBB", "Information Technology", cal[0], switch),
            ("BBB", "Financials", switch, pd.NaT),
            ("CCC", "Utilities", cal[0], pd.NaT),
            ("DDD", "Information Technology", cal[0], pd.NaT),
        ],
        columns=["ticker", "sector", "valid_from", "valid_to"],
    ).astype({"valid_from": "datetime64[ns]", "valid_to": "datetime64[ns]"})
    return returns, prices, sectors


# Phase 2: a synthetic market with lag-1 residual reversal ----------------------

MARKET_CAL = pd.bdate_range("2021-01-04", periods=320)
MARKET_ETFS = {"Information Technology": "XLK", "Financials": "XLF"}


def synthetic_market(seed: int = 0, n: int = 30, reversal: float = 0.3) -> tuple[pd.DataFrame, ...]:
    """Long returns, prices, residuals, universe and sectors tables (statarb.signals.tables.TABLES order)
    for SPY, two sector ETFs and n stocks whose residuals reverse by `reversal` the next day."""
    rng = np.random.default_rng(seed)
    cal = MARKET_CAL
    T = len(cal)
    spy = rng.normal(0, 0.01, T)
    etf = {"XLK": spy + rng.normal(0, 0.005, T), "XLF": spy + rng.normal(0, 0.005, T)}
    rets, resid, betas, sector_rows = {"SPY": spy, **etf}, {}, {}, []
    for i in range(n):
        name, sector = f"S{i:02d}", ("Information Technology" if i % 2 else "Financials")
        e = rng.normal(0, 0.02, T)
        res = e - reversal * np.concatenate([[0.0], e[:-1]])
        beta = 0.8 + 0.4 * rng.random()
        rets[name] = beta * spy + 0.5 * (etf[MARKET_ETFS[sector]] - spy) + res
        resid[name], betas[name] = res, beta
        sector_rows.append((name, sector, cal[0], pd.NaT))
    rows, price_rows = [], []
    for ticker, r in rets.items():
        close = 100 * np.cumprod(1 + r)
        prev = np.concatenate([[100.0], close[:-1]])
        for t, day in enumerate(cal):
            price_rows.append((day, ticker, np.sqrt(prev[t] * close[t]), close[t] * 1.01, close[t] * 0.99, close[t], 1_000_000 + 1000 * t))
            if t:
                rows.append((day, ticker, r[t], cal[t - 1], 1.0, 0.0))
    returns = pd.DataFrame(rows, columns=["date", "ticker", "ret", "prev_date", "split_ratio", "cash"])
    prices = pd.DataFrame(price_rows, columns=["date", "ticker", "open", "high", "low", "close", "volume"])
    stocks = list(resid)
    residuals = pd.DataFrame(
        [(day, s, resid[s][t], betas[s]) for s in stocks for t, day in enumerate(cal) if t >= 20],
        columns=["date", "ticker", "residual", "beta_market"],
    )
    universe = pd.DataFrame([(day, s, cal[0]) for day in cal for s in stocks], columns=["date", "ticker", "rebalanced_on"])
    sectors = pd.DataFrame(sector_rows, columns=["ticker", "sector", "valid_from", "valid_to"]).astype(
        {"valid_from": "datetime64[ns]", "valid_to": "datetime64[ns]"}
    )
    return returns, prices, residuals, universe, sectors


# Model B on the synthetic market: a window and factor count small enough for its 30 stocks.
PCA = PcaModelConfig(factors=3, window_days=60, min_observations=45)


def model_b(returns: pd.DataFrame, stocks: list[str]) -> pd.DataFrame:
    return PcaFactorModel(PCA).residuals(returns, pd.DataFrame(), stocks, MARKET_CAL)
