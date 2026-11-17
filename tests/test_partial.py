"""Partial adjustment (decision record 0006): the aim, the trade towards it, and the rule that sets the trade rate."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_helpers import synthetic_lab
from statarb.backtest.engine import run
from statarb.portfolio.partial import PartialAdjustment, aims, choose_rate, rate_grid
from statarb.portfolio.paths import optimiser_specs

BOOK = 500_000


@pytest.fixture(scope="module")
def setup():
    lab = synthetic_lab()
    spec = dataclasses.replace(optimiser_specs(lab.pc)[0], cost_multiplier=0.0)
    opt = lab.optimiser(spec, BOOK)
    grid = lab.lab.grids.open
    return lab, opt, grid, aims(opt, len(grid.dates))


def _path(lab, opt, grid, aim, rate):
    return run(np.full(grid.returns.shape, np.nan), grid, lab.delay, lab.lab.borrow_rate[: len(grid.dates)], PartialAdjustment(opt, aim, rate))


def test_the_aim_does_not_depend_on_the_book_held(setup) -> None:
    _, opt, _, aim = setup
    rng = np.random.default_rng(0)
    days = [s for s in aim.notes if np.isfinite(aim.weights[s]).all()]
    assert len(days) > 50
    for s in days[::25]:
        held = rng.normal(0, 0.01, opt.n)
        _, w = opt.solve(opt.day_inputs(s, held))
        # The same problem from another starting book, so another path through the solver: equal to within
        # $50 on this book, well under the $1,000 minimum trade.
        np.testing.assert_allclose(w, aim.weights[s], atol=1e-4)


def test_aims_refuse_a_cost_term_or_a_turnover_budget(setup) -> None:
    lab, *_ = setup
    head = optimiser_specs(lab.pc)[0]
    for spec in (head, dataclasses.replace(head, cost_multiplier=0.0, turnover_budget=0.5)):
        with pytest.raises(ValueError, match="no cost term"):
            aims(lab.optimiser(spec, BOOK), 10)


def test_each_trade_moves_the_rate_of_the_way_to_the_aim(setup) -> None:
    _, opt, _, aim = setup
    rng = np.random.default_rng(1)
    s = next(s for s in aim.notes if np.isfinite(aim.weights[s]).all() and s > 100)
    held = np.zeros(opt.n + 10)
    held[: opt.n] = rng.normal(0, 0.01, opt.n)
    values = opt.day_inputs(s, held)
    w0, ok = values["w0"], values["ok"]
    targets, note = PartialAdjustment(opt, aim, 0.25)(s, held, held, np.full(held.shape, np.nan))
    traded = np.isfinite(targets[: opt.n])
    expected = np.where(ok, w0 + 0.25 * (aim.weights[s] - w0), 0.0)
    floor = opt.settings.min_trade_dollars / opt.cost.book_size
    expected = np.where(np.abs(expected) < floor, 0.0, expected)
    np.testing.assert_allclose(targets[: opt.n][traded], expected[traded])
    assert note.status == "optimal" and np.isnan(targets[opt.n :]).all()


def test_names_that_may_not_be_held_close_at_once(setup) -> None:
    _, opt, _, aim = setup
    s = next(s for s in aim.notes if np.isfinite(aim.weights[s]).all() and s > 100)
    held = np.full(opt.n + 10, 0.0)
    held[: opt.n] = 0.01
    values = opt.day_inputs(s, held)
    targets, _ = PartialAdjustment(opt, aim, 0.1)(s, held, held, np.full(held.shape, np.nan))
    assert (targets[: opt.n][~values["ok"]] == 0.0).all()


def test_a_rate_of_one_without_the_filter_trades_to_the_aim(setup) -> None:
    _, opt, _, aim = setup
    nofilter = dataclasses.replace(opt, settings=dataclasses.replace(opt.settings, min_trade_dollars=0.0))
    held = np.zeros(opt.n + 10)
    held[: opt.n] = np.random.default_rng(2).normal(0, 0.01, opt.n)
    for s in [s for s in aim.notes if np.isfinite(aim.weights[s]).all()][5::40]:
        targets, _ = PartialAdjustment(nofilter, aim, 1.0)(s, held, held, np.full(held.shape, np.nan))
        ok = nofilter.day_inputs(s, held)["ok"]
        np.testing.assert_allclose(np.nan_to_num(targets[: opt.n], nan=0.0)[ok], aim.weights[s][ok], atol=1e-12)
        assert (np.nan_to_num(targets[: opt.n], nan=0.0)[~ok] == 0.0).all()


def test_turnover_rises_with_the_rate(setup) -> None:
    lab, opt, grid, aim = setup
    traded = [np.abs(_path(lab, opt, grid, aim, r).trades).sum() for r in (0.1, 0.3, 1.0)]
    assert traded[0] < traded[1] < traded[2]


def test_a_rate_outside_zero_to_one_is_refused(setup) -> None:
    _, opt, _, aim = setup
    for rate in (0.0, 1.5):
        with pytest.raises(ValueError, match="trade rate"):
            PartialAdjustment(opt, aim, rate)


def test_choose_rate_takes_the_closest_turnover_from_the_whole_grid() -> None:
    grid = rate_grid(0.1)
    assert grid[0] == 0.1 and grid[-1] == 1.0 and len(grid) == 10
    seen = []

    def turnover(r: float) -> float:
        seen.append(r)
        return 0.51 if r == 0.7 else r                # not monotone at 0.7: the whole grid is read
    choice = choose_rate(turnover, 0.52, grid)
    assert choice.rate == 0.7 and choice.turnover == 0.51 and sorted(seen) == list(grid) and choice.tried[0.5] == 0.5
    assert choose_rate(lambda r: r, 0.25, (0.2, 0.3)).rate == 0.2          # a tie takes the smaller rate
    with pytest.raises(ValueError, match="divide 1"):
        rate_grid(0.3)
