"""Every portfolio construction (`statarb.portfolio.optimiser`) through the same checks.

The decile sort, the optimiser and partial adjustment are all engine policies. Each must return
a target row the engine can fill, hold only universe members, keep gross
exposure within the capital, stay dollar neutral at its decisions, and decide
day t from data up to the close of t only.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from helpers import MARKET_CAL, synthetic_market
from portfolio_helpers import synthetic_lab
from statarb.backtest.engine import run
from statarb.portfolio.partial import PartialAdjustment, aims
from statarb.portfolio.paths import decile_specs, optimiser_specs
from statarb.testing.lookahead import perturb_after

BOOK = 500_000


PARTIAL = "partial adjustment"


def _specs():
    pc = synthetic_lab().pc
    head = optimiser_specs(pc)[0]
    return {"decile sort": decile_specs(pc)[0], "optimiser": head, PARTIAL: dataclasses.replace(head, cost_multiplier=0.0)}


IMPLEMENTATIONS = sorted(_specs())


def _run(lab, name: str):
    """The path of one implementation; partial adjustment trades a third of the way to its aim each day."""
    spec = _specs()[name]
    if name != PARTIAL:
        return lab.run_path(spec, BOOK)
    opt = lab.optimiser(spec, BOOK)
    grid = lab.lab.grids.open
    policy = PartialAdjustment(opt, aims(opt, len(grid.dates)), 1 / 3)
    return run(np.full(grid.returns.shape, np.nan), grid, lab.delay, lab.lab.borrow_rate[: len(grid.dates)], policy)


@pytest.fixture(scope="module")
def lab():
    return synthetic_lab()


@pytest.mark.parametrize("name", IMPLEMENTATIONS)
def test_targets_fill_on_the_engine_grid(lab, name: str) -> None:
    result = _run(lab, name)
    assert result.holdings.shape == lab.lab.grids.open.returns.shape
    assert np.isfinite(result.holdings).all()
    assert np.abs(result.holdings).sum() > 0


@pytest.mark.parametrize("name", IMPLEMENTATIONS)
def test_only_members_are_held_and_gross_stays_within_the_capital(lab, name: str) -> None:
    result = _run(lab, name)
    n = len(lab.lab.tables.stocks)
    decided = lab.lab.tables.members[: -lab.delay]                     # membership on the decision day of each fill
    held = result.holdings[lab.delay :, :n]
    assert np.all(held[~decided] == 0.0)
    assert np.all(result.holdings[:, n:] == 0.0)                       # no hedge instruments
    # Gross at each fill, before drift, at most the capital (within the solver's tolerance).
    traded = result.trades != 0
    full = traded.any(axis=1)
    assert np.all(np.abs(result.holdings[full]).sum(axis=1) <= 1.0 + 1e-3)


@pytest.mark.parametrize("name", IMPLEMENTATIONS)
def test_decisions_are_dollar_neutral(lab, name: str) -> None:
    result = _run(lab, name)
    gross = np.abs(result.holdings).sum(axis=1)
    held = gross > 0
    # Drift and dropped trades leave a small imbalance; neither construction leans one way.
    imbalance = np.abs(result.holdings.sum(axis=1))[held] / gross[held]
    assert imbalance.mean() < 0.05


@pytest.mark.parametrize("name", IMPLEMENTATIONS)
def test_no_look_ahead(lab, name: str) -> None:
    cutoff = MARKET_CAL[180]
    returns, prices, residuals, universe, sectors = synthetic_market(seed=5)
    noisy = (
        perturb_after(returns, cutoff, ["ret"], seed=7, scale=1.0),
        perturb_after(prices, cutoff, ["open", "high", "low", "close", "volume"], seed=8, scale=1.0),
        perturb_after(residuals.assign(beta_sector=0.5), cutoff, ["residual", "beta_market", "beta_sector"], seed=9, scale=1.0),
        universe,
        sectors,
    )
    other = synthetic_lab(noisy)
    upto = int(lab.lab.tables.dates.searchsorted(cutoff, side="right"))
    a, b = _run(lab, name), _run(other, name)
    np.testing.assert_array_equal(a.holdings[:upto], b.holdings[:upto])
    # The targets decided at the cutoff's close are the same, whatever the prices they fill at.
    s = upto - 1 + lab.delay
    traded_a, traded_b = a.trades[s] != 0, b.trades[s] != 0
    np.testing.assert_array_equal(traded_a, traded_b)
    np.testing.assert_array_equal(a.holdings[s][traded_a], b.holdings[s][traded_b])
