"""Daily backtest engine: target weights in, positions, trades and P&L out.

Time runs on a grid of fill times, one per trading day: the close of each day,
or the open. The return at grid time s is the return from grid time s-1 to s,
on the same total-return basis as phase 0 (split_ratio and cash going ex on
the day), so open and close grids are comparable.

A target decided at the close of day t is filled at grid time t + delay:

    close_t   close grid, delay 0   (optimistic: same close as the signal)
    open_t1   open grid,  delay 1
    close_t1  close grid, delay 1

At each grid time s the engine first books the P&L of the holdings filled at
s-1, lets them drift with the returns, then trades to the targets. A NaN target
means "keep the drifted holding" (used by threshold rules that hold until a
close signal); a name with no bar at s cannot trade and keeps its holding. A
held name with no return at s is booked at zero and counted.

Weights are dollars per unit of capital, with no leverage built in. Results are
reported per dollar of gross exposure (metrics.daily_returns), so the scale of
the targets does not matter.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from statarb.backtest.costs import CostModel
from statarb.data.schema import DATE, TICKER

TRADING_DAYS = 252

# (grid, delay) for each fill timing.
FILL_TIMINGS = {"close_t": ("close", 0), "open_t1": ("open", 1), "close_t1": ("close", 1)}


@dataclass(frozen=True)
class Grid:
    """Returns and tradability on a (dates x tickers) grid of fill times."""

    kind: str
    dates: pd.DatetimeIndex
    tickers: tuple[str, ...]
    returns: np.ndarray      # return from grid time s-1 to s; NaN if no bar at s
    tradable: np.ndarray     # bool: a bar (and so a price to trade at) exists at s


def close_grid(returns: pd.DataFrame, prices: pd.DataFrame, dates: pd.DatetimeIndex, tickers: list[str]) -> Grid:
    """Close-to-close total returns from phase 0's returns table."""
    ret = returns.pivot(index=DATE, columns=TICKER, values="ret").reindex(index=dates, columns=tickers)
    bar = prices.pivot(index=DATE, columns=TICKER, values="close").reindex(index=dates, columns=tickers)
    return Grid("close", dates, tuple(tickers), ret.to_numpy(dtype="float64"), bar.notna().to_numpy())


def open_to_open_returns(prices: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    """Open-to-open total returns: split_ratio * (open + cash) / previous open - 1.

    A split or dividend going ex on day d takes effect at the open of d, so it
    belongs to the return ending at that open, exactly as for close returns.
    """
    actions = returns[[DATE, TICKER, "split_ratio", "cash"]]
    bars = prices[[DATE, TICKER, "open"]].merge(actions, on=[DATE, TICKER], how="left")
    bars = bars.sort_values([TICKER, DATE], kind="mergesort").reset_index(drop=True)
    prev_open = bars.groupby(TICKER, sort=False)["open"].shift(1)
    ret = bars["split_ratio"].fillna(1.0) * (bars["open"] + bars["cash"].fillna(0.0)) / prev_open - 1.0
    return pd.DataFrame({DATE: bars[DATE], TICKER: bars[TICKER], "ret": ret}).loc[prev_open.notna()]


def open_grid(returns: pd.DataFrame, prices: pd.DataFrame, dates: pd.DatetimeIndex, tickers: list[str]) -> Grid:
    ret = open_to_open_returns(prices, returns).pivot(index=DATE, columns=TICKER, values="ret")
    bar = prices.pivot(index=DATE, columns=TICKER, values="open")
    return Grid(
        "open",
        dates,
        tuple(tickers),
        ret.reindex(index=dates, columns=tickers).to_numpy(dtype="float64"),
        bar.reindex(index=dates, columns=tickers).notna().to_numpy(),
    )


@dataclass(frozen=True)
class EngineResult:
    dates: pd.DatetimeIndex
    tickers: tuple[str, ...]
    holdings: np.ndarray     # after the fill at s
    trades: np.ndarray       # holdings minus drifted holdings at s
    pnl: np.ndarray          # P&L at s of the holdings filled at s-1, per name
    borrow: np.ndarray       # borrow cost at s on the short holdings filled at s-1, per day
    gross_held: np.ndarray   # sum |holdings filled at s-1|, per day
    gross_after: np.ndarray  # sum |holdings filled at s|, per day
    missing_returns: int     # held name-days with no return (booked as zero)



@dataclass(frozen=True)
class Step:
    """One grid time: the P&L of the holdings carried in, then the trade to the targets."""

    returns: np.ndarray      # return used for each name, zero where there was none
    pnl: np.ndarray          # held * returns
    borrow: np.ndarray       # borrow cost per name on the short holdings carried in
    drifted: np.ndarray      # held moved with prices to this grid time
    holdings: np.ndarray     # after the fill
    trades: np.ndarray       # holdings minus drifted
    missing: int             # held names with no return (booked as zero)


def step(
    held: np.ndarray,
    returns: np.ndarray,
    tradable: np.ndarray,
    target: np.ndarray,
    rate: np.ndarray,
) -> Step:
    """Grid time s, given the holdings filled at s-1, the row of returns, tradability and
    daily borrow rates at s, and the target due at s (already shifted by the delay)."""
    known = np.isfinite(returns)
    missing = int(np.count_nonzero((held != 0) & ~known))
    r = np.where(known, returns, 0.0)
    owed = rate * np.minimum(held, 0.0)
    drifted = held * (1.0 + r)
    new = np.where(np.isfinite(target) & tradable, target, drifted)
    return Step(r, held * r, -owed, drifted, new, new - drifted, missing)


def daily_rates(borrow_annual: float | np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Daily borrow rate per grid time and name, from a flat annual rate or a panel of them."""
    return np.broadcast_to(np.asarray(borrow_annual, dtype="float64"), shape) / TRADING_DAYS


def shift_targets(targets: np.ndarray, delay: int) -> np.ndarray:
    """Targets decided at the close of t, moved to the grid time t + delay they are filled at."""
    T, N = targets.shape
    shifted = np.full((T, N), np.nan)
    shifted[delay:] = targets[: T - delay] if delay else targets
    return shifted


def run(
    targets: np.ndarray,
    grid: Grid,
    delay: int,
    borrow_annual: float | np.ndarray,
) -> EngineResult:
    """Fill `targets` (decided at the close of each date) at grid time t + delay.

    `borrow_annual` is a flat rate or a (dates x tickers) panel of rates, where
    row s applies to the shorts held from s-1 to s.
    """
    T, N = grid.returns.shape
    if targets.shape != (T, N):
        raise ValueError(f"targets shape {targets.shape} does not match grid {grid.returns.shape}")
    shifted = shift_targets(targets, delay)
    rates = daily_rates(borrow_annual, (T, N))

    holdings = np.zeros((T, N))
    trades = np.zeros((T, N))
    pnl = np.zeros((T, N))
    borrow = np.zeros(T)
    gross_held = np.zeros(T)
    held = np.zeros(N)
    missing = 0
    for s in range(T):
        out = step(held, grid.returns[s], grid.tradable[s], shifted[s], rates[s])
        pnl[s] = out.pnl
        borrow[s] = out.borrow.sum()
        gross_held[s] = np.abs(held).sum()
        trades[s] = out.trades
        holdings[s] = out.holdings
        missing += out.missing
        held = out.holdings
    return EngineResult(
        dates=grid.dates,
        tickers=grid.tickers,
        holdings=holdings,
        trades=trades,
        pnl=pnl,
        borrow=borrow,
        gross_held=gross_held,
        gross_after=np.abs(holdings).sum(axis=1),
        missing_returns=missing,
    )


def daily_returns(result: EngineResult, cost: CostModel) -> pd.DataFrame:
    """Per-day returns on gross exposure: gross, costs, borrow and net, plus turnover.

    The denominator is the gross exposure that earned the day's P&L. On a day
    that starts flat it is the gross just traded into, so the cost of the first
    trades is not lost. Days with no position before or after are dropped.
    """
    base = np.where(result.gross_held > 0, result.gross_held, result.gross_after)
    keep = base > 0
    denom = np.where(keep, base, 1.0)
    traded = np.abs(result.trades).sum(axis=1)
    parts = cost.components(result.trades, base)
    frame = pd.DataFrame(
        {
            "gross": result.pnl.sum(axis=1) / denom,
            "cost": sum(parts.values()) / denom,
            "borrow": result.borrow / denom,
            "turnover": traded / denom,
            "exposure": base,
        },
        index=result.dates,
    )
    prev = np.vstack([np.zeros((1, result.holdings.shape[1])), result.holdings[:-1]])
    frame["long_pnl"] = np.where(prev > 0, result.pnl, 0.0).sum(axis=1) / denom
    frame["short_pnl"] = np.where(prev < 0, result.pnl, 0.0).sum(axis=1) / denom
    for name, value in parts.items():
        frame[f"cost_{name}"] = value / denom
    frame["net"] = frame["gross"] - frame["cost"] - frame["borrow"]
    frame.index.name = DATE
    return frame.loc[keep]
