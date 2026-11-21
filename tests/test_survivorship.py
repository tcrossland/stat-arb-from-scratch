"""Tests for the survivorship measurement. A synthetic market with some symbols marked delisted; the
committed experiment logs are read for their ids alone."""

from __future__ import annotations

import datetime as dt
import itertools
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_CAL, MARKET_ETFS, PCA, synthetic_market
from portfolio_helpers import backtest_config
from statarb.backtest import experiments
from statarb.backtest import survivorship as sv
from statarb.backtest.engine import Grid, run
from statarb.backtest.trials import logs, path_id
from statarb.config import load_config, repo_root
from statarb.data import marketparquet as mp
from statarb.io import write_parquet
from statarb.signals.tables import TABLES

RANKING = {"size": 12, "liquidity_window_days": 20, "liquidity_min_observations": 15}
FACTORS = {
    "model": {"window_days": 60, "min_observations": 45, "sector_factor": "excess"},
    "events": {"lookback_days": 20, "volume_ratio": 3.0},
    "pca": {"factors": PCA.factors, "window_days": PCA.window_days, "min_observations": PCA.min_observations},
    "sector_etfs": MARKET_ETFS,
}
ETFS = ["SPY", *sorted(MARKET_ETFS.values())]
LAST = MARKET_CAL[-1]
DEAD = [f"S{i:02d}" for i in (3, 8, 13, 21)]      # carry the suffix; S21's bars stop part way
STOPS = MARKET_CAL[200]
CLOSE_AFTER = 5


def source_tables(suffix: str = mp.SUFFIX) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """The synthetic market as the second source holds it: dollar volume differing by name, some symbols
    suffixed, one of them stopping. Returns its returns and prices, and the first source's sectors and candidates."""
    returns, prices, _, _, sectors = synthetic_market(seed=11)
    scale = {t: 1.0 + 0.07 * i for i, t in enumerate(sorted(set(prices["ticker"])))}
    prices = prices.assign(volume=prices["volume"] * prices["ticker"].map(scale))
    names = {t: f"{t}{suffix}" for t in DEAD}
    stopped = lambda f: f.loc[~((f["ticker"] == "S21") & (f["date"] > STOPS))]
    returns, prices = (stopped(f).assign(ticker=lambda d: d["ticker"].replace(names)) for f in (returns, prices))
    candidates = pd.DataFrame({"ticker": [f"S{i:02d}" for i in range(30) if i % 3 and f"S{i:02d}" not in DEAD]})
    return returns, prices, sectors, candidates


def inputs(suffix: str = mp.SUFFIX) -> sv.Inputs:
    returns, prices, _, candidates = source_tables(suffix)
    listed = sv.build_universe(
        prices, sorted(set(prices["ticker"]) - set(ETFS)), MARKET_CAL, RANKING["size"], RANKING["liquidity_window_days"], RANKING["liquidity_min_observations"]
    )
    first = dict(zip(TABLES, synthetic_market(seed=11), strict=True))
    return sv.Inputs(existing=first, candidates=candidates, prices=prices, returns=returns, listed=listed, last=LAST)


def measured(suffix: str = mp.SUFFIX):
    return sv.measure(inputs(suffix), backtest_config(), FACTORS, "SPY", RANKING, suffix, CLOSE_AFTER)


@pytest.fixture(scope="module")
def result():
    return measured()


def test_the_survivors_universe_takes_the_suffix_as_an_argument() -> None:
    _, prices, _, _ = source_tables()
    with_it = sv.survivors_universe(prices, mp.SUFFIX, MARKET_CAL, RANKING, ETFS)
    assert not with_it["ticker"].str.endswith(mp.SUFFIX).any() and not set(with_it["ticker"]) & set(ETFS)
    without = sv.survivors_universe(prices, "~no such suffix", MARKET_CAL, RANKING, ETFS)
    assert without["ticker"].str.endswith(mp.SUFFIX).any()


def test_members_to_date_only_grow() -> None:
    universe = inputs().listed
    seen = sv.members_to_date(universe)
    days = sorted(seen)
    assert all(set(seen[a]) <= set(seen[b]) for a, b in itertools.pairwise(days))
    assert set(seen[days[0]]) == set(universe.loc[universe["rebalanced_on"] == days[0], "ticker"])
    assert set(seen[days[-1]]) == set(universe["ticker"])


def test_model_b_rests_on_no_later_ranking_and_no_later_return() -> None:
    data = inputs()
    cut = sorted(set(data.listed["rebalanced_on"]))[5]
    until = data.listed.loc[data.listed["rebalanced_on"] == cut, "date"].max()
    whole = sv.pca_residuals_to_date(data.returns, data.listed, MARKET_CAL, PCA)
    later = data.listed["rebalanced_on"] > cut
    others = sorted(set(data.returns["ticker"]) - set(ETFS))[:RANKING["size"]]
    swapped = pd.concat([data.listed.loc[~later], *(
        g.assign(ticker=others) for _, g in data.listed.loc[later].groupby("date")
    )])
    noise = np.random.default_rng(2).normal(0, 0.05, len(data.returns))
    shaken = data.returns.assign(ret=data.returns["ret"].where(data.returns["date"] <= until, data.returns["ret"] + noise))
    again = sv.pca_residuals_to_date(shaken, swapped, MARKET_CAL, PCA)
    early = lambda f: f.loc[f["date"] <= until].reset_index(drop=True)
    assert len(early(whole)) > 0 and (whole["date"] > until).any()
    pd.testing.assert_frame_equal(early(whole), early(again))


def test_seven_paths_run_on_the_second_source_and_two_on_the_first(result) -> None:
    existing, paths, universes = result
    assert [(p.universe, p.form) for p in existing] == [(sv.EXISTING, sv.MODEL_A), (sv.EXISTING, sv.RAW)]
    assert [(p.universe, p.form) for p in paths] == [
        (sv.CANDIDATES, sv.RAW), (sv.CANDIDATES, sv.MODEL_B), (sv.CANDIDATES, sv.MODEL_A),
        (sv.SURVIVORS, sv.RAW), (sv.SURVIVORS, sv.MODEL_B), (sv.LISTED, sv.RAW), (sv.LISTED, sv.MODEL_B),
    ]
    assert all(p.close_after == CLOSE_AFTER for p in paths) and all(p.close_after is None for p in existing)
    assert set(universes) == {sv.CANDIDATES, sv.SURVIVORS, sv.LISTED}
    assert not universes[sv.SURVIVORS]["ticker"].str.endswith(mp.SUFFIX).any()
    assert universes[sv.LISTED]["ticker"].str.endswith(mp.SUFFIX).any()
    assert set(universes[sv.CANDIDATES]["ticker"]) <= set(inputs().candidates["ticker"])


def test_the_suffix_decides_no_score_and_no_position(result) -> None:
    """Decision record 0008, point 8, for universes 2 and 4: with every suffix replaced by a label that
    means nothing, each path's target book is the same weights on the same securities."""
    _, paths, _ = result
    _, relabelled, _ = measured("~7")
    for plain, other in zip(paths, relabelled, strict=True):
        if plain.universe == sv.SURVIVORS:
            continue
        back = other.book.rename(columns=lambda t: t.replace("~7", mp.SUFFIX))
        pd.testing.assert_frame_equal(plain.book, back[plain.book.columns])
        np.testing.assert_allclose(plain.result.pnl.sum(axis=1), other.result.pnl.sum(axis=1), rtol=0, atol=1e-15)
    listed = next(p for p in paths if p.universe == sv.LISTED)
    assert (listed.book.loc[:, listed.book.columns.str.endswith(mp.SUFFIX)] != 0).any().any()


def test_the_stopped_name_is_closed_only_where_it_was_held(result) -> None:
    _, paths, _ = result
    by = {(p.universe, p.form): p for p in paths}
    assert all(p.result.closed == 0 for p in paths if p.universe != sv.LISTED)
    stopped = f"S21{mp.SUFFIX}"
    for form in (sv.RAW, sv.MODEL_B):
        p = by[sv.LISTED, form]
        col = list(p.result.tickers).index(stopped)
        after = p.result.dates > STOPS + pd.Timedelta(days=14)
        assert (p.result.holdings[after, col] == 0).all()


def test_the_paths_are_seven_new_trials(result) -> None:
    _, paths, _ = result
    cfg = backtest_config()
    entries = sv.log_entries(paths, cfg, LAST, {"git_commit": "x"}, dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    assert len(entries) == 7 * len(cfg.costs.levels_bps)
    ids = {path_id(e["config"]) for e in entries}
    assert len(ids) == 7
    assert all(e["config"]["universe"] in (sv.CANDIDATES, sv.SURVIVORS, sv.LISTED) and e["config"]["close_after"] == CLOSE_AFTER for e in entries)
    assert {e["config"]["residuals"] for e in entries if e["config"]["signal"] == "raw"} == {"pca"}
    assert all("closed" in e["metrics"] for e in entries)
    reports = Path(repo_root()) / load_config("data")["paths"]["reports"]
    earlier = {path_id(e["config"]) for path in logs(reports, "phase-06") for e in experiments.read(path)}
    assert not ids & earlier


def test_stopped_after_a_fall_reads_the_price_path_alone() -> None:
    days = MARKET_CAL[:30]
    rows = []
    for ticker, closes in {
        "ALIVE": np.linspace(10, 5, 30), "FELL": np.linspace(10, 5, 25), "FLAT": np.full(25, 10.0), "SHORT": np.linspace(10, 5, 10),
    }.items():
        rows += [(day, ticker, c, c, c, c, 1.0) for day, c in zip(days, closes, strict=False)]
    prices = pd.DataFrame(rows, columns=["date", "ticker", "open", "high", "low", "close", "volume"])
    assert sv.stopped_after_a_fall(prices, days[-1], 21, 0.10) == {"FELL"}
    assert sv.stopped_after_a_fall(prices, days[-1], 5, 0.10) == {"FELL", "SHORT"}


def test_the_delisting_loss_is_booked_where_a_stopped_name_is_closed_and_moves_no_position() -> None:
    days = pd.bdate_range("2026-01-05", periods=6)
    tradable = np.array([[1, 1], [1, 1], [1, 0], [1, 0], [1, 0], [1, 0]], dtype=bool)
    grid = Grid("close", days, ("A", "B"), np.where(tradable, 0.0, np.nan), tradable)
    book = np.tile([0.5, -0.5], (6, 1))
    result = run(book, grid, 0, 0.0, close_after=2)
    hit, count = sv.with_delisting_loss(result, grid, {"B"}, 0.55)
    assert count == 1 and hit.pnl[3, 1] == pytest.approx(0.55 * 0.5) and hit.pnl.sum() == pytest.approx(0.55 * 0.5)
    np.testing.assert_array_equal(hit.holdings, result.holdings)
    assert sv.with_delisting_loss(result, grid, {"A"}, 0.55)[1] == 0
    long = run(-book, grid, 0, 0.0, close_after=2)
    assert sv.with_delisting_loss(long, grid, {"B"}, 0.55)[0].pnl.sum() == pytest.approx(-0.55 * 0.5)


def test_a_cut_table_holds_no_later_row(tmp_path) -> None:
    frame = pd.DataFrame({"date": MARKET_CAL[:10], "ticker": "A", "ret": 0.0})
    write_parquet(frame, tmp_path / "t.parquet", ["date", "ticker"])
    got = sv.read_cut(tmp_path / "t.parquet", MARKET_CAL[6])
    assert got["date"].max() == MARKET_CAL[6] and len(got) == 7


def test_the_report_counts_the_later_delisted_and_is_the_same_twice(result) -> None:
    existing, paths, universes = result
    cfg = backtest_config()
    delisting = {"bars": 21, "fall": 0.10, "loss": 0.55}
    args = (existing, paths, universes, inputs(), cfg, mp.SUFFIX, delisting, {"alpaca": "a", "marketparquet": "m"}, (7, 7))
    text = sv.report(*args)
    assert text == sv.report(*args) and "## After the last bar" in text and "| survivors | raw |" in text
    shares = sv.leg_shares(next(p for p in paths if p.universe == sv.LISTED), mp.SUFFIX)
    assert shares["long"] > 0 and shares["short"] > 0
    assert sv.leg_shares(next(p for p in paths if p.universe == sv.SURVIVORS), mp.SUFFIX) == {"long": 0.0, "short": 0.0}
    assert load_config("marketparquet")["survivorship"]["delisting"] == delisting
