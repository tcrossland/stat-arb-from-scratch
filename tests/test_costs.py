"""Phase 3: cost components, spread pooling, calibration, the no-trade zone and look-ahead."""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_CAL, MARKET_ETFS, synthetic_market
from statarb.backtest import cost_report, experiments
from statarb.backtest.config import BacktestConfig, CostConfig
from statarb.backtest.cost_run import (
    Lab,
    alternatives,
    build_lab,
    cost,
    expected_move_of,
    headline,
    log_entries,
    no_trade,
    per_capital,
    record,
    run_all,
    run_path,
    scores_of,
    trial_sets,
    variants,
    verdicts,
)
from statarb.backtest.costs import (
    HALF_TICK,
    CommissionSchedule,
    CostInputs,
    FlatCost,
    NoTradeZone,
    TradingCost,
    before,
    borrow_rates,
    half_spread,
    pooled_spread,
    size_groups,
    split_consistent,
)
from statarb.backtest.engine import Grid, daily_returns, run
from statarb.backtest.sweep import Variant, targets
from statarb.backtest.trials import path_id
from statarb.config import load_config
from statarb.signals.calibration import calibration_slope, expected_move, forward_sum
from statarb.signals.tables import build_tables
from statarb.testing.lookahead import perturb_after

FIXED = CommissionSchedule("fixed", per_share=0.005, min_per_order=1.0, max_fraction=0.01)


# Commission, spread, impact ----------------------------------------------------


def test_commission_applies_per_share_rate_minimum_and_maximum() -> None:
    dollars = np.array([0.0, 50.0, 1_000.0, 100_000.0])
    price = np.array([100.0, 100.0, 100.0, 100.0])
    # Nothing traded: nothing. $50: the $1 minimum is above 1% of $50 ($0.50), so the maximum wins.
    # $1,000 = 10 shares: $0.05, raised to the $1 minimum. $100,000 = 1,000 shares: $5.
    np.testing.assert_allclose(FIXED(dollars, price), [0.0, 0.5, 1.0, 5.0])


def _cost(book: float = 10_000.0, T: int = 2, N: int = 2) -> TradingCost:
    return TradingCost(
        half_spread=np.full((T, N), 2e-4),
        volatility=np.full((T, N), 0.02),
        dollar_volume=np.full((T, N), 1e6),
        fill_price=np.full((T, N), 50.0),
        book_size=book,
        impact_coefficient=0.5,
        commission=FIXED,
    )


def test_cost_components_by_hand() -> None:
    trades = np.array([[0.1, -0.4], [0.0, 0.0]])          # fractions of $10,000 capital
    parts = _cost().components(trades, np.array([1.0, 1.0]))
    # $1,000 and $4,000 traded at $50: 20 and 80 shares.
    spread = 2e-4 * 5_000
    impact = 0.5 * 0.02 * (np.sqrt(1_000 / 1e6) * 1_000 + np.sqrt(4_000 / 1e6) * 4_000)
    commission = 1.0 + 1.0                                 # $0.10 and $0.40, both raised to the $1 minimum
    assert parts["spread"][0] == pytest.approx(spread / 10_000)
    assert parts["impact"][0] == pytest.approx(impact / 10_000)
    assert parts["commission"][0] == pytest.approx(commission / 10_000)
    assert all(p[1] == 0.0 for p in parts.values())
    unit = _cost().unit_cost(0, np.array([1_000.0, 4_000.0]), np.array([50.0, 50.0]))
    np.testing.assert_allclose(unit, 2e-4 + 0.5 * 0.02 * np.sqrt(np.array([1e-3, 4e-3])) + np.array([1e-3, 2.5e-4]))


def test_cost_inputs_on_a_grid_time_come_from_the_day_before() -> None:
    close = np.array([[10.0, 200.0], [20.0, 400.0], [40.0, 800.0]])
    inputs = CostInputs(
        dates=pd.bdate_range("2024-01-01", periods=3),
        tickers=("A", "B"),
        name_spread={},
        spread={"edge": np.array([[0.002, 0.0], [0.004, 0.0], [0.006, 0.0]])},
        groups=np.zeros((3, 2), dtype=np.int64),
        volatility=np.zeros((3, 2)),
        dollar_volume=np.zeros((3, 2)),
        open=close,
        close=close,
    )
    assert np.isnan(before(close)[0]).all() and (before(close)[1:] == close[:-1]).all()
    np.testing.assert_allclose(half_spread(inputs, "edge", half_tick_floor=False)[1:, 0], [0.001, 0.002])
    floored = half_spread(inputs, 1.0, half_tick_floor=True)
    # Half a cent over the previous close: 5 bps at $10 and 0.25 bps at $200, where the 1 bp assumption wins.
    np.testing.assert_allclose(floored[1], [HALF_TICK / 10.0, 1e-4])
    np.testing.assert_allclose(floored[2], [HALF_TICK / 20.0, 1e-4])


def test_flat_cost_is_unchanged() -> None:
    parts = FlatCost(10.0).components(np.array([[0.5, -0.5], [0.1, 0.0]]), np.ones(2))
    np.testing.assert_allclose(parts["flat"], [1e-3 * 1.0, 1e-3 * 0.1])


def test_split_consistent_prices_have_no_jump_at_a_split() -> None:
    prices = np.array([[100.0], [102.0], [51.5], [52.0]])
    split = np.array([[1.0], [1.0], [2.0], [1.0]])           # 2-for-1 going ex on day 2
    np.testing.assert_allclose(split_consistent(prices, split)[:, 0], [100.0, 102.0, 103.0, 104.0])


def test_borrow_rates_flag_the_most_volatile_stocks_only() -> None:
    vol = np.array([[0.01, 0.02, 0.03, 0.04, 0.50], [np.nan] * 5])
    is_stock = np.array([True, True, True, True, False])      # the last column is an ETF
    rates, hard = borrow_rates(vol, is_stock, 0.005, 0.05, 0.25)
    assert hard[0].tolist() == [False, False, False, True, False]
    np.testing.assert_allclose(rates[0], [0.005, 0.005, 0.005, 0.05, 0.005])
    assert not hard[1].any()


def test_engine_borrow_panel_matches_a_flat_rate() -> None:
    grid = Grid("close", pd.bdate_range("2024-01-01", periods=3), ("A", "B"), np.array([[np.nan] * 2, [0.01, -0.01], [0.0, 0.0]]), np.ones((3, 2), dtype=bool))
    book = np.array([[0.5, -0.5], [0.5, -0.5], [np.nan, np.nan]])
    flat = run(book, grid, 0, 0.0252)
    panel = run(book, grid, 0, np.full((3, 2), 0.0252))
    np.testing.assert_array_equal(flat.borrow, panel.borrow)
    assert flat.borrow[1] == pytest.approx(0.5 * 0.0252 / 252)


# Spread pooling -----------------------------------------------------------------


def test_pooling_averages_signed_squares_within_groups() -> None:
    signed = np.array([[0.003, -0.001, 0.004, np.nan]])
    out = pooled_spread(signed, np.array([[0, 0, 1, -1]]))
    np.testing.assert_allclose(out[0, :2], np.sqrt((0.003**2 - 0.001**2) / 2))
    assert out[0, 2] == pytest.approx(0.004) and np.isnan(out[0, 3])
    g = size_groups(np.array([[1.0, 2.0, 3.0, 4.0, 9.0]]), np.array([True, True, True, True, False]), 2)
    assert g[0].tolist() == [0, 0, 1, 1, 2]


# Calibration ---------------------------------------------------------------------


def test_forward_sum_and_calibration_use_only_known_outcomes() -> None:
    series = np.arange(1.0, 7.0)[:, None]
    np.testing.assert_allclose(forward_sum(series, 2)[:, 0], [5, 7, 9, 11, np.nan, np.nan])

    rng = np.random.default_rng(0)
    T, N, h = 120, 20, 3
    signal = rng.normal(size=(T, N))
    outcome = 0.5 * signal + rng.normal(size=(T, N))
    members = np.ones((T, N), dtype=bool)
    slope = calibration_slope(signal, outcome, members, h, window=60, min_days=20)
    # On day t only signals up to t-h have a known outcome: changing later outcomes changes nothing.
    t = 80
    changed = outcome.copy()
    changed[t - h + 1 :] = rng.normal(size=(T - t + h - 1, N))
    assert calibration_slope(signal, changed, members, h, 60, 20)[t] == slope[t]
    assert slope[t] == pytest.approx(0.5, abs=0.1)
    move = expected_move(signal, members, slope)
    np.testing.assert_allclose(move[t].sum(), 0.0, atol=1e-12)    # demeaned across members


# No-trade zone -------------------------------------------------------------------


def test_no_trade_zone_opens_resizes_and_exits_as_stated() -> None:
    # Unit cost of a $1,000 trade: 2 bps + 0.5 x 2% x sqrt(0.001) (3.2 bps) + $1 / $1,000 (10 bps) = 15.2 bps.
    move = np.array([[0.0040, 0.0020, 0.0010, 0.0, -0.002, 0.0]])
    zone = NoTradeZone(np.tile(move, (2, 1)), _cost(10_000.0, N=6), decision_price=np.full((2, 6), 50.0), delay=1)
    drifted = np.array([0.0, 0.0, 0.2, 0.2, 0.1, -0.1])
    target = np.array([0.1, 0.1, 0.3, 0.0, -0.1, -0.2])
    out = zone(1, drifted, target)
    # Opening: 40 bps clears the 30.4 bps round trip; 20 bps does not.
    assert out[0] == 0.1 and np.isnan(out[1])
    # A resize up by $1,000 on a 10 bps move against 15.2 bps: skipped. An exit and a change of side: traded.
    assert np.isnan(out[2]) and out[3] == 0.0 and out[4] == -0.1
    # A resize of a short by -$1,000 with no expected move: skipped.
    assert np.isnan(out[5])
    assert zone(0, drifted, target) is target                       # nothing decided yet before the delay


def test_no_trade_zone_cuts_on_a_negative_move_but_not_a_zero_one() -> None:
    drifted = np.array([0.0, 0.2, 0.3, 0.3])
    target = np.array([0.1, 0.3, 0.2, 0.0])          # open, grow, cut by $1,000 (15.2 bps one way), exit
    for move, cuts in ((-0.0040, True), (0.0, False)):
        zone = NoTradeZone(np.full((2, 4), move), _cost(10_000.0, N=4), decision_price=np.full((2, 4), 50.0), delay=1)
        out = zone(1, drifted, target)
        assert np.isnan(out[0]) and np.isnan(out[1])
        assert (out[2] == 0.2) if cuts else np.isnan(out[2])
        assert out[3] == 0.0


def test_engine_without_a_policy_is_phase_2s() -> None:
    grid = Grid("close", pd.bdate_range("2024-01-01", periods=3), ("A", "B"), np.array([[np.nan] * 2, [0.01, -0.01], [0.02, 0.0]]), np.ones((3, 2), dtype=bool))
    book = np.array([[0.5, -0.5], [0.4, -0.4], [0.5, -0.5]])
    a, b = run(book, grid, 1, 0.005), run(book, grid, 1, 0.005, lambda s, drifted, target: target)
    np.testing.assert_array_equal(a.holdings, b.holdings)
    np.testing.assert_array_equal(a.pnl, b.pnl)


# Phase 3 runs on the synthetic market ----------------------------------------------


def _config() -> BacktestConfig:
    raw = load_config("backtest")
    raw["period"]["start"] = MARKET_CAL[60].date()
    raw["sscore"]["window_days"] = 30
    raw["signals"] = [{"name": n, "lookbacks": [1], "vol_scaled": [False]} for n in ("residual", "raw")]
    raw["headline"] = {"signal": "residual", "lookback_days": 1, "vol_scaled": False, "holding_days": 1}
    raw["sweep"]["holding_days"] = [1, 2]
    return BacktestConfig.from_dict(raw)


def _cost_config(cfg: BacktestConfig, books=(100_000,)) -> CostConfig:
    raw = load_config("costs")
    raw["variants"] = [{"name": "baseline", "signal": "residual", "lookback_days": 1, "vol_scaled": False, "holding_days": 2}]
    raw["run"] = {"fill": "open_t1", "book_sizes": list(books), "headline_book": books[0]}
    raw["spread"] = {**raw["spread"], "window_days": 40, "min_observations": 30}
    raw["impact"] = {**raw["impact"], "volatility_window_days": 20, "volatility_min_observations": 15, "volume_window_days": 10, "volume_min_observations": 8}
    raw["no_trade"] = {"calibration_window_days": 60, "calibration_min_days": 20}
    return CostConfig.from_dict(raw, cfg)


def _lab(long=None, books=(100_000,)) -> Lab:
    tables = build_tables(*(long or synthetic_market()), "SPY", MARKET_ETFS)
    cfg = _config()
    return build_lab(tables, cfg, _cost_config(cfg, books), MARKET_ETFS)


BASE = Variant("residual", "residual", 1, False, 2)


def _zoned(lab: Lab, book: float = 100_000):
    scores = scores_of(lab, BASE)
    move = expected_move_of(lab, BASE, scores)
    result = run_path(lab, targets(BASE, scores, lab.tables, lab.cfg), "open_t1", no_trade(lab, book, move))
    return move, result


def test_no_trade_zone_and_costs_have_no_look_ahead() -> None:
    long = synthetic_market(seed=9)
    base = _lab(long)
    for cutoff in (MARKET_CAL[120], MARKET_CAL[220]):
        returns, prices, residuals, universe, sectors = long
        noisy = (
            perturb_after(returns, cutoff, ["ret"], seed=1, scale=1.0),
            perturb_after(prices, cutoff, ["open", "high", "low", "close", "volume"], seed=2, scale=1.0),
            perturb_after(residuals, cutoff, ["residual", "beta_market"], seed=3, scale=1.0),
            universe,
            sectors,
        )
        other = _lab(noisy)
        upto = int(base.tables.dates.searchsorted(cutoff, side="right"))
        for name, panel in (("spread", lambda lab: lab.costs.name_spread["edge"]), ("volatility", lambda lab: lab.costs.volatility)):
            np.testing.assert_array_equal(panel(base)[:upto], panel(other)[:upto], err_msg=name)
        (move_a, ra), (move_b, rb) = _zoned(base), _zoned(other)
        np.testing.assert_array_equal(move_a[:upto], move_b[:upto])
        np.testing.assert_array_equal(ra.holdings[:upto], rb.holdings[:upto])
        head = headline(base.ccfg)
        da = per_capital(daily_returns(ra, cost(base, head, 100_000, "open")), ra.dates)
        db = per_capital(daily_returns(rb, cost(other, head, 100_000, "open")), rb.dates)
        pd.testing.assert_frame_equal(da.loc[:cutoff], db.loc[:cutoff], check_exact=True)


def test_cost_config_rejects_unknown_or_missing_keys() -> None:
    cfg = _config()
    raw = load_config("costs")
    CostConfig.from_dict(raw, BacktestConfig.from_dict(load_config("backtest")))
    with pytest.raises(ValueError, match="unknown"):
        CostConfig.from_dict({**raw, "borrow": {**raw["borrow"], "hard_rate": 0.1}}, cfg)
    with pytest.raises(ValueError, match="missing"):
        CostConfig.from_dict({**raw, "impact": {k: v for k, v in raw["impact"].items() if k != "coefficients"}}, cfg)
    with pytest.raises(ValueError, match="phase 2 signal"):
        CostConfig.from_dict({**raw, "variants": [{**raw["variants"][0], "lookback_days": 2}]}, cfg)


def test_cost_runs_reproduce_exactly() -> None:
    def once():
        lab = _lab(synthetic_market(seed=11))
        _, result = _zoned(lab)
        return per_capital(daily_returns(result, cost(lab, headline(lab.ccfg), 100_000, "open")), result.dates)

    pd.testing.assert_frame_equal(once(), once(), check_exact=True)


def test_a_larger_book_pays_more_impact_and_less_commission_per_dollar() -> None:
    lab = _lab(books=(10_000, 10_000_000))
    outcomes = [o for o in run_all(lab) if o.setting == headline(lab.ccfg) and not o.no_trade and o.name == "baseline"]
    small, large = sorted(outcomes, key=lambda o: o.book)
    assert small.metrics["commission_bps_per_dollar"] > large.metrics["commission_bps_per_dollar"]
    assert small.metrics["impact_bps_per_dollar"] < large.metrics["impact_bps_per_dollar"]
    assert small.metrics["spread_bps_per_dollar"] == pytest.approx(large.metrics["spread_bps_per_dollar"])
    assert small.metrics["ann_gross_return"] == large.metrics["ann_gross_return"]


def test_log_judgement_and_report(tmp_path) -> None:
    lab = _lab()
    outcomes = run_all(lab)
    head = headline(lab.ccfg)
    # One decile configuration and the s-score, each at 9 cost settings, plus one no-trade path.
    assert len(outcomes) == 2 * 9 + 1
    now = dt.datetime(2026, 11, 16, tzinfo=dt.UTC)
    entries = log_entries(outcomes, lab, {"git_commit": None, "git_dirty": None}, now)
    assert len({e["config_id"] for e in entries}) == len(entries)
    # Book size and cost settings are not trials; the no-trade path is one of its own.
    assert len({path_id(e["config"]) for e in entries}) == 3
    zone = next(o for o in outcomes if o.no_trade)
    assert path_id(record(zone, lab)) != path_id(record(next(o for o in outcomes if o.name == "baseline"), lab))
    phase_2 = {path_id({**record(zone, lab), "no_trade": None, "cost_bps": 5.0}): 0.01}
    trials = trial_sets(phase_2, outcomes, lab)
    assert len(trials[100_000]) == 3        # the phase 2 path is rerun here, not a new trial
    verdict = verdicts(outcomes, trials, head)
    assert len(verdict) == 3 and set(verdict["trials"]) == {3}
    assert verdict["clears"].dtype == bool

    for name in ("a", "b"):
        out = tmp_path / name / "phase-03"
        experiments.append(out / "experiments.jsonl", entries)
        settings = [head, *alternatives(lab.ccfg)]
        cost_report.write_report(lab, variants(lab.cfg, lab.ccfg), settings, outcomes, verdict, None, experiments.read(out / "experiments.jsonl"), out)
    files = sorted(p.name for p in (tmp_path / "a" / "phase-03").iterdir())
    assert files == ["baseline_pnl.png", "capacity.png", "costs.md", "experiments.jsonl"]
    for f in ("baseline_pnl.png", "capacity.png", "costs.md"):
        assert (tmp_path / "a" / "phase-03" / f).read_bytes() == (tmp_path / "b" / "phase-03" / f).read_bytes()
    text = (tmp_path / "a" / "phase-03" / "costs.md").read_text()
    for section in ("## Net results by book size", "## Cost per dollar traded", "## Spread", "## Sensitivity",
                    "## No-trade zone", "## Borrow", "## Judging the result", "## Configurations tried"):
        assert section in text
    assert "binding" in text and "| reversal 0.2 |" in text
    # Every result is shown beside the capital it deploys: a filter can look safe by holding nothing.
    assert "| configuration | capital $ | capital | median names |" in text


def test_trials_count_each_phase_up_to_its_own(tmp_path) -> None:
    from statarb.backtest.trials import repository_trials

    now = dt.datetime(2026, 11, 16, tzinfo=dt.UTC)
    state = {"git_commit": None, "git_dirty": None}
    p2 = experiments.entry({"signal": "residual", "fill": "open_t1", "cost_bps": 5.0, "slippage_bps": 0.0}, {"gross_sharpe": 0.5}, 0, state, now)
    p3 = [
        experiments.entry({"signal": "residual", "fill": "open_t1", "book_size": b, "spread": 1.5, "no_trade": None, "name": "x"}, {"gross_sharpe": 0.6}, 0, state, now)
        for b in (1e5, 1e6)
    ]
    zone = experiments.entry({"signal": "residual", "fill": "open_t1", "no_trade": {"calibration_window_days": 252}}, {"gross_sharpe": 0.7}, 0, state, now)
    experiments.append(tmp_path / "phase-02" / "experiments.jsonl", [p2])
    experiments.append(tmp_path / "phase-03" / "experiments.jsonl", [*p3, zone])
    assert len(repository_trials(tmp_path, through="phase-02")) == 1
    later = repository_trials(tmp_path)
    assert len(later) == 2
    assert later[path_id(p2["config"])] == pytest.approx(0.6 / math.sqrt(252))


def test_the_report_does_not_import_the_runner() -> None:
    # Run as `python -m`, the runner is `__main__`: a report importing it would get a second copy
    # of its classes, and the cost settings it compares would never be equal.
    import inspect

    assert "import cost_run" not in inspect.getsource(cost_report)
    assert "from statarb.backtest.cost_run" not in inspect.getsource(cost_report)
