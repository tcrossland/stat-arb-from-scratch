"""Phase 2 signals: the reversal signal and the s-score's estimation. The look-ahead contract is in tests/contract/."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from statarb.signals.reversal import reversal_signal
from statarb.signals.sscore import fit_sscores


def test_reversal_is_minus_the_sum_over_n_days_and_needs_every_day() -> None:
    series = pd.DataFrame({"A": [0.01, -0.02, 0.03, np.nan, 0.01, 0.02], "B": [0.0, 0.01, 0.01, 0.01, -0.01, 0.0]})
    out = reversal_signal(series, 2)
    np.testing.assert_allclose(out["B"].iloc[1:], [-0.01, -0.02, -0.02, 0.0, 0.01])
    assert out["A"].iloc[3:5].isna().all()                  # a window over the missing day has no signal
    assert out["A"].iloc[5] == pytest.approx(-0.03)
    scaled = reversal_signal(series, 2, vol_scaled=True, vol_window=3, vol_min_observations=3)
    vol = series["B"].iloc[2:5].std()
    assert scaled["B"].iloc[4] == pytest.approx(-0.0 / (vol * np.sqrt(2)), abs=1e-15)
    assert scaled["B"].iloc[5] == pytest.approx(0.01 / (series["B"].iloc[3:6].std() * np.sqrt(2)))


def test_sscore_matches_the_papers_appendix_on_one_day() -> None:
    rng = np.random.default_rng(3)
    T, W = 80, 60
    market = rng.normal(0, 0.01, T)
    sector = rng.normal(0, 0.005, (T, 1))
    x = np.zeros(T)
    for t in range(1, T):
        x[t] = 0.8 * x[t - 1] + rng.normal(0, 0.01)
    y = (1.1 * market + 0.7 * sector[:, 0] + np.diff(np.concatenate([[0.0], x])))[:, None]
    fit = fit_sscores(y, market, sector, np.ones((T, 1), dtype=bool), W, 30, centre_means=False)

    t = T - 1
    rows = slice(t - W + 1, t + 1)
    X = np.column_stack([np.ones(W), market[rows], sector[rows, 0]])
    coef, *_ = np.linalg.lstsq(X, y[rows, 0], rcond=None)
    cum = np.cumsum(y[rows, 0] - X @ coef)
    assert cum[-1] == pytest.approx(0.0, abs=1e-12)          # X_60 = 0 with an intercept
    b, a = np.polyfit(cum[:-1], cum[1:], 1)
    noise = cum[1:] - a - b * cum[:-1]
    m, sigma_eq = a / (1 - b), np.sqrt(noise.var() / (1 - b**2))
    assert fit.s[t, 0] == pytest.approx((cum[-1] - m) / sigma_eq, rel=1e-9)
    assert fit.beta_market[t, 0] == pytest.approx(coef[1], rel=1e-9)
    assert fit.reversion_days[t, 0] == pytest.approx(-1 / np.log(b), rel=1e-9)
    assert fit.tradeable[t, 0] == (-1 / np.log(b) < 30)
    assert np.isnan(fit.s[: W - 1]).all()


def test_sscore_centring_removes_the_cross_sectional_mean_of_m() -> None:
    rng = np.random.default_rng(4)
    T, N, W = 70, 6, 60
    market = rng.normal(0, 0.01, T)
    sector = rng.normal(0, 0.005, (T, N))
    y = market[:, None] + rng.normal(0, 0.01, (T, N))
    members = np.ones((T, N), dtype=bool)
    plain = fit_sscores(y, market, sector, members, W, 30, centre_means=False)
    centred = fit_sscores(y, market, sector, members, W, 30, centre_means=True)
    t = T - 1
    ok = np.isfinite(plain.s[t])
    assert ok.sum() >= 3
    # Without centring s_i = -m_i / sigma_i (X_window = 0). Centring subtracts the mean of m,
    # so shift_i = s_centred_i - s_i = mean(m) / sigma_i, and then mean(-s_i / shift_i) = 1.
    s, shift = plain.s[t, ok], (centred.s[t] - plain.s[t])[ok]
    assert np.mean(-s / shift) == pytest.approx(1.0, rel=1e-6)


def test_sscore_fits_and_centres_only_stocks_known_on_the_day() -> None:
    rng = np.random.default_rng(5)
    T, N, W = 70, 6, 60
    market = rng.normal(0, 0.01, T)
    sector = rng.normal(0, 0.005, (T, N))
    y = market[:, None] + rng.normal(0, 0.01, (T, N))
    members = np.ones((T, N), dtype=bool)
    known = np.ones((T, N), dtype=bool)
    known[: T - 1, 0] = False                                # stock 0 is first known on the last day
    everyone = fit_sscores(y, market, sector, members, W, 30, centre_means=True)
    counted = fit_sscores(y, market, sector, members, W, 30, centre_means=True, known=known)
    assert np.isnan(counted.s[: T - 1, 0]).all() and not counted.tradeable[: T - 1, 0].any()
    # Before the last day the centre leaves stock 0 out, so the others' scores move.
    t = T - 2
    others = np.isfinite(everyone.s[t, 1:])
    assert others.any() and not np.allclose(everyone.s[t, 1:][others], counted.s[t, 1:][others])
    np.testing.assert_array_equal(everyone.s[T - 1], counted.s[T - 1])   # all known: the same fit
