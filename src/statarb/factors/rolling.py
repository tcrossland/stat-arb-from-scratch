"""Rolling least squares on a dates x stocks panel, with windows that end the day before.

The coefficients on row t are estimated from rows t-window to t-1 only, so
they never depend on data from t or later. Window sums come from cumulative
sums taken from the first row forwards, so a value on row t is unchanged by
any later row.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RollingFit:
    coef: np.ndarray    # (dates, stocks, 1 + regressors); intercept first; NaN where not estimated
    n_obs: np.ndarray   # (dates, stocks) rows used in each window


def _lagged_window_sum(values: np.ndarray, window: int) -> np.ndarray:
    """Sum over rows t-window .. t-1 for every row t (zero rows for t = 0)."""
    cumulative = np.concatenate([np.zeros_like(values[:1]), np.cumsum(values, axis=0)])
    rows = np.arange(values.shape[0])
    return cumulative[rows] - cumulative[np.maximum(rows - window, 0)]


def rolling_ols(
    y: np.ndarray, regressors: list[np.ndarray], window: int, min_obs: int, max_condition: float = 1e10
) -> RollingFit:
    """Regress y on an intercept and the regressors, stock by stock, in lagged rolling windows.

    All arrays are (dates, stocks). A row enters a window only if y and every
    regressor are finite on it. A window whose normal matrix is too badly
    conditioned (a regressor constant over it, say) gets no coefficients.
    """
    if min_obs > window:
        raise ValueError("min_obs cannot exceed the window")
    X = np.stack([np.ones_like(y), *regressors], axis=-1)
    valid = np.isfinite(y) & np.isfinite(X).all(axis=-1)
    Xv = np.where(valid[..., None], X, 0.0)
    yv = np.where(valid, y, 0.0)

    n_obs = _lagged_window_sum(valid.astype(np.int64), window)
    xtx = _lagged_window_sum(Xv[..., :, None] * Xv[..., None, :], window)
    xty = _lagged_window_sum(Xv * yv[..., None], window)

    coef = np.full(X.shape, np.nan)
    enough = n_obs >= min_obs
    if enough.any():
        a, b = xtx[enough], xty[enough]
        solvable = np.linalg.cond(a) < max_condition
        solved = np.full(b.shape, np.nan)
        solved[solvable] = np.linalg.solve(a[solvable], b[solvable][..., None])[..., 0]
        coef[enough] = solved
    return RollingFit(coef=coef, n_obs=n_obs)
