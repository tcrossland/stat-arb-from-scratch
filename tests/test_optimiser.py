"""Phase 4: the optimiser's constraints, turnover budget, minimum trade and re-solve, failures, look-ahead, the log and the report."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace

import cvxpy as cp
import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_CAL, synthetic_market
from portfolio_helpers import BOOKS, first_decision, portfolio_raw, synthetic_lab
from statarb.backtest import experiments
from statarb.backtest.engine import run
from statarb.backtest.sweep import targets
from statarb.backtest.trials import path_id
from statarb.portfolio import report
from statarb.portfolio.config import PortfolioConfig
from statarb.portfolio.optimiser import Optimiser, Settings, problem
from statarb.portfolio.paths import DECILE, HEADLINE, decile_specs, optimiser_specs
from statarb.portfolio.run import (
    log_entries,
    outcomes_for,
    record,
    trial_sets,
    verdicts,
)
from statarb.testing.lookahead import perturb_after

TOL = 1e-6


def _settings(**kw) -> Settings:
    base = {
        "risk_aversion": 3.0, "cost_multiplier": 1.0, "turnover_budget": None, "min_trade_dollars": 0.0, "re_solve": False, "re_solve_rounds": 5,
        "horizon_days": 5, "position_cap": 0.05, "adv_cap": 0.01, "gross_cap": 1.0, "dollar_tolerance": 0.0, "factor_tolerance": 0.01,
        "solver": "CLARABEL", "solver_options": {"tol_gap_abs": 1e-8, "tol_gap_rel": 1e-8, "tol_feas": 1e-8, "max_iter": 200},
    }
    return Settings(**{**base, **kw})


def _inputs(seed: int, m: int = 40, k: int = 3) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    w0 = rng.normal(0, 0.01, m)
    return {
        "mu": rng.normal(0, 0.01, m),
        "G": rng.normal(0, 0.01, (m, k)),
        "spec": rng.uniform(0.01, 0.03, m),
        "X": rng.normal(1, 0.3, (m, k)),
        "w0": w0 - w0.mean(),
        "lin": rng.uniform(1e-4, 5e-4, m),
        "imp": rng.uniform(1e-3, 1e-2, m),
        "cap": np.full(m, 0.05),
    }


def _solve(v, st, fixed=None) -> np.ndarray:
    prob, x = problem(v, st, fixed)
    prob.solve(solver=st.solver, **st.solver_options)
    assert prob.status == cp.OPTIMAL
    return x.value


@pytest.mark.parametrize("seed", range(5))
def test_constraints_hold_on_random_inputs(seed: int) -> None:
    v, st = _inputs(seed), _settings()
    x = _solve(v, st)
    assert np.all(np.abs(x) <= v["cap"] + TOL)
    assert np.abs(x).sum() <= st.gross_cap + TOL
    assert abs(x.sum()) <= TOL
    assert np.all(np.abs(v["X"].T @ x) <= st.factor_tolerance + TOL)


@pytest.mark.parametrize("budget", [0.05, 0.2])
def test_the_turnover_budget_is_never_exceeded_and_binds(budget: float) -> None:
    v = _inputs(1)
    v = {**v, "mu": v["mu"] * 20, "lin": v["lin"] * 0, "imp": v["imp"] * 0}     # a strong forecast that wants to trade
    free = _solve(v, _settings())
    x = _solve(v, _settings(turnover_budget=budget))
    assert np.abs(free - v["w0"]).sum() > budget
    assert np.abs(x - v["w0"]).sum() <= budget + TOL
    assert np.abs(x - v["w0"]).sum() == pytest.approx(budget, abs=1e-5)


def test_with_no_cost_and_no_risk_the_optimiser_is_a_sort() -> None:
    m = 40
    mu = np.linspace(-0.01, 0.01, m)[np.random.default_rng(2).permutation(m)]
    v = {"mu": mu, "G": np.zeros((m, 1)), "spec": np.zeros(m), "X": np.zeros((m, 1)), "w0": np.zeros(m),
         "lin": np.zeros(m), "imp": np.zeros(m), "cap": np.full(m, 0.05)}
    x = _solve(v, _settings(risk_aversion=0.0, cost_multiplier=0.0))
    order = np.argsort(mu)
    # Gross 1 at 5% a name: the 10 highest forecasts long at the cap, the 10 lowest short, the rest flat.
    np.testing.assert_allclose(x[order[-10:]], 0.05, atol=1e-5)
    np.testing.assert_allclose(x[order[:10]], -0.05, atol=1e-5)
    np.testing.assert_allclose(x[order[10:-10]], 0.0, atol=1e-5)


def _day(plab, spec, book, t=None):
    """The optimiser for a path, the grid time of a decision day and its inputs from an empty book."""
    opt = plab.optimiser(spec, book)
    s = (t or first_decision(plab) + 20) + opt.delay
    held = np.zeros(plab.lab.tables.residual.shape[1] + len(plab.lab.tables.hedges))
    return opt, s, held


def test_after_the_filter_no_trade_is_below_the_minimum_except_a_close() -> None:
    plab = synthetic_lab()
    head = optimiser_specs(plab.pc)[0]
    for minimum in (1_000.0, 5_000.0):
        spec = replace(head, min_trade_dollars=minimum)
        opt, s, _ = _day(plab, spec, 500_000)
        rng = np.random.default_rng(0)
        held = np.concatenate([rng.normal(0, 0.01, opt.n), np.zeros(len(plab.lab.tables.hedges))])
        values = opt.day_inputs(s, held)
        _, w = opt.solve(values)
        out = opt.filter_trades(w, values)
        traded = np.isfinite(out.targets)
        size = np.abs(out.targets - values["w0"]) * 500_000
        closes = traded & (out.targets == 0.0)
        assert np.all(size[traded & ~closes] >= minimum)
        nonzero = out.targets[traded & ~closes]
        assert np.all(np.abs(nonzero) * 500_000 >= minimum)
        assert out.note.dropped > 0


def test_the_re_solve_restores_neutrality() -> None:
    plab = synthetic_lab()
    head = optimiser_specs(plab.pc)[0]
    spec = replace(head, min_trade_dollars=5_000.0)
    opt, s, _ = _day(plab, spec, 500_000)
    rng = np.random.default_rng(1)
    held = np.concatenate([rng.normal(0, 0.008, opt.n), np.zeros(len(plab.lab.tables.hedges))])
    held[: opt.n] -= held[: opt.n].mean()
    _, filtered = opt.decide(s, held)
    resolved_opt = replace(opt, settings=replace(opt.settings, re_solve=True))
    _, resolved = resolved_opt.decide(s, held)
    assert filtered.dollar_breach > 1e-4 or filtered.factor_breach > 1e-4
    assert resolved.rounds >= 1 and resolved.re_solve_status == ""
    assert resolved.dollar_breach < 1e-6 and resolved.factor_breach < 1e-6


def test_a_forced_solver_failure_holds_the_previous_book() -> None:
    plab = synthetic_lab()
    head = optimiser_specs(plab.pc)[0]
    ok = plab.run_path(head, 500_000)
    first = first_decision(plab)
    failing = replace(plab.optimiser(head, 500_000), settings=replace(plab.optimiser(head, 500_000).settings, solver_options={"max_iter": 1}))
    # Fail from the 30th decision day on: the book filled by then is held, drifting, and never traded again.
    fail_from = first + 30
    policy = _SwitchAt(plab.optimiser(head, 500_000), failing, fail_from + plab.delay)
    grid = plab.lab.grids.open
    held = run(np.full(grid.returns.shape, np.nan), grid, plab.delay, plab.lab.borrow_rate, policy)
    s0 = fail_from + plab.delay
    np.testing.assert_array_equal(held.holdings[:s0], ok.holdings[:s0])
    assert np.all(held.trades[s0:] == 0.0)
    assert np.abs(held.holdings[s0]).sum() > 0
    statuses = [n.status for n in held.notes if n.date_index >= fail_from]
    assert statuses and all(x == "user_limit" for x in statuses)


class _SwitchAt:
    """A policy that hands over from one optimiser to another at grid time `at`."""

    def __init__(self, before: Optimiser, after: Optimiser, at: int) -> None:
        self.before, self.after, self.at = before, after, at

    def __call__(self, s, held, drifted, target):
        return (self.before if s < self.at else self.after)(s, held, drifted, target)


def _perturbed(cutoff):
    returns, prices, residuals, universe, sectors = synthetic_market(seed=5)
    return (
        perturb_after(returns, cutoff, ["ret"], seed=1, scale=1.0),
        perturb_after(prices, cutoff, ["open", "high", "low", "close", "volume"], seed=2, scale=1.0),
        perturb_after(residuals.assign(beta_sector=0.5), cutoff, ["residual", "beta_market", "beta_sector"], seed=3, scale=1.0),
        universe,
        sectors,
    )


def _decided(result, upto: int) -> list[dict]:
    return [{**vars(n), "seconds": 0} for n in result.notes if n.date_index < upto]


def test_calibration_risk_and_decisions_have_no_look_ahead() -> None:
    base = synthetic_lab()
    specs = [optimiser_specs(base.pc)[0], next(s for s in optimiser_specs(base.pc) if s.name == "Model B")]
    for cutoff in (MARKET_CAL[150], MARKET_CAL[230]):
        other = synthetic_lab(_perturbed(cutoff))
        upto = int(base.lab.tables.dates.searchsorted(cutoff, side="right"))
        for key in base.moves:
            np.testing.assert_array_equal(base.moves[key][:upto], other.moves[key][:upto], err_msg=str(key))
        for name in ("etf", "pca"):
            for t in range(upto - 5, upto):
                a, b = base.risks[name].day(t), other.risks[name].day(t)
                for field in ("loadings", "factor_cov", "specific_var"):
                    np.testing.assert_array_equal(getattr(a, field), getattr(b, field), err_msg=f"{name} {field}")
        for spec in specs:
            ra, rb = base.run_path(spec, 500_000), other.run_path(spec, 500_000)
            # Holdings through the cutoff, and every decision made by its close. The fill of the last
            # decision lands after the cutoff, where untraded names drift with later prices.
            np.testing.assert_array_equal(ra.holdings[:upto], rb.holdings[:upto], err_msg=spec.name)
            assert _decided(ra, upto) == _decided(rb, upto)


def test_the_decile_sort_policy_is_the_phase_3_path() -> None:
    plab = synthetic_lab()
    spec = decile_specs(plab.pc)[0]
    lab = plab.lab
    variant = plab.variants[spec.variant]
    from statarb.backtest.cost_run import run_path, scores_of

    phase_3 = run_path(lab, targets(variant, scores_of(lab, variant), lab.tables, lab.cfg), plab.pc.run.fill)
    here = plab.run_path(spec, 500_000)
    np.testing.assert_array_equal(here.holdings, phase_3.holdings)
    np.testing.assert_array_equal(here.pnl, phase_3.pnl)


def test_runs_reproduce_exactly() -> None:
    spec = optimiser_specs(synthetic_lab().pc)[0]
    a, b = synthetic_lab().run_path(spec, 5_000_000), synthetic_lab().run_path(spec, 5_000_000)
    np.testing.assert_array_equal(a.holdings, b.holdings)


def test_portfolio_config_rejects_unknown_or_missing_keys() -> None:
    from portfolio_helpers import backtest_config, cost_config

    ccfg = cost_config(backtest_config())
    raw = portfolio_raw()
    PortfolioConfig.from_dict(raw, ccfg)
    with pytest.raises(ValueError, match="unknown"):
        PortfolioConfig.from_dict({**raw, "optimiser": {**raw["optimiser"], "risk_aversion": 3.0}}, ccfg)
    with pytest.raises(ValueError, match="missing"):
        PortfolioConfig.from_dict({**raw, "headline": {k: v for k, v in raw["headline"].items() if k != "re_solve"}}, ccfg)
    with pytest.raises(ValueError, match="variant"):
        PortfolioConfig.from_dict({**raw, "run": {**raw["run"], "variant": "nonexistent"}}, ccfg)
    with pytest.raises(ValueError, match="solver"):
        PortfolioConfig.from_dict({**raw, "optimiser": {**raw["optimiser"], "solver": "SCS"}}, ccfg)
    with pytest.raises(ValueError, match="book sizes"):
        PortfolioConfig.from_dict({**raw, "run": {**raw["run"], "book_sizes": [123_456]}}, ccfg)


def test_trials_log_and_report(tmp_path) -> None:
    plab = synthetic_lab()
    pc = plab.pc
    pick = [*decile_specs(pc), *optimiser_specs(pc)]
    outcomes = [o for spec in pick for b in BOOKS for o in outcomes_for(plab, spec, b, plab.run_path(spec, b))]
    head = plab.head_setting()
    now = dt.datetime(2026, 11, 16, tzinfo=dt.UTC)
    entries = log_entries(outcomes, plab, {"git_commit": None, "git_dirty": None}, now)
    assert len({e["config_id"] for e in entries}) == len(entries)
    # The decile sort on Model A is phase 3's path; each other path is one trial across book sizes.
    decile = next(o for o in outcomes if o.name == DECILE)
    phase_3_record = {k: v for k, v in record(decile, plab).items() if k not in ("residuals", "optimiser")}
    assert path_id(record(decile, plab)) == path_id(phase_3_record)
    assert len({path_id(e["config"]) for e in entries}) == len(pick)
    trials = trial_sets({path_id(phase_3_record): 0.01, "earlier": 0.02}, outcomes, plab)
    assert {len(v) for v in trials.values()} == {len(pick) + 1}
    verdict = verdicts(outcomes, trials, head)
    assert len(verdict) == len(pick) * len(BOOKS) and verdict["clears"].dtype == bool

    phase_3 = [
        experiments.entry({"name": "baseline", "no_trade_zone": True, "book_size": b, "spread": head.spread},
                          {"sharpe": 0.1, "ann_return": 0.01, "ann_gross_return": 0.02, "turnover": 0.1, "mean_exposure": 0.5, "net_dollar_imbalance": 0.2},
                          0, {}, now)
        for b in BOOKS
    ]
    for name in ("a", "b"):
        out = tmp_path / name
        report.write_report(plab, outcomes, verdict, phase_3, entries, out)
    files = sorted(p.name for p in (tmp_path / "a").iterdir())
    assert files == ["cumulative_net.png", "portfolio.md", "turnover_frontier.png"]
    for f in files:
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes()
    text = (tmp_path / "a" / "portfolio.md").read_text()
    for section in ("## Decile sort against optimiser", "## Net return by year", "## Realised factor exposure", "## Model A and Model B",
                    "### Decile P&L by size", "## Against the no-trade zone", "## Sensitivity", "## Cost penalty against turnover budget",
                    "## Minimum trade size and the re-solve", "## Spread bracket", "## Solver", "## Against the bar"):
        assert section in text
    assert "baseline, no-trade zone (phase 3)" in text
    assert f"| {HEADLINE} |" in text or f" {HEADLINE} |" in text


def test_the_report_does_not_import_the_runner() -> None:
    import inspect

    source = inspect.getsource(report)
    assert "from statarb.portfolio.run" not in source and "import run" not in source


def test_daily_frames_are_per_dollar_of_capital() -> None:
    plab = synthetic_lab()
    spec = optimiser_specs(plab.pc)[0]
    o = outcomes_for(plab, spec, 500_000, plab.run_path(spec, 500_000))[0]
    assert isinstance(o.daily, pd.DataFrame) and o.daily.index[0] == plab.lab.tables.dates[plab.lab.start]
    assert o.metrics["mean_exposure"] <= plab.pc.optimiser.gross_cap + TOL
