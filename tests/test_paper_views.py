"""The ledger explorer's views, on a synthetic ledger built to hit each case."""

from __future__ import annotations

import datetime as dt
import shutil

import numpy as np
import pandas as pd
import pytest

import statarb.io
from statarb.config import repo_root
from statarb.data.schema import DATE, TICKER
from statarb.paper import ledger, momentum, views
from statarb.paper.config import Run, load_paper_config
from synthetic_ledger import (
    BOOK_SIZE,
    CHANGE,
    DATES,
    HEDGES,
    SECTORS,
    concat,
    frames,
    write,
)

PATHS = tuple(spec.name for spec in momentum.load_momentum_config(repo_root()).runs)   # the momentum paths, by name


@pytest.fixture
def frame() -> pd.DataFrame:
    return concat(frames())


@pytest.fixture
def root(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "data.toml").write_text('[paths]\npaper = "data/paper"\n')
    write(tmp_path / "data" / "paper")
    return tmp_path


@pytest.fixture
def momentum_frame() -> pd.DataFrame:
    return concat(frames(momentum=True))


@pytest.fixture
def both(root):
    """A checkout with the reversal ledger and a ledger for each momentum path, as config/momentum_forward.toml names
    them, each from its own seed."""
    shutil.copy(repo_root() / "config" / "momentum_forward.toml", root / "config" / "momentum_forward.toml")
    paper = momentum.paper_dir(root, momentum.load_momentum_config(root))
    for seed, name in enumerate(PATHS, start=1):
        write(paper, seed, path=name)
    return root


def _tree(path) -> dict[str, bytes]:
    return {str(p.relative_to(path)): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


def test_the_synthetic_ledger_chains(tmp_path) -> None:
    write(tmp_path)
    assert ledger.check(tmp_path / "ledger") == []


def test_load_reads_the_ledger_and_the_snapshots_sectors(root, frame) -> None:
    loaded = views.load(root)
    pd.testing.assert_frame_equal(concat([loaded.frame]), frame)
    pd.testing.assert_frame_equal(loaded.sectors, SECTORS)
    assert loaded.snapshot == "2026-01-02"
    assert loaded.problems == ()


def test_load_ignores_an_incomplete_snapshot(root) -> None:
    (root / "data" / "paper" / "processed" / "2026-01-09").mkdir()
    assert views.load(root).snapshot == "2026-01-02"


def test_load_writes_nothing_and_reads_only_the_ledger_and_sectors(root, monkeypatch) -> None:
    read, original = [], statarb.io.pq.read_table
    monkeypatch.setattr(statarb.io.pq, "read_table", lambda path, *a, **k: read.append(path) or original(path, *a, **k))
    before = _tree(root)
    views.load(root)
    assert _tree(root) == before
    paper = root / "data" / "paper"
    assert {p.parent for p in read} == {paper / "ledger", paper / "processed" / "2026-01-02"}
    assert {p.name for p in read if p.parent.name == "2026-01-02"} == {"sectors.parquet"}


def test_an_empty_ledger_loads(tmp_path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "data.toml").write_text('[paths]\npaper = "data/paper"\n')
    loaded = views.load(tmp_path)
    assert loaded.frame.empty and loaded.snapshot is None and loaded.problems == ()


def test_load_reads_the_runs_sessions_where_the_checkout_has_them(root) -> None:
    assert views.load(root).run is None                    # no config/paper.toml: not a forward run's checkout
    shutil.copy(repo_root() / "config" / "paper.toml", root / "config" / "paper.toml")
    assert views.load(root).run == load_paper_config().run


def test_the_ledgers_are_the_reversal_runs_then_each_momentum_path(root, both) -> None:
    assert len(PATHS) >= 2
    assert views.ledgers(both) == (views.REVERSAL, *PATHS)


def test_a_checkout_without_the_momentum_run_has_only_the_reversal_ledger(root) -> None:
    assert views.ledgers(root) == (views.REVERSAL,)
    with pytest.raises(ValueError, match="reversal"):
        views.load(root, PATHS[0])


def test_load_reads_a_momentum_paths_ledger_and_its_runs_sectors(both) -> None:
    paper = momentum.paper_dir(both, momentum.load_momentum_config(both))
    for seed, name in enumerate(PATHS, start=1):
        loaded = views.load(both, name)
        pd.testing.assert_frame_equal(concat([loaded.frame]), concat(frames(seed, momentum=True)))
        pd.testing.assert_frame_equal(loaded.sectors, SECTORS)
        assert loaded.name == name and loaded.folder == paper / name / "ledger"
        assert loaded.snapshot == "2026-01-02" and loaded.problems == ()
    assert views.load(both).name == views.REVERSAL
    pd.testing.assert_frame_equal(concat([views.load(both).frame]), concat(frames()))   # the reversal ledger is untouched


def test_load_of_a_momentum_path_reads_only_its_ledger_and_sectors(both, monkeypatch) -> None:
    read, original = [], statarb.io.pq.read_table
    monkeypatch.setattr(statarb.io.pq, "read_table", lambda path, *a, **k: read.append(path) or original(path, *a, **k))
    before = _tree(both)
    views.load(both, PATHS[-1])
    assert _tree(both) == before
    paper = momentum.paper_dir(both, momentum.load_momentum_config(both))
    assert {p.parent for p in read} == {paper / PATHS[-1] / "ledger", paper / "processed" / "2026-01-02"}


def test_load_refuses_a_ledger_the_checkout_does_not_configure(both) -> None:
    with pytest.raises(ValueError, match="no ledger 'momentum'"):
        views.load(both, "momentum")


def test_a_ledger_is_calibrated_when_it_records_a_slope(frame, momentum_frame) -> None:
    assert views.calibrated(frame)
    assert not views.calibrated(momentum_frame)
    assert views.calibrated(frame.assign(slope=np.where(frame[DATE] == DATES[0], np.nan, frame["slope"])))


def test_the_next_open_under_the_decile_sort_is_its_target(momentum_frame) -> None:
    """With no expected moves the names follow the target, largest first; a hedge's zero move does not keep a name
    the book neither holds nor targets, and a NaN move is never read as zero."""
    n = views.next_open(momentum_frame)
    last = momentum_frame.loc[momentum_frame[DATE] == DATES[-1]].set_index(TICKER)
    kept = last.loc[(last["holding"] != 0) | (last["target"] != 0)]
    assert set(n[TICKER]) == set(kept.index) and "DD" not in set(n[TICKER])
    assert list(n["target"]) == sorted(n["target"], reverse=True)
    stocks = n.loc[~n[TICKER].isin(HEDGES)]
    assert stocks["expected_move"].isna().all() and n["target"].notna().all()


def test_the_next_open_sorts_a_missing_move_last(frame) -> None:
    last = frame[DATE] == DATES[-1]
    gap = frame.assign(expected_move=np.where(last & (frame[TICKER] == "AA"), np.nan, frame["expected_move"]))
    n = views.next_open(gap)
    assert n[TICKER].iloc[-1] == "AA" and np.isnan(n["expected_move"].iloc[-1])
    assert list(n["expected_move"].iloc[:-1]) == sorted(n["expected_move"].iloc[:-1], reverse=True)


def test_the_views_carry_a_momentum_ledgers_missing_moves_and_slope_as_nan(momentum_frame) -> None:
    held = views.book(momentum_frame, SECTORS, DATES[3])
    assert held.loc[~held[TICKER].isin(HEDGES), "prior_expected_move"].isna().all()
    assert (held.loc[held[TICKER].isin(HEDGES), "prior_expected_move"] == 0).all()
    h = views.health(momentum_frame)
    assert h["slope"].isna().all() and (h["status"] == "").all()
    assert views.history(momentum_frame, "AA")["expected_move"].isna().all()
    assert views.pnl(momentum_frame)["net_usd"].notna().all()


def test_a_momentum_ledger_trades_and_earns_as_the_reversal_ledger_does(frame, momentum_frame) -> None:
    """The two variants share returns and holdings, so every view that reads neither moves nor slope agrees."""
    pd.testing.assert_frame_equal(views.trades(momentum_frame), views.trades(frame))
    pd.testing.assert_frame_equal(views.pnl(momentum_frame), views.pnl(frame))
    pd.testing.assert_frame_equal(views.spells(momentum_frame), views.spells(frame))
    pd.testing.assert_frame_equal(views.attribution(momentum_frame, SECTORS, "sector"), views.attribution(frame, SECTORS, "sector"))


RUN = Run(first_session=dt.date(2026, 11, 16), calendar="XNYS", run_time=dt.time(6, 0))


def _utc(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC)


def test_due_is_what_the_daily_job_would_process_now() -> None:
    last = pd.Timestamp("2026-11-17")
    assert list(views.due(RUN, last, _utc("2026-11-19T10:30"))) == []          # 05:30 New York: before the run time
    assert list(views.due(RUN, last, _utc("2026-11-19T12:00"))) == [pd.Timestamp("2026-11-18")]
    assert list(views.due(RUN, last, _utc("2026-11-23T12:00"))) == list(pd.to_datetime(["2026-11-18", "2026-11-19", "2026-11-20"]))


def test_due_knows_the_markets_holidays() -> None:
    """Thanksgiving, Thursday 2026-11-26, is a weekday with no session, so nothing is due the morning after."""
    assert list(views.due(RUN, pd.Timestamp("2026-11-25"), _utc("2026-11-27T12:00"))) == []


def test_due_is_unknown_without_a_configured_run() -> None:
    assert views.due(None, pd.Timestamp("2026-11-17"), _utc("2026-11-19T12:00")) is None
    assert views.due(Run(first_session="", calendar="XNYS", run_time=dt.time(6, 0)), None, _utc("2026-11-19T12:00")) is None


def test_sectors_follow_their_dates(frame) -> None:
    named = views.with_sector(frame, SECTORS).set_index([DATE, TICKER])["sector"]
    assert named[(DATES[2], "BB")] == "Tech"
    assert named[(CHANGE, "BB")] == "Energy"
    assert named[(DATES[0], "HX")] == views.NO_SECTOR
    assert len(named) == len(frame)


def test_between_includes_both_ends(frame) -> None:
    assert views.days(views.between(frame, DATES[1], DATES[3])) == list(DATES[1:4])
    assert views.days(views.between(frame, last=DATES[0])) == [DATES[0]]


def test_book_lists_the_names_held_after_the_open(frame) -> None:
    held = views.book(frame, SECTORS, DATES[3])
    day = frame.loc[(frame[DATE] == DATES[3]) & (frame["holding"] != 0)]
    assert set(held[TICKER]) == set(day[TICKER]) == {"BB", "CC", "HX"}
    assert list(held["holding"].abs()) == sorted(held["holding"].abs(), reverse=True)
    np.testing.assert_array_equal(held["holding_usd"], held["holding"] * BOOK_SIZE)
    assert dict(zip(held[TICKER], held["side"], strict=True)) == {"BB": "long", "CC": "long", "HX": "short"}
    assert dict(zip(held[TICKER], held["sector"], strict=True)) == {"BB": "Energy", "CC": "Health", "HX": views.NO_SECTOR}


def test_book_pairs_a_holding_with_the_move_it_was_decided_on(frame) -> None:
    held = views.book(frame, SECTORS, DATES[3])
    decided = frame.loc[frame[DATE] == DATES[2]].set_index(TICKER)["expected_move"]
    own = frame.loc[frame[DATE] == DATES[3]].set_index(TICKER)["expected_move"]
    np.testing.assert_array_equal(held["prior_expected_move"], decided.loc[list(held[TICKER])])
    assert not np.array_equal(held["prior_expected_move"], own.loc[list(held[TICKER])])   # not the next open's decision
    assert views.book(frame, SECTORS, DATES[0])["prior_expected_move"].isna().all()       # nothing was decided before day one


def test_exposure_and_sector_exposure_agree_with_the_book(frame) -> None:
    exp = views.exposure(frame)
    for day in DATES:
        h = frame.loc[frame[DATE] == day, "holding"]
        assert exp.loc[day, "gross"] == pytest.approx(h.abs().sum())
        assert exp.loc[day, "net"] == pytest.approx(h.sum())
        assert exp.loc[day, "names_long"] == (h > 0).sum() and exp.loc[day, "names_short"] == (h < 0).sum()
    by_sector = views.sector_exposure(views.book(frame, SECTORS, DATES[3]))
    assert by_sector["gross"].sum() == pytest.approx(exp.loc[DATES[3], "gross"])
    assert by_sector["names"].sum() == 3


def test_trades_name_each_kind(frame) -> None:
    t = views.trades(frame)
    got = {(d, k): a for d, k, a in zip(t[DATE], t[TICKER], t["action"], strict=True)}
    assert got == {
        (DATES[0], "AA"): "open", (DATES[0], "BB"): "open",
        (DATES[1], "CC"): "open", (DATES[1], "HX"): "open",
        (DATES[2], "AA"): "close", (DATES[2], "BB"): "flip",
        (DATES[3], "CC"): "add", (DATES[3], "HX"): "reduce",
        (DATES[4], "AA"): "open",
    }
    np.testing.assert_array_equal(t["trade"], t["holding"] - t["drifted"])
    np.testing.assert_array_equal(t["trade_usd"], t["trade"] * BOOK_SIZE)
    assert list(t[DATE]) == sorted(t[DATE], reverse=True)


def test_pnl_nets_as_the_daily_note_does(frame) -> None:
    p = views.pnl(frame)
    assert list(p.index) == list(DATES)
    costs = p[["cost_spread_usd", "cost_impact_usd", "cost_commission_usd"]].sum(axis=1)
    np.testing.assert_allclose(p["net_usd"], p["gross_usd"] - p["borrow_usd"] - costs)
    assert p["gross_usd"].sum() == pytest.approx(frame["pnl"].sum() * BOOK_SIZE)
    assert p["cumulative_net_usd"].iloc[-1] == pytest.approx(p["net_usd"].sum())
    assert p.loc[DATES[5], "turnover"] == 0.0 and p.loc[DATES[0], "turnover"] == pytest.approx(0.2)


@pytest.mark.parametrize("by", ["ticker", "sector", "side"])
def test_attribution_sums_to_the_ledger(frame, by) -> None:
    a = views.attribution(frame, SECTORS, by)
    assert a["pnl_usd"].sum() == pytest.approx(frame["pnl"].sum() * BOOK_SIZE)
    assert a["borrow_usd"].sum() == pytest.approx(frame["borrow"].sum() * BOOK_SIZE)
    assert list(a["net_usd"].abs()) == sorted(a["net_usd"].abs(), reverse=True)


def test_attribution_by_side_follows_the_holding_carried_in(frame) -> None:
    a = views.attribution(frame, SECTORS, "side")
    shorts = frame.loc[frame["held"] < 0]
    assert a.loc["short", "pnl_usd"] == pytest.approx(shorts["pnl"].sum() * BOOK_SIZE)
    assert a.loc["short", "borrow_usd"] == pytest.approx(shorts["borrow"].sum() * BOOK_SIZE)


def test_next_open_shows_the_latest_decision(frame) -> None:
    n = views.next_open(frame)
    last = frame.loc[frame[DATE] == DATES[-1]]
    assert set(n[TICKER]) == set(last[TICKER])
    assert n["target"].isna().all()
    assert list(n["expected_move"]) == sorted(n["expected_move"], reverse=True)


def test_history_is_one_name_by_day(frame) -> None:
    h = views.history(frame, "DD")
    assert list(h[DATE]) == list(DATES[3:])
    assert (h["held"] == 0).all()


def test_spells_run_from_entry_to_exit(frame) -> None:
    s = views.spells(frame)
    got = {(k, side, e): (x if pd.notna(x) else None, n) for k, side, e, x, n in zip(s[TICKER], s["side"], s["entry"], s["exit"], s["days"], strict=True)}
    assert got == {
        ("AA", "long", DATES[0]): (DATES[2], 2),
        ("AA", "long", DATES[4]): (None, 2),
        ("BB", "short", DATES[0]): (DATES[2], 2),
        ("BB", "long", DATES[2]): (None, 4),
        ("CC", "long", DATES[1]): (None, 5),
        ("HX", "short", DATES[1]): (None, 5),
    }
    assert s["pnl_usd"].sum() == pytest.approx(frame["pnl"].sum() * BOOK_SIZE)
    assert s["borrow_usd"].sum() == pytest.approx(frame["borrow"].sum() * BOOK_SIZE)
    bb_short = frame.loc[(frame[TICKER] == "BB") & (frame[DATE].isin(DATES[1:3])), "pnl"].sum() * BOOK_SIZE
    assert s.loc[(s[TICKER] == "BB") & (s["side"] == "short"), "pnl_usd"].item() == pytest.approx(bb_short)


def test_health_counts_the_grid_and_the_names_held(frame) -> None:
    h = views.health(frame)
    assert list(h["names"]) == [4, 4, 4, 5, 5, 5]
    assert list(h["held"]) == [0, 2, 4, 3, 3, 4]
    assert (h["status"] == "optimal").all() and not h["git_dirty"].any()

