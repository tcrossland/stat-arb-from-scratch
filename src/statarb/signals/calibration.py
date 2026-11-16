"""Signal calibration to return units: the expected move over the next h days.

On day t the slope is estimated from signal-outcome pairs whose outcome is
known by the close of t. The outcome of a signal on day d is the sum of the
series over d+1 to d+h, known at the close of d+h, so only pairs with
d <= t-h qualify: the newest pair starts h days back (docs/time-discipline.md).

The regression is pooled over universe members and a trailing window of signal
dates, with signal and outcome demeaned across members each day, so the slope
measures cross-sectional reversal, not market-wide moves. Phase 3 uses it for
the no-trade zone; phase 4 reuses it for the optimiser's expected returns.
"""

from __future__ import annotations

import numpy as np


def forward_sum(series: np.ndarray, horizon: int) -> np.ndarray:
    """Row d: sum of series over rows d+1 to d+horizon; NaN unless all are present."""
    T, N = series.shape
    out = np.full((T, N), np.nan)
    if horizon < 1 or horizon >= T:
        return out
    csum = np.vstack([np.zeros((1, N)), np.cumsum(np.nan_to_num(series), axis=0)])
    cnt = np.vstack([np.zeros((1, N)), np.cumsum(np.isfinite(series), axis=0)])
    d = np.arange(T - horizon)
    total = csum[d + horizon + 1] - csum[d + 1]
    full = (cnt[d + horizon + 1] - cnt[d + 1]) == horizon
    out[: T - horizon] = np.where(full, total, np.nan)
    return out


def _demean(panel: np.ndarray, ok: np.ndarray) -> np.ndarray:
    n = ok.sum(axis=1)
    mean = np.where(n > 0, np.where(ok, panel, 0.0).sum(axis=1) / np.maximum(n, 1), 0.0)
    return np.where(ok, panel - mean[:, None], 0.0)


def calibration_slope(
    signal: np.ndarray,
    outcome: np.ndarray,
    members: np.ndarray,
    horizon: int,
    window: int,
    min_days: int,
) -> np.ndarray:
    """Slope b_t of outcome on signal, pooled over signal dates t-horizon-window+1 to t-horizon.

    `outcome` row d is the realised move after the signal of day d (for example
    `forward_sum(residual, horizon)`). NaN until `min_days` signal dates with
    pairs are available.
    """
    T = signal.shape[0]
    ok = members & np.isfinite(signal) & np.isfinite(outcome)
    x = _demean(signal, ok)
    y = _demean(outcome, ok)
    sxy = (x * y).sum(axis=1)
    sxx = (x * x).sum(axis=1)
    has = ok.sum(axis=1) >= 2
    cxy = np.concatenate([[0.0], np.cumsum(sxy)])
    cxx = np.concatenate([[0.0], np.cumsum(sxx)])
    cdays = np.concatenate([[0], np.cumsum(has)])
    slope = np.full(T, np.nan)
    for t in range(T):
        last = t - horizon                 # newest signal date whose outcome is known at t
        if last < 0:
            continue
        first = max(0, last - window + 1)
        days = cdays[last + 1] - cdays[first]
        den = cxx[last + 1] - cxx[first]
        if days >= min_days and den > 0:
            slope[t] = (cxy[last + 1] - cxy[first]) / den
    return slope


def expected_move(signal: np.ndarray, members: np.ndarray, slope: np.ndarray) -> np.ndarray:
    """Expected move of each member over the horizon, from its signal on t: b_t times the demeaned signal."""
    ok = members & np.isfinite(signal)
    move = _demean(signal, ok) * slope[:, None]
    return np.where(ok & np.isfinite(slope)[:, None], move, np.nan)
