"""Phase 1: rolling regression, Model A, event flag and look-ahead, on synthetic panels."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from helpers import FACTOR_CAL as CAL
from helpers import factor_panel as _panel
from statarb.config import load_config, repo_root
from statarb.data.schema import GICS_SECTORS
from statarb.factors.build import build_residuals
from statarb.factors.events import volume_ratio
from statarb.factors.model import EtfModelConfig
from statarb.factors.rolling import rolling_ols
from statarb.testing.lookahead import assert_unchanged_through, perturb_after

ETFS = {"Information Technology": "XLK", "Financials": "XLF"}
FACTORS_CFG = {
    "model": {"window_days": 60, "min_observations": 45, "sector_factor": "excess"},
    "sector_etfs": ETFS,
    "events": {"lookback_days": 20, "volume_ratio": 3.0},
}
STOCKS = ["AAA", "BBB", "CCC", "DDD"]


def _residuals(returns: pd.DataFrame, prices: pd.DataFrame, sectors: pd.DataFrame) -> pd.DataFrame:
    return build_residuals(returns, sectors, prices, STOCKS, FACTORS_CFG, "SPY")


def test_rolling_ols_matches_least_squares_on_each_window() -> None:
    rng = np.random.default_rng(1)
    T, N, W = 200, 3, 50
    x = rng.normal(0, 0.01, (T, N))
    y = 0.5 * x + rng.normal(0, 0.01, (T, N))
    y[20:35, 1] = np.nan
    fit = rolling_ols(y, [x], W, 30)
    for t in range(T):
        for i in range(N):
            rows = np.arange(max(t - W, 0), t)
            ok = np.isfinite(y[rows, i])
            assert fit.n_obs[t, i] == ok.sum()
            if ok.sum() < 30:
                assert np.isnan(fit.coef[t, i]).all()
                continue
            X = np.column_stack([np.ones(ok.sum()), x[rows, i][ok]])
            ref = np.linalg.lstsq(X, y[rows, i][ok], rcond=None)[0]
            np.testing.assert_allclose(fit.coef[t, i], ref, rtol=0, atol=1e-12)


def test_coefficients_on_t_ignore_data_from_t_onwards() -> None:
    rng = np.random.default_rng(2)
    x = rng.normal(0, 0.01, (120, 2))
    y = x + rng.normal(0, 0.01, (120, 2))
    base = rolling_ols(y, [x], 40, 30).coef
    for t in (40, 77, 119):
        y2, x2 = y.copy(), x.copy()
        y2[t:] += rng.normal(0, 0.05, y2[t:].shape)
        x2[t:] += rng.normal(0, 0.05, x2[t:].shape)
        changed = rolling_ols(y2, [x2], 40, 30).coef
        np.testing.assert_array_equal(base[: t + 1], changed[: t + 1])


def test_model_recovers_betas_and_uses_the_sector_etf_of_each_day() -> None:
    returns, prices, sectors = _panel()
    res = _residuals(returns, prices, sectors).set_index(["date", "ticker"])
    late = res.xs(CAL[-1], level="date")
    assert late.loc["AAA", "sector_etf"] == "XLK"
    assert late.loc["BBB", "sector_etf"] == "XLF"
    assert late.loc["AAA", "beta_market"] == pytest.approx(0.9, abs=0.15)
    assert late.loc["AAA", "beta_sector"] == pytest.approx(0.8, abs=0.15)
    # BBB's window straddles its sector change: the spliced series keeps the fit.
    assert late.loc["BBB", "beta_sector"] == pytest.approx(1.2, abs=0.15)
    before = res.xs(CAL[129], level="date")
    assert before.loc["BBB", "sector_etf"] == "XLK"
    row = res.loc[(CAL[200], "BBB")]
    by_key = returns.set_index(["date", "ticker"])["ret"]
    xlf, spy = by_key.loc[(CAL[200], "XLF")], by_key.loc[(CAL[200], "SPY")]
    assert row["fitted"] == pytest.approx(row["beta_market"] * spy + row["beta_sector"] * (xlf - spy), abs=1e-15)
    assert row["residual"] == pytest.approx(row["ret"] - row["fitted"], abs=1e-15)


def test_sector_without_an_etf_falls_back_to_the_market() -> None:
    returns, prices, sectors = _panel()
    res = _residuals(returns, prices, sectors)
    ccc = res[res["ticker"] == "CCC"]
    assert ccc["market_only"].all() and ccc["beta_sector"].isna().all() and ccc["sector_etf"].isna().all()
    assert not res.loc[res["ticker"] == "AAA", "market_only"].any()


def test_no_residual_without_enough_history() -> None:
    returns, prices, sectors = _panel()
    res = _residuals(returns, prices, sectors)
    assert res["date"].min() == CAL[45]           # first day with 45 prior returns
    assert (res["n_obs"] >= 45).all()
    ddd = res[res["ticker"] == "DDD"].set_index("date")
    assert CAL[60] not in ddd.index               # in the gap: no return that day


def test_residuals_have_no_look_ahead() -> None:
    returns, prices, sectors = _panel()
    base = _residuals(returns, prices, sectors)
    for cutoff in (CAL[60], CAL[131], CAL[200]):
        noisy_returns = perturb_after(returns, cutoff, ["ret"], seed=3, scale=1.0)
        noisy_prices = perturb_after(prices, cutoff, ["volume"], seed=4, scale=1.0)
        assert_unchanged_through(base, _residuals(noisy_returns, noisy_prices, sectors), cutoff)


def test_split_does_not_register_as_a_volume_spike() -> None:
    days = pd.bdate_range("2021-01-04", periods=30)
    volume = [1e6] * 25 + [4e6] * 5                 # 4:1 split on day 25: share count quadruples
    split = [1.0] * 25 + [4.0] + [1.0] * 4
    prices = pd.DataFrame({"date": days, "ticker": "AAA", "volume": volume})
    returns = pd.DataFrame({"date": days, "ticker": "AAA", "ret": 0.0, "split_ratio": split})
    ratio = volume_ratio(prices, returns, ["AAA"], pd.DatetimeIndex(days), 20)["AAA"]
    assert ratio.iloc[25:].tolist() == [1.0] * 5
    assert ratio.iloc[:20].isna().all()


def test_model_config_rejects_unknown_or_missing_keys() -> None:
    with pytest.raises(ValueError, match="unknown"):
        EtfModelConfig.from_config({**FACTORS_CFG["model"], "windw_days": 10}, ETFS, "SPY")
    with pytest.raises(ValueError, match="missing"):
        EtfModelConfig.from_config({"window_days": 60, "min_observations": 45}, ETFS, "SPY")
    with pytest.raises(ValueError):
        EtfModelConfig.from_config({**FACTORS_CFG["model"], "min_observations": 61}, ETFS, "SPY")
    with pytest.raises(ValueError, match="events"):
        returns, prices, sectors = _panel()
        build_residuals(returns, sectors, prices, STOCKS, {**FACTORS_CFG, "events": {"lookback_days": 20}}, "SPY")


def test_repository_factor_config_is_consistent() -> None:
    root = repo_root()
    factors = load_config("factors", root)
    data = load_config("data", root)
    cfg = EtfModelConfig.from_config(factors["model"], factors["sector_etfs"], data["factors"]["market"])
    assert set(cfg.sector_etfs) == GICS_SECTORS
    assert sorted(cfg.sector_etfs.values()) == sorted(data["factors"]["sectors"])
