"""Model B: the eigenportfolios, partial histories, strict config and look-ahead."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_CAL, PCA, model_b, synthetic_market
from statarb.factors.pca import (
    PcaModelConfig,
    beta_columns,
    eigenvalue_columns,
    fit_window,
)
from statarb.testing.lookahead import perturb_after


def _factor_returns(seed: int = 0, days: int = 120, stocks: int = 40, k: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    f = rng.normal(0, 0.01, (days, k))
    load = rng.normal(1, 0.5, (stocks, k))
    return f @ load.T + rng.normal(0, 0.01, (days, stocks))


def test_eigenvalues_are_the_eigenportfolios_variances() -> None:
    window = _factor_returns()
    fit = fit_window(window, 3, 90)
    factor_returns = window @ fit.weights
    np.testing.assert_allclose(factor_returns.var(axis=0, ddof=1), fit.eigenvalues, rtol=1e-10)
    # The eigenportfolios are uncorrelated over the window, so diag(eigenvalues) is their covariance.
    cov = np.cov(factor_returns, rowvar=False)
    np.testing.assert_allclose(cov - np.diag(np.diag(cov)), 0.0, atol=1e-10 * fit.eigenvalues[0])
    assert np.all(np.diff(fit.eigenvalues) <= 0)


def test_partial_histories_get_betas_but_do_not_shape_the_factors() -> None:
    window = _factor_returns()
    partial = window.copy()
    partial[:20, 0] = np.nan            # 100 of 120 days: enough for a regression
    partial[:40, 1] = np.nan            # 80 of 120: too few
    full, part = fit_window(window[:, 2:], 3, 90), fit_window(partial, 3, 90)
    np.testing.assert_allclose(part.eigenvalues, full.eigenvalues)
    assert np.all(part.weights[:2] == 0.0)
    assert np.isfinite(part.coef[0]).all() and np.isnan(part.coef[1]).all()
    assert part.n_obs[0] == 100


def test_too_few_complete_stocks_give_no_fit() -> None:
    assert fit_window(_factor_returns(stocks=3), 3, 90) is None


def test_model_b_has_no_look_ahead() -> None:
    returns, *_, residuals, _, _ = synthetic_market(seed=3)
    stocks = sorted(residuals["ticker"].unique())
    base = model_b(returns, stocks)
    cutoff = MARKET_CAL[150]
    other = model_b(perturb_after(returns, cutoff, ["ret"], seed=4, scale=1.0), stocks)
    cols = ["date", "ticker", "residual", *beta_columns(PCA.factors), *eigenvalue_columns(PCA.factors)]
    a = base.loc[base["date"] <= cutoff, cols].reset_index(drop=True)
    b = other.loc[other["date"] <= cutoff, cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_exact=True)
    assert not base.loc[base["date"] > cutoff, "residual"].equals(other.loc[other["date"] > cutoff, "residual"])
    # The first return is on the calendar's second day, so the first complete window ends a day later.
    assert base["date"].min() == MARKET_CAL[PCA.window_days + 1]


def test_model_b_residuals_remove_the_common_factor() -> None:
    returns, *_, residuals, _, _ = synthetic_market(seed=3)
    out = model_b(returns, sorted(residuals["ticker"].unique()))
    panel = out.pivot(index="date", columns="ticker", values="residual")
    raw = out.pivot(index="date", columns="ticker", values="ret")
    off = lambda c: c[~np.eye(len(c), dtype=bool)].mean()
    assert abs(off(panel.corr().to_numpy())) < 0.2 * off(raw.corr().to_numpy())


def test_pca_config_rejects_unknown_or_missing_keys() -> None:
    good = {"factors": 15, "window_days": 252, "min_observations": 189}
    assert PcaModelConfig.from_config(good).factors == 15
    with pytest.raises(ValueError, match="unknown"):
        PcaModelConfig.from_config({**good, "factor": 3})
    with pytest.raises(ValueError, match="missing"):
        PcaModelConfig.from_config({"factors": 15, "window_days": 252})
    with pytest.raises(ValueError, match="min_observations"):
        PcaModelConfig.from_config({**good, "min_observations": 300})
