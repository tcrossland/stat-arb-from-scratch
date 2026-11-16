"""Performance metrics on daily returns per dollar of gross exposure.

Returns are long-short and on gross, with no cash rate: Sharpe is the mean over
the standard deviation of daily returns, times sqrt(252). Drawdown is measured
on cumulative summed returns, which is the P&L of a book kept at constant gross.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

from statarb.backtest.engine import TRADING_DAYS, EngineResult


def sharpe(returns: pd.Series) -> float:
    sd = returns.std()
    return float(returns.mean() / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else float("nan")


def max_drawdown(returns: pd.Series) -> float:
    cum = returns.cumsum()
    return float((cum - cum.cummax()).min())


def break_even_bps(daily: pd.DataFrame) -> float:
    """One-way cost (bps) at which mean net return, and so net Sharpe, is zero.

    Net = gross - cost x turnover - borrow is linear in the cost, so this is exact
    for the flat cost model. `daily` must come from a zero-cost run.
    """
    to = daily["turnover"].mean()
    return float((daily["gross"].mean() - daily["borrow"].mean()) / to * 1e4) if to > 0 else float("nan")


def position_hit_rate(result: EngineResult) -> float:
    """Share of held position-days whose gross P&L was positive."""
    prev = np.vstack([np.zeros((1, result.holdings.shape[1])), result.holdings[:-1]])
    held = prev != 0
    return float((result.pnl[held] > 0).mean()) if held.any() else float("nan")


def summary(daily: pd.DataFrame) -> dict[str, float]:
    net, gross = daily["net"], daily["gross"]
    return {
        "days": len(daily),
        "ann_return": float(net.mean() * TRADING_DAYS),
        "ann_vol": float(net.std() * math.sqrt(TRADING_DAYS)),
        "sharpe": sharpe(net),
        "gross_sharpe": sharpe(gross),
        "ann_gross_return": float(gross.mean() * TRADING_DAYS),
        "max_drawdown": max_drawdown(net),
        "turnover": float(daily["turnover"].mean()),
        "ann_cost": float(daily["cost"].mean() * TRADING_DAYS),
        "ann_borrow": float(daily["borrow"].mean() * TRADING_DAYS),
        "ann_long_pnl": float(daily["long_pnl"].mean() * TRADING_DAYS),
        "ann_short_pnl": float(daily["short_pnl"].mean() * TRADING_DAYS),
        "day_hit_rate": float((net > 0).mean()),
    }


def by_year(daily: pd.DataFrame) -> pd.DataFrame:
    g = daily.groupby(daily.index.year)
    return pd.DataFrame(
        {
            "days": g.size(),
            "gross_return": g["gross"].sum(),
            "net_return": g["net"].sum(),
            "gross_sharpe": g["gross"].apply(sharpe),
            "net_sharpe": g["net"].apply(sharpe),
            "turnover": g["turnover"].mean(),
        }
    )


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """Bailey and Lopez de Prado (2014): expected maximum of n independent Sharpe estimates under the null.

    Inputs and output are per-period (daily), not annualised.
    """
    if n_trials < 2:
        return 0.0
    gamma = 0.5772156649015329
    z = NormalDist()
    return math.sqrt(sharpe_variance) * (
        (1 - gamma) * z.inv_cdf(1 - 1 / n_trials) + gamma * z.inv_cdf(1 - 1 / (n_trials * math.e))
    )


def deflated_sharpe(returns: pd.Series, n_trials: int, trial_sharpes: np.ndarray) -> dict[str, float]:
    """Probability that the true Sharpe exceeds the best expected from n_trials of noise.

    `trial_sharpes` are the daily (not annualised) Sharpe ratios of all trials,
    used for their variance. Follows Bailey and Lopez de Prado (2014), eq. 2 and
    the expected-maximum benchmark above; trials are treated as independent,
    which overstates the effective number when they are correlated.
    """
    r = returns.to_numpy()
    T = len(r)
    sr = r.mean() / r.std(ddof=1)
    skew = float(pd.Series(r).skew())
    kurt = float(pd.Series(r).kurt()) + 3.0
    sr0 = expected_max_sharpe(n_trials, float(np.var(trial_sharpes, ddof=1)))
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr**2, 1e-12))
    dsr = NormalDist().cdf((sr - sr0) * math.sqrt(T - 1) / denom)
    return {
        "sharpe": sr * math.sqrt(TRADING_DAYS),
        "benchmark_sharpe": sr0 * math.sqrt(TRADING_DAYS),
        "deflated_sharpe_probability": dsr,
        "trials": n_trials,
    }
