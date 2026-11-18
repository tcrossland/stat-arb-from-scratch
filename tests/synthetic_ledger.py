"""A small synthetic ledger for the explorer's tests and its demonstration: made-up names, returns and holdings.

Six days on five names. A holding of None keeps the drifted weight, so the name does not trade. The book is built
to cover each kind of trade (open, close, flip, add, reduce), a sector change, a name joining the grid and a name
with no sector (HX, standing in for a hedge ETF).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from statarb.backtest.engine import Step
from statarb.data.schema import DATE, TICKER
from statarb.paper import ledger

BOOK_SIZE = 1e6
META = ledger.DayMeta(book_size=BOOK_SIZE, config_hash="0123456789abcdef", git_commit="deadbeef", git_dirty=False, snapshot="2026-01-02")
DATES = pd.bdate_range("2026-01-05", periods=6)
BORROW_RATE = 1e-4          # per day, on a short holding carried in
CHANGE = DATES[3]           # BB moves from Tech to Energy

# Holdings after each open's fill, by day; a name absent from a day's grid is not listed.
HOLDINGS: list[dict[str, float | None]] = [
    {"AA": 0.10, "BB": -0.10, "CC": 0.0, "HX": 0.0},
    {"AA": None, "BB": None, "CC": 0.05, "HX": -0.05},
    {"AA": 0.0, "BB": 0.10, "CC": None, "HX": None},
    {"AA": 0.0, "BB": None, "CC": 0.08, "DD": 0.0, "HX": -0.03},
    {"AA": 0.02, "BB": None, "CC": None, "DD": 0.0, "HX": None},
    {"AA": None, "BB": None, "CC": None, "DD": None, "HX": None},
]

SECTORS = pd.DataFrame({
    TICKER: ["AA", "BB", "BB", "CC", "DD"],
    "sector": ["Tech", "Tech", "Energy", "Health", "Tech"],
    "valid_from": pd.to_datetime(["2016-01-04", "2016-01-04", CHANGE, "2016-01-04", "2016-01-04"]).astype("datetime64[ns]"),
    "valid_to": pd.to_datetime([None, CHANGE, None, None, None]).astype("datetime64[ns]"),
})


def frames(seed: int = 0) -> list[pd.DataFrame]:
    """The ledger's days, chained as the daily job chains them."""
    rng = np.random.default_rng(seed)
    out, carry = [], ledger.Carry.flat(tuple(sorted(HOLDINGS[0])))
    for date, plan in zip(DATES, HOLDINGS, strict=True):
        tickers = tuple(sorted(plan))
        carry = carry.on(tickers)
        held = carry.holdings
        ret = np.round(rng.normal(0.0, 0.02, len(tickers)), 4)
        drifted = held * (1.0 + ret)
        holdings = np.array([drifted[i] if plan[t] is None else plan[t] for i, t in enumerate(tickers)])
        trades = holdings - drifted
        traded = float(np.abs(trades).sum())
        step = Step(returns=ret, pnl=held * ret, borrow=BORROW_RATE * np.clip(-held, 0.0, None), drifted=drifted,
                    holdings=holdings, trades=trades, missing=0)
        totals = ledger.DayTotals(cost_spread=1e-4 * traded, cost_impact=2e-4 * traded, cost_commission=5e-5 * traded,
                                  slope=0.5, status="optimal")
        moves = np.round(rng.normal(0.0, 0.003, len(tickers)), 5)
        frame = ledger.day_frame(date, tickers, held, step, np.full(len(tickers), np.nan), moves, META, totals)
        out.append(frame)
        carry = ledger.carry_of(frame)
    return out


def write(paper: Path, seed: int = 0) -> list[pd.DataFrame]:
    """Write the ledger under `paper`/ledger and the sectors as a complete processed snapshot, as the daily job does."""
    days = frames(seed)
    for frame in days:
        ledger.write_day(paper / "ledger", frame)
    snapshot = paper / "processed" / META.snapshot
    snapshot.mkdir(parents=True)
    SECTORS.to_parquet(snapshot / "sectors.parquet", index=False)
    (snapshot / "COMPLETE").touch()
    return days


def concat(days: list[pd.DataFrame]) -> pd.DataFrame:
    return pd.concat(days, ignore_index=True).sort_values([DATE, TICKER], kind="mergesort").reset_index(drop=True)
