"""Portfolio rules: scores and universe membership in, a target-weights panel out.

Two implementations behind one interface. The decile rule sorts each day and
holds each day's book for k days in overlapping slices; the threshold rule
opens and closes positions on the s-score and carries them from day to day.
Targets are decided at the close of each date; the engine fills them later
(`statarb.backtest.engine`). A NaN target means "hold what you have".

The panel's columns are the stocks, then the hedge instruments (the sector
ETFs, then the market), so a rule that hedges can trade them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from statarb.signals.base import Hedge, Scores


class PortfolioRule(Protocol):
    def targets(self, scores: Scores, members: np.ndarray, start: int, hedges: int) -> np.ndarray:
        """(dates x (stocks + hedges)) targets, NaN before `start`, the first date a book may be held."""
        ...


def decile_portfolio(signal: np.ndarray, members: np.ndarray, fraction: float) -> np.ndarray:
    """Equal-weight long top / short bottom `fraction` of members with a signal, each day.

    Each leg holds floor(fraction x names) names and 0.5 of gross. Ties are broken
    by column order, so the result is deterministic. A day with fewer than one
    name per leg is flat.
    """
    T, N = signal.shape
    out = np.zeros((T, N))
    columns = np.arange(N)
    for t in range(T):
        ok = members[t] & np.isfinite(signal[t])
        idx = columns[ok]
        q = int(np.floor(len(idx) * fraction))
        if q < 1:
            continue
        order = idx[np.lexsort((idx, signal[t, idx]))]
        out[t, order[:q]] = -0.5 / q
        out[t, order[-q:]] = 0.5 / q
    return out


def holding_slices(daily: np.ndarray, k: int) -> np.ndarray:
    """Average of the last k daily portfolios; days before the first count as flat."""
    if k < 1:
        raise ValueError("k must be at least 1")
    total = np.zeros_like(daily, dtype="float64")
    for lag in range(k):
        total[lag:] += daily[: len(daily) - lag]
    return total / k


@dataclass(frozen=True)
class DecileRule:
    fraction: float
    holding_days: int

    def targets(self, scores: Scores, members: np.ndarray, start: int, hedges: int) -> np.ndarray:
        daily = decile_portfolio(scores.score, members, self.fraction)
        daily[:start] = 0.0
        out = np.hstack([holding_slices(daily, self.holding_days), np.zeros((len(daily), hedges))])
        out[:start] = np.nan
        return out


def threshold_positions(
    score: np.ndarray,
    members: np.ndarray,
    first: int,
    open_level: float,
    close_long: float,
    close_short: float,
) -> np.ndarray:
    """(dates x stocks) position state in {-1, 0, +1}, decided at the close of each day from `first` on.

    A position closes when its rule fires, or when the stock leaves the universe
    or loses its score; it can reopen the other way the same day.
    """
    T, N = score.shape
    out = np.zeros((T, N), dtype=np.int8)
    pos = np.zeros(N, dtype=np.int8)
    for t in range(first, T):
        s = score[t]
        ok = members[t] & np.isfinite(s)
        new = pos.copy()
        new[(pos != 0) & ~ok] = 0
        new[(pos == 1) & ok & (s > -close_long)] = 0
        new[(pos == -1) & ok & (s < close_short)] = 0
        flat = (new == 0) & ok
        new[flat & (s < -open_level)] = 1
        new[flat & (s > open_level)] = -1
        out[t] = new
        pos = new
    return out


def hedged_targets(
    positions: np.ndarray,
    hedge: Hedge,
    n_hedges: int,
    first: int,
    weight: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Target weights for stocks and for the hedge instruments (sector ETFs, then the market).

    Stocks: `weight` per open position, set on the day it opens or closes and NaN
    (hold) otherwise, so a position is not rebalanced while open. Hedges: each
    open position of signed size w is hedged with -w x beta_sector of its sector
    ETF and -w x (beta_market - beta_sector) of the market, using the betas and
    ETF from the day it opened; hedge targets are reset every day.
    """
    T, N = positions.shape
    market_col = n_hedges - 1
    stock = np.full((T, N), np.nan)
    out = np.full((T, n_hedges), np.nan)
    prev = np.zeros(N, dtype=np.int8)
    entry_bm = np.zeros(N)
    entry_bs = np.zeros(N)
    entry_etf = np.full(N, -1)
    for t in range(first, T):
        pos = positions[t]
        changed = pos != prev
        stock[t, changed] = pos[changed] * weight
        opened = changed & (pos != 0)
        entry_bm[opened] = hedge.beta_market[t, opened]
        entry_bs[opened] = hedge.beta_sector[t, opened]
        entry_etf[opened] = hedge.etf_index[t, opened]
        h = np.zeros(n_hedges)
        live = pos != 0
        w = pos[live] * weight
        np.add.at(h, entry_etf[live], -w * entry_bs[live])
        h[market_col] += float(np.sum(-w * (entry_bm[live] - entry_bs[live])))
        out[t] = h
        prev = pos
    return stock, out


@dataclass(frozen=True)
class ThresholdRule:
    """Avellaneda and Lee's entry and exit thresholds on the s-score, each position hedged."""

    open: float
    close_long: float
    close_short: float
    position_weight: float

    def targets(self, scores: Scores, members: np.ndarray, start: int, hedges: int) -> np.ndarray:
        if scores.hedge is None:
            raise ValueError("the threshold rule needs a signal that estimates hedge ratios")
        positions = threshold_positions(scores.score, members, start, self.open, self.close_long, self.close_short)
        stock, hedge = hedged_targets(positions, scores.hedge, hedges, start, self.position_weight)
        stock[:start] = np.nan
        hedge[:start] = np.nan
        return np.hstack([stock, hedge])
