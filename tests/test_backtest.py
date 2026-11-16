"""Phase 2: engine, portfolio rules, s-score, placebo, reproducibility, look-ahead, config, log and trials."""

from __future__ import annotations

import dataclasses
import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_CAL, MARKET_ETFS, synthetic_market
from statarb.backtest import experiments, report
from statarb.backtest.config import BacktestConfig
from statarb.backtest.costs import FlatCost
from statarb.backtest.engine import (
    TRADING_DAYS,
    Grid,
    daily_returns,
    open_to_open_returns,
    run,
)
from statarb.backtest.metrics import (
    break_even_bps,
    deflated_sharpe,
    expected_max_sharpe,
)
from statarb.backtest.rules import (
    DecileRule,
    ThresholdRule,
    decile_portfolio,
    hedged_targets,
    holding_slices,
    threshold_positions,
)
from statarb.backtest.run import evaluate, placebo, run_sweep, shuffle_within_days
from statarb.backtest.sweep import (
    SSCORE_VARIANT,
    build_grids,
    daily,
    fill,
    headline_variant,
    record,
    signal_of,
    targets,
)
from statarb.backtest.trials import path_id, repository_trials, trial_sharpes
from statarb.config import load_config
from statarb.signals.base import Hedge, Scores
from statarb.signals.tables import build_tables
from statarb.testing.lookahead import perturb_after

# Hand-built example ----------------------------------------------------------

DAYS = pd.bdate_range("2024-01-01", periods=5)


def _toy_grid() -> Grid:
    # Close-to-close returns ending on each day, for A, B, C.
    returns = np.array(
        [
            [np.nan, np.nan, np.nan],
            [0.01, -0.01, 0.00],
            [-0.02, 0.01, 0.00],
            [0.03, -0.01, 0.01],
            [0.00, 0.02, -0.01],
        ]
    )
    return Grid("close", DAYS, ("A", "B", "C"), returns, np.ones((5, 3), dtype=bool))


def test_hand_built_three_stock_five_day_example() -> None:
    # Signals: long the highest, short the lowest; one name per leg.
    signal = np.array([[3, 1, 2], [3, 1, 2], [1, 2, 3], [1, 2, 3], [np.nan] * 3], dtype=float)
    book = decile_portfolio(signal, np.ones((5, 3), dtype=bool), 0.34)
    np.testing.assert_array_equal(book[0], [0.5, -0.5, 0.0])
    np.testing.assert_array_equal(book[2], [-0.5, 0.0, 0.5])
    np.testing.assert_array_equal(book[4], [0.0, 0.0, 0.0])
    book[4] = np.nan                                     # no decision on the last day: hold

    result = run(book, _toy_grid(), delay=0, borrow_annual=0.252)    # 10 bps a day on shorts
    d = daily_returns(result, FlatCost(10.0))

    # By hand. Day 0: buy A 0.5, sell B 0.5. Day 1: P&L 0.5(0.01) - 0.5(-0.01) = 0.01;
    # drifted A 0.505, B -0.495, rebalanced back: traded 0.01. Day 2: P&L -0.01 - 0.005;
    # drifted A 0.49, B -0.505; to A -0.5, C 0.5: traded 0.99 + 0.505 + 0.5. Day 3: P&L
    # 0.005 - 0.015; drifted C 0.505, A -0.515; traded 0.02. Day 4: P&L -0.005, no trade.
    np.testing.assert_allclose(d["gross"], [0.0, 0.01, -0.015, -0.01, -0.005], rtol=0, atol=1e-15)
    np.testing.assert_allclose(d["turnover"], [1.0, 0.01, 1.995, 0.02, 0.0], rtol=0, atol=1e-15)
    np.testing.assert_allclose(d["cost"], [0.001, 0.00001, 0.001995, 0.00002, 0.0], rtol=0, atol=1e-15)
    np.testing.assert_allclose(d["borrow"], [0.0, 0.0005, 0.0005, 0.0005, 0.0005], rtol=0, atol=1e-15)
    np.testing.assert_allclose(d["long_pnl"], [0.0, 0.005, -0.01, 0.005, -0.005], rtol=0, atol=1e-15)
    np.testing.assert_allclose(d["short_pnl"], [0.0, 0.005, -0.005, -0.015, 0.0], rtol=0, atol=1e-15)
    np.testing.assert_allclose(result.holdings[4], [-0.5, 0.0, 0.495], rtol=0, atol=1e-15)
    assert d["net"].sum() == pytest.approx(-0.02 - 0.003025 - 0.002, abs=1e-15)


def test_delay_untradable_names_and_missing_returns() -> None:
    grid = _toy_grid()
    book = np.full((5, 3), np.nan)
    book[0] = [0.5, -0.5, 0.0]
    result = run(book, grid, delay=1, borrow_annual=0.0)
    assert (result.holdings[0] == 0).all()               # decided at day 0, filled at day 1
    np.testing.assert_array_equal(result.holdings[1], [0.5, -0.5, 0.0])
    assert result.pnl[1].sum() == 0.0 and result.pnl[2].sum() == pytest.approx(-0.015)

    blocked = dataclasses.replace(grid, tradable=np.array([[True, False, True]] * 5))
    result = run(book, blocked, delay=0, borrow_annual=0.0)
    np.testing.assert_array_equal(result.holdings[0], [0.5, 0.0, 0.0])   # B has no price to trade at

    gap = grid.returns.copy()
    gap[2, 0] = np.nan                                   # A held with no return on day 2
    result = run(book, dataclasses.replace(grid, returns=gap), delay=0, borrow_annual=0.0)
    assert result.missing_returns == 1 and result.pnl[2, 0] == 0.0


def test_open_to_open_returns_carry_splits_and_dividends() -> None:
    d = pd.bdate_range("2024-01-01", periods=3)
    prices = pd.DataFrame({"date": d, "ticker": "A", "open": [100.0, 102.0, 51.0]})
    returns = pd.DataFrame({"date": d[1:], "ticker": "A", "split_ratio": [1.0, 2.0], "cash": [1.0, 0.0]})
    out = open_to_open_returns(prices, returns)
    # Dividend of 1 going ex on day 1; 2-for-1 split going ex on day 2.
    np.testing.assert_allclose(out["ret"], [103.0 / 100.0 - 1, 2 * 51.0 / 102.0 - 1])


def test_holding_slices_average_the_last_k_portfolios() -> None:
    rng = np.random.default_rng(0)
    book = rng.normal(size=(6, 4))
    held = holding_slices(book, 2)
    np.testing.assert_allclose(held[0], book[0] / 2)
    for t in range(1, 6):
        np.testing.assert_allclose(held[t], (book[t] + book[t - 1]) / 2, rtol=0, atol=1e-15)
    np.testing.assert_array_equal(holding_slices(book, 1), book)


def test_decile_rule_is_flat_before_the_start_and_pads_hedges() -> None:
    signal = np.array([[3, 1, 2]] * 4, dtype=float)
    out = DecileRule(0.34, 2).targets(Scores(signal), np.ones((4, 3), dtype=bool), 1, 2)
    assert out.shape == (4, 5) and np.isnan(out[0]).all()
    np.testing.assert_array_equal(out[1], [0.25, -0.25, 0.0, 0.0, 0.0])    # one of two slices held
    np.testing.assert_array_equal(out[2], [0.5, -0.5, 0.0, 0.0, 0.0])


def test_break_even_cost_zeroes_mean_net_return() -> None:
    signal = np.array([[3, 1, 2], [3, 1, 2], [1, 2, 3], [1, 2, 3], [2, 3, 1]], dtype=float)
    book = decile_portfolio(signal, np.ones((5, 3), dtype=bool), 0.34)
    result = run(book, _toy_grid(), delay=0, borrow_annual=0.01)
    be = break_even_bps(daily_returns(result, FlatCost(0.0)))
    assert daily_returns(result, FlatCost(be))["net"].mean() == pytest.approx(0.0, abs=1e-15)


def test_expected_maximum_and_deflated_sharpe() -> None:
    assert expected_max_sharpe(1, 0.01) == 0.0
    assert expected_max_sharpe(100, 0.01) > expected_max_sharpe(10, 0.01) > 0
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0.001, 0.01, 2000))
    one = deflated_sharpe(r, 2, np.array([0.0, 0.001]))
    many = deflated_sharpe(r, 200, rng.normal(0, 0.05, 200))
    assert one["deflated_sharpe_probability"] > many["deflated_sharpe_probability"]
    assert one["sharpe"] == pytest.approx(r.mean() / r.std() * math.sqrt(TRADING_DAYS))


# Synthetic market ------------------------------------------------------------


def _config(**overrides) -> BacktestConfig:
    raw = load_config("backtest")
    raw["period"]["start"] = MARKET_CAL[40].date()
    raw["run"]["placebo_runs"] = 2
    raw["sscore"]["window_days"] = 30
    raw["signals"] = [{"name": n, "lookbacks": [1], "vol_scaled": [False]} for n in ("residual", "raw")]
    raw["headline"] = {"signal": "residual", "lookback_days": 1, "vol_scaled": False, "holding_days": 1}
    raw["sweep"]["holding_days"] = [1, 2]
    for key, value in overrides.items():
        raw[key] = {**raw[key], **value}
    return BacktestConfig.from_dict(raw)


def _tables(long=None):
    return build_tables(*(long or synthetic_market()), "SPY", MARKET_ETFS)


def _paths(tables, cfg, variant, timing, level=0.0):
    book = targets(variant, signal_of(variant, cfg, MARKET_ETFS).scores(tables), tables, cfg)
    return book, daily(fill(book, build_grids(tables), timing, cfg), cfg, timing, level)


def test_reversal_earns_and_a_shuffled_signal_does_not() -> None:
    tables, cfg = _tables(), _config()
    head = headline_variant(cfg)
    real = _paths(tables, cfg, head, "close_t")[1]["gross"]
    assert real.mean() / real.std() * np.sqrt(len(real)) > 5

    signal = signal_of(head, cfg, MARKET_ETFS).scores(tables).score
    rule, grids = DecileRule(cfg.portfolio.decile, 1), build_grids(tables)
    means = []
    for seed in range(200):
        shuffled = Scores(shuffle_within_days(signal, tables.members, np.random.default_rng(seed)))
        book = rule.targets(shuffled, tables.members, 40, len(tables.hedges))
        means.append(daily(fill(book, grids, "close_t", cfg), cfg, "close_t", 0.0)["gross"].mean())
    means = np.array(means)
    t = means.mean() / (means.std(ddof=1) / np.sqrt(len(means)))
    assert abs(t) < 3
    assert abs(means.mean()) < 0.1 * real.mean()


def test_backtest_reproduces_exactly_from_config_and_seed() -> None:
    def once():
        tables, cfg = _tables(synthetic_market(seed=5)), _config()
        grids = build_grids(tables)
        outcomes = run_sweep(tables, cfg, grids, MARKET_ETFS)
        return outcomes, placebo(tables, cfg, grids, MARKET_ETFS)

    (a, pa), (b, pb) = once(), once()
    assert [(o.variant, o.fill) for o in a] == [(o.variant, o.fill) for o in b]
    for x, y in zip(a, b, strict=True):
        assert x.metrics == y.metrics
        for level in x.daily:
            pd.testing.assert_frame_equal(x.daily[level], y.daily[level], check_exact=True)
    pd.testing.assert_frame_equal(pa, pb, check_exact=True)


def test_report_and_charts_are_identical_on_a_rerun(tmp_path) -> None:
    tables, cfg = _tables(), _config()
    grids = build_grids(tables)
    outcomes = run_sweep(tables, cfg, grids, MARKET_ETFS)
    shuffled = placebo(tables, cfg, grids, MARKET_ETFS)
    for name in ("a", "b"):
        report.write_report(tables, cfg, outcomes, shuffled, tmp_path / name, tmp_path / name / "phase-02")
    files = sorted(p.name for p in (tmp_path / "a" / "phase-02").iterdir())
    assert files == ["backtest.md", "headline_pnl.png", "rolling_sharpe.png"]
    for f in files:
        assert (tmp_path / "a" / "phase-02" / f).read_bytes() == (tmp_path / "b" / "phase-02" / f).read_bytes()
    for f in files[1:]:
        data = (tmp_path / "a" / "phase-02" / f).read_bytes()
        assert b"Software" not in data and b"Creation Time" not in data
    text = (tmp_path / "a" / "phase-02" / "backtest.md").read_text()
    for section in ("## By year", "## By sector", "## By size", "## Placebo", "## Configurations tried"):
        assert section in text


def test_targets_and_pnl_have_no_look_ahead() -> None:
    long = synthetic_market(seed=7)
    cfg = _config()
    base = _tables(long)
    for cutoff in (MARKET_CAL[80], MARKET_CAL[200]):
        returns, prices, residuals, universe, sectors = long
        noisy = _tables(
            (
                perturb_after(returns, cutoff, ["ret"], seed=1, scale=1.0),
                perturb_after(prices, cutoff, ["open", "close"], seed=2, scale=1.0),
                perturb_after(residuals, cutoff, ["residual", "beta_market"], seed=3, scale=1.0),
                universe,
                sectors,
            )
        )
        upto = int(base.dates.searchsorted(cutoff, side="right"))
        for variant in (headline_variant(cfg), SSCORE_VARIANT):
            for timing in cfg.fills.timings:
                ta, da = _paths(base, cfg, variant, timing, 5.0)
                tb, db = _paths(noisy, cfg, variant, timing, 5.0)
                np.testing.assert_array_equal(ta[:upto], tb[:upto])
                pd.testing.assert_frame_equal(da.loc[:cutoff], db.loc[:cutoff], check_exact=True)


def test_evaluate_reports_every_cost_level_and_break_even() -> None:
    tables, cfg = _tables(), _config()
    head = headline_variant(cfg)
    book, _ = _paths(tables, cfg, head, "open_t1")
    o = evaluate(cfg, head, "open_t1", fill(book, build_grids(tables), "open_t1", cfg), keep_result=False)
    assert list(o.metrics) == list(cfg.costs.levels_bps) and o.result is None
    sharpes = [o.metrics[level]["sharpe"] for level in cfg.costs.levels_bps]
    assert sharpes == sorted(sharpes, reverse=True)
    assert len({o.metrics[level]["break_even_bps"] for level in cfg.costs.levels_bps}) == 1


# s-score -----------------------------------------------------------------------


def test_threshold_rule_opens_holds_and_closes() -> None:
    s = np.array([0.0, -1.3, -0.8, -0.4, 1.3, 0.9, 0.7, 1.3, np.nan, -1.3])[:, None]   # NaN: too slow, force close
    pos = threshold_positions(s, np.ones_like(s, dtype=bool), 0, 1.25, 0.50, 0.75)
    assert pos[:, 0].tolist() == [0, 1, 1, 0, -1, -1, 0, -1, 0, 1]


def test_hedged_targets_hold_stocks_and_hedge_with_entry_betas() -> None:
    T = 4
    positions = np.array([[0], [1], [1], [0]], dtype=np.int8)
    hedge = Hedge(np.array([[1.0], [1.2], [9.0], [9.0]]), np.array([[0.5], [0.4], [9.0], [9.0]]), np.zeros((T, 1), dtype=np.int64))
    stock, h = hedged_targets(positions, hedge, 2, 0, 0.01)      # hedge columns: [XLK, SPY]
    assert np.isnan(stock[0, 0]) and stock[1, 0] == 0.01 and np.isnan(stock[2, 0]) and stock[3, 0] == 0.0
    np.testing.assert_allclose(h[1], [-0.01 * 0.4, -0.01 * (1.2 - 0.4)])
    np.testing.assert_allclose(h[2], h[1])                       # entry betas, not the day's
    np.testing.assert_allclose(h[3], [0.0, 0.0])


def test_threshold_rule_needs_hedge_ratios() -> None:
    with pytest.raises(ValueError, match="hedge"):
        ThresholdRule(1.25, 0.5, 0.75, 0.01).targets(Scores(np.zeros((3, 2))), np.ones((3, 2), dtype=bool), 0, 2)


# Config, log and trials ---------------------------------------------------------


def test_config_rejects_unknown_or_missing_keys_and_unregistered_signals() -> None:
    raw = load_config("backtest")
    BacktestConfig.from_dict(raw)
    bad = {**raw, "costs": {**raw["costs"], "levels_bp": [1]}}
    with pytest.raises(ValueError, match="unknown"):
        BacktestConfig.from_dict(bad)
    missing = {**raw, "sscore": {k: v for k, v in raw["sscore"].items() if k != "open"}}
    with pytest.raises(ValueError, match="missing"):
        BacktestConfig.from_dict(missing)
    with pytest.raises(ValueError):
        BacktestConfig.from_dict({**raw, "fills": {**raw["fills"], "headline": "open_t2"}})
    with pytest.raises(ValueError, match="decile signal"):
        BacktestConfig.from_dict({**raw, "signals": [*raw["signals"], {"name": "momentum", "lookbacks": [1], "vol_scaled": [False]}]})


def test_log_records_reproduce_the_configuration_layout() -> None:
    cfg = load_config("backtest")
    cfg = BacktestConfig.from_dict(cfg)
    head = headline_variant(cfg)
    rec = record(head, "close_t", 0, cfg)
    assert rec == {
        "signal": "residual", "source": "residual", "lookback_days": 1, "vol_scaled": False, "holding_days": 1,
        "fill": "close_t", "cost_bps": 0, "slippage_bps": 5, "borrow_annual": 0.005, "decile": 0.1, "start": "2017-01-03",
    }
    s = record(SSCORE_VARIANT, "open_t1", 5, cfg)
    assert s["decile"] is None and s["slippage_bps"] == 0.0 and set(s["sscore"]) == {
        "window_days", "max_reversion_days", "open", "close_long", "close_short", "centre_means", "position_weight",
    }


def test_experiment_entries_identify_repeated_configurations(tmp_path) -> None:
    now = dt.datetime(2026, 11, 14, 12, 0, tzinfo=dt.UTC)
    config = {"signal": "residual", "cost_bps": 5.0}
    state = {"git_commit": "abc", "git_dirty": False, "config_overlay": None, "price_source": "alpaca", "price_snapshot": "2026-11-16"}
    e1 = experiments.entry(config, {"sharpe": float("nan")}, 0, state, now)
    e2 = experiments.entry(dict(reversed(list(config.items()))), {"sharpe": 1.0}, 0, state, now)
    assert e1["config_id"] == e2["config_id"] and e1["metrics"]["sharpe"] is None
    assert e1["recorded_at"] == "2026-11-14T12:00:00+00:00" and e1["price_snapshot"] == "2026-11-16"
    path = tmp_path / "experiments.jsonl"
    experiments.append(path, [e1])
    experiments.append(path, [e2])
    assert [e["metrics"]["sharpe"] for e in experiments.read(path)] == [None, 1.0]


def test_trials_are_distinct_paths_across_every_phase_log(tmp_path) -> None:
    now = dt.datetime(2026, 11, 16, tzinfo=dt.UTC)
    state = {"git_commit": None, "git_dirty": None}

    def entry(signal: str, cost: float, gross: float) -> dict:
        return experiments.entry({"signal": signal, "cost_bps": cost}, {"gross_sharpe": gross}, 0, state, now)

    a = [entry("residual", c, 0.5) for c in (0, 5)]               # one path at two cost levels
    b = [entry("raw", 0, 0.3), entry("residual", 0, 0.7)]         # a new path, and a rerun of the first
    experiments.append(tmp_path / "phase-02" / "experiments.jsonl", a)
    experiments.append(tmp_path / "phase-03" / "experiments.jsonl", b)
    (tmp_path / "phase-01").mkdir()
    trials = repository_trials(tmp_path)
    assert len(trials) == 2
    assert trials[path_id({"signal": "residual", "cost_bps": 99})] == pytest.approx(0.7 / math.sqrt(TRADING_DAYS))
    assert trial_sharpes([]) == {}
