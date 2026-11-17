"""Model B: statistical factors from principal components of stock returns.

After Avellaneda and Lee (2010), section 2.1. For each day t, over the
`window_days` trading days ending t-1:

1. Take the stocks with a return on every day of the window, standardise each
   one's returns, and form their correlation matrix.
2. Keep the eigenvectors v_k of its `factors` largest eigenvalues. Eigenportfolio
   k holds v_ik / sigma_i of stock i, so its return on any day is that weighted
   sum of the stocks' returns.
3. Regress each stock with at least `min_observations` returns in the window on
   an intercept and the eigenportfolio returns over the window.
4. The residual on t is the stock's return on t less its betas times the
   eigenportfolio returns on t. As in Model A, the intercept is estimated but
   not subtracted.

Every estimate on row t uses rows before t only; the returns of t enter only
the residual itself. Over the window, the eigenportfolio returns have
covariance diag(eigenvalues) exactly, since they come from the same
standardised returns; the risk model reads the factor variances from the
`eigenvalue_k` columns.

Eigenvectors are defined up to sign, and their order can swap when two
eigenvalues are close. The residuals, and the risk and neutrality the optimiser
builds from the betas, depend on neither.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, fields
from typing import Any

import numpy as np
import pandas as pd
from scipy.linalg import eigh

from statarb.data.schema import DATE, TICKER
from statarb.factors.model import wide


@dataclass(frozen=True)
class PcaModelConfig:
    factors: int
    window_days: int
    min_observations: int

    @classmethod
    def from_config(cls, data: dict[str, Any]) -> PcaModelConfig:
        """From `[pca]` of config/factors.toml; unknown or missing keys fail."""
        expected = {f.name for f in fields(cls)}
        if set(data) != expected:
            raise ValueError(f"[pca] keys: missing {sorted(expected - set(data))}, unknown {sorted(set(data) - expected)}")
        cfg = cls(**data)
        if not 0 < cfg.min_observations <= cfg.window_days:
            raise ValueError("min_observations must be in 1..window_days")
        if cfg.factors < 1:
            raise ValueError("factors must be at least 1")
        return cfg


def beta_columns(k: int) -> list[str]:
    return [f"beta_{i + 1}" for i in range(k)]


def eigenvalue_columns(k: int) -> list[str]:
    return [f"eigenvalue_{i + 1}" for i in range(k)]


@dataclass(frozen=True)
class WindowFit:
    """What one window of returns gives: the eigenportfolios and each stock's regression on them."""

    weights: np.ndarray       # (stocks, k) eigenportfolio weights; zero outside the estimation set
    eigenvalues: np.ndarray   # (k,), largest first
    coef: np.ndarray          # (stocks, 1 + k): intercept, then betas; NaN where not estimated
    n_obs: np.ndarray         # (stocks,) returns in the window


def fit_window(window: np.ndarray, k: int, min_obs: int) -> WindowFit | None:
    """Fit the eigenportfolios and betas on one window (rows = days, columns = stocks); None if too few stocks."""
    n_days, n_stocks = window.shape
    finite = np.isfinite(window)
    complete = finite.all(axis=0)
    est = window[:, complete]
    if est.shape[1] <= k:
        return None
    sd = est.std(axis=0, ddof=1)
    if not (sd > 0).all():
        # A stock with no variation in the window cannot be standardised: leave it out.
        idx = np.flatnonzero(complete)
        keep = sd > 0
        complete = np.zeros(n_stocks, dtype=bool)
        complete[idx[keep]] = True
        est, sd = est[:, keep], sd[keep]
    z = (est - est.mean(axis=0)) / sd
    corr = z.T @ z / (n_days - 1)
    m = corr.shape[0]
    values, vectors = eigh(corr, subset_by_index=[m - k, m - 1])
    order = np.argsort(values)[::-1]
    values, vectors = values[order], vectors[:, order]
    weights = np.zeros((n_stocks, k))
    weights[complete] = vectors / sd[:, None]
    factor_returns = est @ weights[complete]                       # (days, k)

    X = np.column_stack([np.ones(n_days), factor_returns])
    coef = np.full((n_stocks, k + 1), np.nan)
    counts = finite.sum(axis=0)
    full = counts == n_days
    if full.any():
        coef[full] = np.linalg.lstsq(X, window[:, full], rcond=None)[0].T
    for j in np.flatnonzero(~full & (counts >= min_obs)):
        rows = finite[:, j]
        coef[j] = np.linalg.lstsq(X[rows], window[rows, j], rcond=None)[0]
    return WindowFit(weights, values, coef, counts)


class PcaFactorModel:
    """Model B behind the FactorModel protocol."""

    name = "pca"

    def __init__(self, config: PcaModelConfig) -> None:
        self.config = config

    def residuals(
        self, returns: pd.DataFrame, sectors: pd.DataFrame, stocks: Sequence[str], calendar: pd.DatetimeIndex
    ) -> pd.DataFrame:
        """One row per (date, stock) with a residual. `sectors` is unused: the factors come from the returns alone."""
        cfg = self.config
        k = cfg.factors
        stocks = sorted(stocks)
        y = wide(returns, "ret", calendar, stocks).to_numpy()
        T, N = y.shape
        fitted = np.full((T, N), np.nan)
        betas = np.full((T, N, k), np.nan)
        eig = np.full((T, k), np.nan)
        n_obs = np.zeros((T, N), dtype=np.int64)
        for t in range(cfg.window_days, T):
            fit = fit_window(y[t - cfg.window_days : t], k, cfg.min_observations)
            if fit is None:
                continue
            factor_today = np.nan_to_num(y[t]) @ fit.weights          # a stock with no return on t counts as zero
            fitted[t] = fit.coef[:, 1:] @ factor_today
            betas[t] = fit.coef[:, 1:]
            eig[t] = fit.eigenvalues
            n_obs[t] = fit.n_obs
        keep = np.isfinite(fitted) & np.isfinite(y)
        t_idx, s_idx = np.nonzero(keep)
        out = pd.DataFrame(
            {
                DATE: calendar[t_idx],
                TICKER: np.asarray(stocks, dtype=object)[s_idx],
                "ret": y[t_idx, s_idx],
                "fitted": fitted[t_idx, s_idx],
                "residual": y[t_idx, s_idx] - fitted[t_idx, s_idx],
                "n_obs": n_obs[t_idx, s_idx],
            }
        )
        for i, name in enumerate(beta_columns(k)):
            out[name] = betas[t_idx, s_idx, i]
        for i, name in enumerate(eigenvalue_columns(k)):
            out[name] = eig[t_idx, i]
        return out.astype({DATE: "datetime64[ns]", TICKER: "str"})
