"""Phase 1 diagnostics: the date and alignment helpers, and a deterministic report, on synthetic data."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from helpers import FACTOR_CAL, factor_panel
from statarb.factors.build import build_residuals
from statarb.factors.report import (
    daily_rank_correlation,
    diagnostics,
    lead,
    sector_on_date,
    write_report,
)

FACTORS_CFG = {
    "model": {"window_days": 60, "min_observations": 45, "sector_factor": "excess"},
    "sector_etfs": {"Information Technology": "XLK", "Financials": "XLF"},
    "events": {"lookback_days": 20, "volume_ratio": 3.0},
}
REPORT_CFG = {"size_buckets": 2, "autocorrelation_lags": 2, "calm_year": 2020}
STOCKS = ["AAA", "BBB", "CCC", "DDD"]


def test_lead_takes_the_same_ticker_exactly_k_trading_days_later() -> None:
    cal = pd.bdate_range("2021-01-04", periods=6)
    frame = pd.DataFrame(
        {
            "date": [cal[0], cal[1], cal[3], cal[0], cal[2]],
            "ticker": ["AAA", "AAA", "AAA", "BBB", "BBB"],
            "x": [1.0, 2.0, 4.0, 10.0, 30.0],
        }
    )
    one = lead(frame, "x", 1, cal)
    two = lead(frame, "x", 2, cal)
    # AAA has no row on cal[2], so its lead from cal[1] is missing rather than the next row's value.
    np.testing.assert_array_equal(one.to_numpy(), [2.0, np.nan, np.nan, np.nan, np.nan])
    np.testing.assert_array_equal(two.to_numpy(), [np.nan, 4.0, np.nan, 30.0, np.nan])


def test_sector_on_date_reads_the_interval_that_contains_the_date() -> None:
    sectors = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "sector": ["Information Technology", "Financials"],
            "valid_from": pd.to_datetime(["2021-01-01", "2021-03-01"]),
            "valid_to": pd.to_datetime(["2021-03-01", None]),
        }
    )
    rows = pd.DataFrame({"date": pd.to_datetime(["2021-02-26", "2021-03-01", "2020-12-31"]), "ticker": "AAA"})
    assert sector_on_date(rows, sectors).tolist()[:2] == ["Information Technology", "Financials"]
    assert pd.isna(sector_on_date(rows, sectors).iloc[2])     # before the first interval


def test_daily_rank_correlation_is_spearman_within_each_day() -> None:
    rng = np.random.default_rng(5)
    days = np.repeat(pd.bdate_range("2021-01-04", periods=4), 8)
    x, y = pd.Series(rng.normal(size=32)), pd.Series(rng.normal(size=32))
    y.iloc[3] = np.nan
    keys = pd.Series(days)
    got = daily_rank_correlation(x, y, [keys])
    frame = pd.DataFrame({"d": keys, "x": x, "y": y}).dropna()
    want = frame.groupby("d")[["x", "y"]].apply(lambda g: g["x"].rank().corr(g["y"].rank()))
    np.testing.assert_allclose(got.to_numpy(), want.to_numpy(), rtol=0, atol=1e-12)


def _wide_panel(n_stocks: int = 12, seed: int = 6) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """SPY, XLK and enough IT stocks for every daily statistic to have five names."""
    rng = np.random.default_rng(seed)
    n = len(FACTOR_CAL)
    spy = rng.normal(0, 0.01, n)
    xlk = spy + rng.normal(0, 0.006, n)
    stocks = [f"S{i:02d}" for i in range(n_stocks)]
    series = {"SPY": spy, "XLK": xlk}
    for s in stocks:
        series[s] = rng.uniform(0.6, 1.4) * spy + rng.uniform(0.3, 1.2) * (xlk - spy) + rng.normal(0, 0.01, n)
    returns = pd.concat(
        [pd.DataFrame({"date": FACTOR_CAL, "ticker": t, "ret": r, "split_ratio": 1.0}) for t, r in series.items()],
        ignore_index=True,
    )
    prices = returns[["date", "ticker"]].assign(close=100.0, volume=1e6 * np.exp(rng.normal(0, 0.5, len(returns))))
    sectors = pd.DataFrame(
        {"ticker": stocks, "sector": "Information Technology", "valid_from": FACTOR_CAL[0], "valid_to": pd.NaT}
    ).astype({"valid_from": "datetime64[ns]", "valid_to": "datetime64[ns]"})
    return returns, prices, sectors, stocks


def _report():
    returns, prices, sectors, stocks = _wide_panel()
    residuals = build_residuals(returns, sectors, prices, stocks, FACTORS_CFG, "SPY")
    universe = returns.loc[returns["ticker"].isin(stocks), ["date", "ticker"]]
    return diagnostics(residuals, universe, sectors, prices, REPORT_CFG)


def test_report_writes_identical_bytes_with_no_chart_metadata(tmp_path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    write_report(_report(), first)
    write_report(_report(), second)
    names = sorted(p.name for p in first.iterdir())
    assert names == sorted(["diagnostics.md", "betas.png", "pairwise_correlation.png",
                            "autocorrelation_by_year.png", "residual_distribution.png"])
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes()
        if name.endswith(".png"):
            assert b"Software" not in (first / name).read_bytes()
            assert b"tIME" not in (first / name).read_bytes()
    text = (first / "diagnostics.md").read_text()
    assert f"to {FACTOR_CAL[-1].date()}" in text
    assert "## Residuals in March 2020 compared with 2020" in text
    assert "| Information Technology |" in text          # a sector with five names a day has a row
    assert "| year | lag-1 daily rank mean | t | raw returns mean | raw returns t | days |" in text


def test_report_config_rejects_unknown_keys() -> None:
    returns, prices, sectors = factor_panel()
    residuals = build_residuals(returns, sectors, prices, STOCKS, FACTORS_CFG, "SPY")
    with pytest.raises(ValueError, match="report"):
        diagnostics(residuals, returns[["date", "ticker"]], sectors, prices, {**REPORT_CFG, "calm_yr": 2017})
