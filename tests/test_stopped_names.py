"""Tests for the engine's option for names whose bars stop, and for the trial id's keys for another
universe. Synthetic grids; the committed experiment logs are read for their ids alone."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_ETFS, synthetic_market
from portfolio_helpers import backtest_config
from statarb.backtest import experiments
from statarb.backtest.costs import FlatCost
from statarb.backtest.engine import Grid, daily_returns, run
from statarb.backtest.experiments import config_id
from statarb.backtest.sweep import (
    build_grids,
    fill,
    headline_variant,
    signal_of,
    targets,
)
from statarb.backtest.trials import PATH_KEYS, TRAILING, logs, path_id
from statarb.config import load_config, repo_root
from statarb.signals.tables import build_tables

DAYS = pd.bdate_range("2026-01-05", periods=8)
# The keys that set a position path before phase 7, as every logged entry of phases 2 to 6 was hashed.
EARLIER_KEYS = (
    "signal", "source", "lookback_days", "vol_scaled", "holding_days", "fill", "decile", "start", "sscore", "no_trade",
    "residuals", "optimiser", "model", "partial_adjustment", "slope_rule",
)


def grid(bars: list[list[int]]) -> Grid:
    """Three names, 1% a day where a name has a bar and no return where it has none."""
    tradable = np.array(bars, dtype=bool)
    return Grid("close", DAYS, ("A", "B", "C"), np.where(tradable, 0.01, np.nan), tradable)


# A trades every day. B has no bar on days 2 and 3 and comes back. C's bars stop for good after day 2.
STOPS = grid([[1, 1, 1], [1, 1, 1], [1, 0, 1], [1, 0, 0], [1, 1, 0], [1, 1, 0], [1, 1, 0], [1, 1, 0]])
HOLD = np.tile([0.5, -0.25, -0.25], (len(DAYS), 1))


def test_off_a_stopped_name_stays_in_the_book_for_good() -> None:
    result = run(HOLD, STOPS, 0, 0.0)
    assert result.closed == 0 and (result.holdings[3:, 2] != 0).all()
    assert result.missing_returns == 2 + 5       # B on two days, C on five


def test_on_a_name_is_closed_at_its_last_price_after_that_many_sessions_without_a_bar() -> None:
    off, on = run(HOLD, STOPS, 0, 0.0), run(HOLD, STOPS, 0, 0.0, close_after=3)
    assert on.closed == 1
    assert (on.holdings[:5, 2] != 0).all() and (on.holdings[5:, 2] == 0).all()      # no bar on days 3, 4 and 5
    held = off.holdings[4, 2]
    assert on.trades[5, 2] == pytest.approx(-held) and on.holdings[4, 2] == held    # at the last price: nothing was earned since
    assert (on.pnl[3:, 2] == 0).all() and (on.trades[6:, 2] == 0).all()
    np.testing.assert_array_equal(on.holdings[:, :2], off.holdings[:, :2])          # B's two days are under the count
    np.testing.assert_array_equal(on.holdings[:5], off.holdings[:5])
    assert on.missing_returns == 2 + 3          # C is counted until it is closed, and not after
    cost = daily_returns(on, FlatCost(10.0))
    assert cost.loc[DAYS[5], "turnover"] > daily_returns(off, FlatCost(10.0)).loc[DAYS[5], "turnover"]   # the close is a trade, and charged


def test_a_closed_name_trades_again_when_its_bars_return() -> None:
    on = run(HOLD, STOPS, 0, 0.0, close_after=1)
    assert on.closed == 2                                    # B on day 2, C on day 3
    assert on.holdings[2, 1] == 0 and on.holdings[3, 1] == 0 and on.holdings[4, 1] == -0.25
    assert (on.holdings[3:, 2] == 0).all()


def test_the_count_starts_again_at_each_bar() -> None:
    comes_and_goes = grid([[1, 1, 1], [1, 0, 1], [1, 1, 1], [1, 0, 1], [1, 1, 1], [1, 0, 1], [1, 1, 1], [1, 0, 1]])
    assert run(HOLD, comes_and_goes, 0, 0.0, close_after=2).closed == 0


def test_the_count_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        run(HOLD, STOPS, 0, 0.0, close_after=0)


def test_where_no_name_stops_the_option_changes_nothing() -> None:
    """Every logged path of phases 2 to 6 ran with the option off. On the synthetic market, where every
    name has every bar, the headline's result is the same arrays with it off, on, or never asked for."""
    cfg = backtest_config()
    returns, prices, residuals, universe, sectors = synthetic_market(seed=4)
    tables = build_tables(returns, prices, residuals, universe, sectors, "SPY", MARKET_ETFS)
    head = headline_variant(cfg)
    book = targets(head, signal_of(head, cfg, MARKET_ETFS).scores(tables), tables, cfg)
    grids = build_grids(tables)
    plain = fill(book, grids, cfg.fills.headline, cfg)
    for close_after in (None, 1, 5):
        other = run(book, grids.open, 1, cfg.costs.borrow_annual, close_after=close_after)
        assert other.closed == 0 and other.missing_returns == plain.missing_returns
        for name in ("holdings", "trades", "pnl", "borrow", "gross_held", "gross_after"):
            np.testing.assert_array_equal(getattr(other, name), getattr(plain, name))


def earlier_path_id(config: dict) -> str:
    return config_id({k: config[k] for k in EARLIER_KEYS if config.get(k) is not None and not (k == "slope_rule" and config[k] == TRAILING)})


def test_every_logged_path_keeps_its_id() -> None:
    reports = Path(repo_root()) / load_config("data")["paths"]["reports"]
    entries = [e for path in logs(reports, "phase-06") for e in experiments.read(path)]
    assert len(entries) > 1000
    assert all(path_id(e["config"]) == earlier_path_id(e["config"]) for e in entries)
    assert set(PATH_KEYS) - set(EARLIER_KEYS) == {"universe", "close_after"}


def test_another_universe_and_the_stop_rule_are_other_paths() -> None:
    config = {"signal": "raw", "lookback_days": 1, "fill": "open_t1", "start": "2017-01-03"}
    assert path_id({**config, "universe": None, "close_after": None}) == path_id(config)
    listed = path_id({**config, "universe": "listed"})
    assert len({path_id(config), listed, path_id({**config, "universe": "survivors"}), path_id({**config, "universe": "listed", "close_after": 5})}) == 4


def test_the_run_state_names_the_source_it_was_given() -> None:
    root = repo_root()
    theirs = experiments.run_state(root)
    ours = experiments.run_state(root, {"name": "marketparquet", "snapshot": "2026-11-20"})
    assert (ours["price_source"], ours["price_snapshot"]) == ("marketparquet", "2026-11-20")
    assert theirs["price_source"] == load_config("data")["source"]["name"]
    assert {k: v for k, v in ours.items() if not k.startswith("price_")} == {k: v for k, v in theirs.items() if not k.startswith("price_")}


def test_the_configured_count_is_a_whole_number_of_sessions() -> None:
    count = load_config("marketparquet")["engine"]["close_after_sessions"]
    assert isinstance(count, int) and count >= 1
