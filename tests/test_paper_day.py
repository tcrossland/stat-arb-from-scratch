"""The daily job's step on the synthetic market: a run of sessions, one ledger day at a time, gives the backtest's path exactly."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_CAL
from runner_helpers import market_long, market_settings
from statarb.data.schema import TICKER
from statarb.models.backend import make_backend
from statarb.models.forecast import (
    ForecastSignal,
    ModelHashError,
    SavedBlock,
    load_checked,
    saved_forecast,
)
from statarb.models.run import build_period_lab
from statarb.models.training import model_name
from statarb.paper import ledger
from statarb.paper.config import TRAILING
from statarb.paper.day import (
    MissingSession,
    backtest_path,
    backtest_result,
    ledger_day,
    session_inputs,
    strategy_of,
    strategy_panels,
)
from statarb.portfolio.optimiser import Optimiser

META = ledger.DayMeta(500_000.0, "frozen", "c0ffee", False, "2026-01-01")
DAYS = 6


@pytest.fixture(scope="module")
def settings():
    return market_settings()


@pytest.fixture(scope="module")
def long():
    return market_long()


@pytest.fixture(scope="module")
def saved(settings, long, tmp_path_factory):
    """One horizon's walk-forward on the whole synthetic market, its models saved and loaded back with their hashes."""
    H = settings.mc.target.horizons[0]
    plab = build_period_lab(long, settings, MARKET_CAL[-1])
    tables = plab.lab.tables
    run = ForecastSignal(settings.mc, H).run(tables)
    model_dir = tmp_path_factory.mktemp("models")
    blocks = []
    for fit in run.walk.fits:
        name = model_name(fit)
        blocks.append(SavedBlock(tables.dates[fit.fold.test_start], name, fit.model.save(model_dir / name)))
    backend = make_backend(settings.mc.model.library, settings.mc.lightgbm)
    models = tuple((b.test_first, load_checked(backend, model_dir, b)) for b in blocks)
    return H, run, tables, model_dir, blocks, models


def first_session(settings, long, strategy) -> int:
    """A few days after the strategy's first calibrated move on the whole market."""
    p = strategy_panels(long, MARKET_CAL[-1], MARKET_CAL[0], strategy)
    return int(np.flatnonzero(np.isfinite(p.slopes))[0]) + 3


def live_run(long, strategy, first: int, days: int, root=None) -> list[pd.DataFrame]:
    """Sessions first .. first+days-1, each on the tables cut at it, carried through the ledger on disk when `root` is given."""
    carry = ledger.Carry.flat(())
    frames = []
    for d in MARKET_CAL[first : first + days]:
        frame, _ = ledger_day(session_inputs(long, d, MARKET_CAL[first], strategy), carry, META)
        if root is not None:
            ledger.write_day(root, frame)
            frame = ledger.read_day(root, d)
        carry = ledger.carry_of(frame)
        frames.append(frame)
    return frames


def assert_matches_backtest(long, strategy, first: int, frames: list[pd.DataFrame]) -> None:
    last = first + len(frames) - 1
    p = strategy_panels(long, MARKET_CAL[last], MARKET_CAL[first], strategy)
    o = backtest_path(p, strategy)
    result = backtest_result(p, strategy)
    grid = getattr(p.plab.lab.grids, p.plab.kind)
    order = {t: i for i, t in enumerate(grid.tickers)}
    for k, frame in enumerate(frames):
        s = first + k
        cols = [order[t] for t in frame[TICKER]]
        np.testing.assert_array_equal(frame["holding"].to_numpy(), result.holdings[s, cols])
        np.testing.assert_array_equal(frame["trade"].to_numpy(), result.trades[s, cols])
        np.testing.assert_array_equal(frame["pnl"].to_numpy(), result.pnl[s, cols])
    assert o.daily.index.max() == MARKET_CAL[last]
    assert np.abs(result.holdings[last]).sum() > 0          # the run traded


# --- the live step is the backtest's step ---------------------------------------------------------------


@pytest.mark.parametrize("rule", ["decile sort", "no-trade zone", "optimiser κ = 1"])
def test_a_run_of_sessions_gives_the_backtests_path(settings, long, rule) -> None:
    strategy = strategy_of(settings, "baseline", rule, TRAILING, 500_000)
    first = first_session(settings, long, strategy)
    assert_matches_backtest(long, strategy, first, live_run(long, strategy, first, DAYS))


@pytest.mark.parametrize("slope_rule", ["floored", "expanding"])
def test_every_slope_rule_runs_live_as_in_the_backtest(settings, long, slope_rule) -> None:
    strategy = strategy_of(settings, "three-day lookback", "no-trade zone", slope_rule, 5_000_000)
    first = first_session(settings, long, strategy)
    assert_matches_backtest(long, strategy, first, live_run(long, strategy, first, DAYS))


def test_a_model_forecast_from_saved_files_runs_live_as_in_the_backtest(settings, long, saved) -> None:
    H, *_, models = saved
    strategy = strategy_of(settings, f"model H={H}", "no-trade zone", TRAILING, 500_000, models)
    first = first_session(settings, long, strategy)
    assert_matches_backtest(long, strategy, first, live_run(long, strategy, first, DAYS))


def test_the_ledger_on_disk_carries_the_run_exactly(settings, long, tmp_path) -> None:
    strategy = strategy_of(settings, "baseline", "no-trade zone", TRAILING, 500_000)
    first = first_session(settings, long, strategy)
    in_memory = live_run(long, strategy, first, 4)
    on_disk = live_run(long, strategy, first, 4, tmp_path)
    for a, b in zip(in_memory, on_disk, strict=True):
        pd.testing.assert_frame_equal(a, b)
    assert ledger.check(tmp_path) == []


def test_the_recorded_decision_is_filled_not_recomputed(settings, long) -> None:
    """A revision overnight cannot change an order: the fill reads the ledger's target, not the day's tables."""
    strategy = strategy_of(settings, "baseline", "decile sort", TRAILING, 500_000)
    first = first_session(settings, long, strategy)
    frames = live_run(long, strategy, first, 2)
    carry = ledger.carry_of(frames[0])
    changed = ledger.Carry(carry.tickers, carry.holdings, -carry.target, carry.expected_move)
    d = MARKET_CAL[first + 1]
    inputs = session_inputs(long, d, MARKET_CAL[first], strategy)
    frame, _ = ledger_day(inputs, changed, META)
    traded = np.isfinite(changed.target)
    np.testing.assert_array_equal(frame.set_index(TICKER).loc[list(carry.tickers), "holding"].to_numpy()[traded], -carry.target[traded])


# --- the optimiser's failure -----------------------------------------------------------------------------


def test_a_solver_failure_holds_the_book_and_the_next_day_continues(settings, long, monkeypatch) -> None:
    strategy = strategy_of(settings, "baseline", "optimiser κ = 1", TRAILING, 500_000)
    first = first_session(settings, long, strategy) + 3
    frames = live_run(long, strategy, first, 3)
    assert set(frames[-1]["status"]) == {"optimal"}
    carry = ledger.carry_of(frames[-1])
    d = MARKET_CAL[first + 3]
    real = Optimiser.solve
    monkeypatch.setattr(Optimiser, "solve", lambda self, values, fixed=None: ("solver_error", None))
    failed, _ = ledger_day(session_inputs(long, d, MARKET_CAL[first], strategy), carry, META)
    assert set(failed["status"]) == {"solver_error"}
    np.testing.assert_array_equal(failed["holding"].to_numpy(), failed["drifted"].to_numpy())
    assert (failed["trade"] == 0).all()
    monkeypatch.setattr(Optimiser, "solve", real)
    nxt, _ = ledger_day(session_inputs(long, MARKET_CAL[first + 4], MARKET_CAL[first], strategy), ledger.carry_of(failed), META)
    assert set(nxt["status"]) == {"optimal"}
    assert (nxt["trade"] != 0).any()


# --- refusals ------------------------------------------------------------------------------------------


def test_a_session_the_tables_lack_is_missing(settings, long) -> None:
    strategy = strategy_of(settings, "baseline", "decile sort", TRAILING, 500_000)
    later = MARKET_CAL[-1] + pd.offsets.BDay(1)
    with pytest.raises(MissingSession, match="no SPY bar"):
        session_inputs(long, later, MARKET_CAL[100], strategy)


@pytest.mark.parametrize(
    ("forecast", "rule", "match"),
    [
        ("baseline", "partial adjustment", "decile sort, the no-trade zone or"),
        ("raw reversal", "decile sort", "not a forecast phase 5 ran"),
        ("model H=7", "decile sort", "horizon 7"),
        ("model H=1", "decile sort", "needs its saved model files"),
    ],
)
def test_refuses_a_strategy_it_cannot_run(settings, forecast, rule, match) -> None:
    with pytest.raises(ValueError, match=match):
        strategy_of(settings, forecast, rule, TRAILING, 500_000)


# --- saved models ---------------------------------------------------------------------------------------


def test_saved_models_give_the_walk_forwards_forecast(saved) -> None:
    _, run, tables, _, _, models = saved
    shape = (len(tables.dates), len(tables.stocks))
    walk = run.panel(shape)
    from_files = saved_forecast(run.features, tables.dates, models, shape)
    stop = max(f.fold.test_stop for f in run.walk.fits)
    np.testing.assert_array_equal(from_files[:stop], walk[:stop])
    assert np.isfinite(from_files[stop:]).any() or stop == shape[0]      # the last model continues


def test_a_changed_model_file_is_refused(saved, settings) -> None:
    _, _, _, model_dir, blocks, _ = saved
    backend = make_backend(settings.mc.model.library, settings.mc.lightgbm)
    with pytest.raises(ModelHashError, match="not the recorded"):
        load_checked(backend, model_dir, SavedBlock(blocks[0].test_first, blocks[0].file, "0" * 64))
    with pytest.raises(ModelHashError, match="missing"):
        load_checked(backend, model_dir, SavedBlock(blocks[0].test_first, "absent.txt", blocks[0].sha256))
