"""Phase 6 ledger: the engine one day at a time, carried through files, and the checks on them."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from statarb.backtest import engine
from statarb.backtest.costs import CommissionSchedule, NoTradeZone, TradingCost
from statarb.config import repo_root
from statarb.paper import ledger
from statarb.paper.loop import live_step

T, N = 40, 8
TICKERS = ("HH", "BB", "AA", "GG", "CC", "FF", "EE", "DD")   # not sorted: the grid's order is not the file's
META = ledger.DayMeta(book_size=5e6, config_hash="0123456789abcdef", git_commit="deadbeef", git_dirty=False, snapshot="2026-11-14")


def _world(seed: int = 0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2026-01-05", periods=T)
    returns = rng.normal(0.0, 0.01, (T, N))
    returns[rng.random((T, N)) < 0.05] = np.nan
    tradable = rng.random((T, N)) > 0.05
    grid = engine.Grid("open", dates, TICKERS, returns, tradable)
    targets = rng.normal(0.0, 0.05, (T, N))
    targets[:3] = np.nan                                   # paths start flat
    targets[rng.random((T, N)) < 0.05] = np.nan            # "keep the drifted holding"
    moves = rng.normal(0.0, 0.003, (T, N))
    borrow = rng.uniform(0.005, 0.05, (T, N))
    cost = TradingCost(
        half_spread=np.full((T, N), 1.5e-4),
        volatility=rng.uniform(0.01, 0.03, (T, N)),
        dollar_volume=rng.uniform(1e7, 1e9, (T, N)),
        fill_price=rng.uniform(20, 200, (T, N)),
        book_size=META.book_size,
        impact_coefficient=1.0,
        commission=CommissionSchedule("fixed", 0.005, 1.0, 0.01),
    )
    zone = NoTradeZone(moves, cost, decision_price=rng.uniform(20, 200, (T, N)), delay=1)
    return grid, targets, moves, borrow, zone


def _forward(root, grid, targets, moves, borrow, zone):
    """Run the grid one ledger day at a time; the zone's own expected-move panel is blanked, so only the ledger can supply it."""
    rates = engine.daily_rates(borrow, (T, N))
    blank = None if zone is None else NoTradeZone(np.zeros_like(zone.expected_move), zone.cost, zone.decision_price, zone.delay)
    carry = ledger.Carry.flat(grid.tickers)
    for s, day in enumerate(grid.dates):
        carry = carry.on(grid.tickers)
        out = live_step(s, carry, grid.returns[s], grid.tradable[s], rates[s], blank)
        ledger.write_day(root, ledger.day_frame(day, grid.tickers, carry.holdings, out, targets[s], moves[s], META))
        carry = ledger.carry_of(ledger.read_day(root, day))


def _first_frame(grid, targets, moves, borrow) -> pd.DataFrame:
    out = engine.step(0, np.zeros(N), grid.returns[0], grid.tradable[0], targets[0], engine.daily_rates(borrow, (T, N))[0])
    return ledger.day_frame(grid.dates[0], TICKERS, np.zeros(N), out, targets[0], moves[0], META)


@pytest.mark.parametrize("with_zone", [True, False])
def test_the_ledger_reproduces_the_engine_exactly(tmp_path, with_zone) -> None:
    grid, targets, moves, borrow, zone = _world()
    zone = zone if with_zone else None
    expected = engine.run(targets, grid, 1, borrow, zone)
    _forward(tmp_path, grid, targets, moves, borrow, zone)

    days = ledger.dates(tmp_path)
    assert days == list(grid.dates)
    order = [TICKERS.index(t) for t in sorted(TICKERS)]
    for s, day in enumerate(days):
        frame = ledger.read_day(tmp_path, day)
        assert tuple(frame["ticker"]) == tuple(sorted(TICKERS))
        np.testing.assert_array_equal(frame["holding"], expected.holdings[s, order])
        np.testing.assert_array_equal(frame["trade"], expected.trades[s, order])
        np.testing.assert_array_equal(frame["pnl"], expected.pnl[s, order])
        assert frame["borrow"].sum() == pytest.approx(expected.borrow[s], rel=1e-15, abs=0)
    assert sum(int(ledger.read_day(tmp_path, d)["missing_returns"].iloc[0]) for d in days) == expected.missing_returns
    assert ledger.check(tmp_path) == []
    if with_zone:                                         # the zone did skip trades, so the test means something
        assert not np.array_equal(expected.holdings, engine.run(targets, grid, 1, borrow).holdings)


def test_day_frame_types_and_meta(tmp_path) -> None:
    grid, targets, moves, borrow, _ = _world()
    path = ledger.write_day(tmp_path, _first_frame(grid, targets, moves, borrow))
    frame = ledger.read_day(tmp_path, grid.dates[0])
    assert path.name == "date=2026-01-05.parquet"
    assert frame["date"].dtype == "datetime64[ns]"
    assert frame.loc[0, "config_hash"] == META.config_hash and frame.loc[0, "snapshot"] == "2026-11-14"
    assert not frame.loc[0, "git_dirty"]
    assert frame.loc[0, "status"] == ""


def test_carry_moves_to_a_new_grid() -> None:
    carry = ledger.Carry(("A", "B", "C"), np.array([0.1, 0.0, -0.2]), np.array([0.2, 0.3, np.nan]), np.array([1.0, 2.0, 3.0]))
    on = carry.on(("C", "D", "A"))
    np.testing.assert_array_equal(on.holdings, [-0.2, 0.0, 0.1])
    np.testing.assert_array_equal(on.target, [np.nan, np.nan, 0.2])
    np.testing.assert_array_equal(on.expected_move, [3.0, np.nan, 1.0])
    carry.on(("A", "C"))                                   # B was flat: dropping it is fine
    empty = ledger.Carry.flat(()).on(("A", "B"))             # before the first day
    np.testing.assert_array_equal(empty.holdings, [0.0, 0.0])
    assert np.isnan(empty.target).all()
    with pytest.raises(ValueError, match="C"):
        carry.on(("A", "B"))                               # C was held


def test_integrity_check_finds_a_broken_chain(tmp_path) -> None:
    grid, targets, moves, borrow, zone = _world()
    _forward(tmp_path, grid, targets, moves, borrow, zone)
    day = grid.dates[10]
    frame = ledger.read_day(tmp_path, day)
    frame.loc[2, "held"] += 1e-12
    frame.loc[2, "pnl"] = frame.loc[2, "held"] * frame.loc[2, "ret"]
    frame.loc[2, "drifted"] = frame.loc[2, "held"] * (1.0 + frame.loc[2, "ret"])
    ledger.write_day(tmp_path, frame)
    assert ledger.check(tmp_path) == [f"{day:%Y-%m-%d}: held is not the previous day's holding"]


def test_integrity_check_finds_holdings_on_the_first_day_and_mixed_meta(tmp_path) -> None:
    grid, targets, moves, borrow, zone = _world()
    _forward(tmp_path, grid, targets, moves, borrow, zone)
    first = ledger.read_day(tmp_path, grid.dates[0])
    first.loc[0, "held"] = 0.1
    first.loc[1, "config_hash"] = "something else"
    first.loc[2, "status"] = "solver_error"
    problems = ledger.check_day(first, None)
    assert "the first day carries holdings in" in problems
    assert "config_hash differs between rows" in problems
    assert "status differs between rows" in problems
    assert "pnl is not held times ret" in problems


def test_a_crash_mid_write_leaves_no_ledger_day(tmp_path, monkeypatch) -> None:
    grid, targets, moves, borrow, _ = _world()
    frame = _first_frame(grid, targets, moves, borrow)

    def crash(table, where, **kwargs):
        with open(where, "wb") as fh:
            fh.write(b"PAR1 half a file")
        raise OSError("disk went away")

    monkeypatch.setattr(pq, "write_table", crash)
    with pytest.raises(OSError):
        ledger.write_day(tmp_path, frame)
    assert [p.name for p in tmp_path.iterdir()] == ["date=2026-01-05.parquet.tmp"]
    assert ledger.dates(tmp_path) == []
    assert ledger.check(tmp_path) == []


def test_a_file_holds_one_day(tmp_path) -> None:
    grid, targets, moves, borrow, _ = _world()
    frame = _first_frame(grid, targets, moves, borrow)
    frame.loc[0, "date"] = grid.dates[1]
    with pytest.raises(ValueError, match="one day"):
        ledger.write_day(tmp_path, frame)


def test_rewriting_a_day_gives_the_same_bytes(tmp_path) -> None:
    grid, targets, moves, borrow, _ = _world()
    frame = _first_frame(grid, targets, moves, borrow)
    path = ledger.write_day(tmp_path, frame)
    before = path.read_bytes()
    ledger.write_day(tmp_path, frame)
    assert path.read_bytes() == before


def test_data_model_documents_the_ledger_file(tmp_path) -> None:
    grid, targets, moves, borrow, _ = _world()
    path = ledger.write_day(tmp_path, _first_frame(grid, targets, moves, borrow))
    schema = pq.read_schema(path)
    written = [(n, "string" if str(t) == "large_string" else str(t)) for n, t in zip(schema.names, schema.types, strict=True)]

    lines = (repo_root() / "docs" / "data-model.md").read_text().splitlines()
    start = lines.index("### `data/paper/ledger/date=YYYY-MM-DD.parquet`")
    row = re.compile(r"^\| `?(?P<col>[a-z_]+)`? \| (?P<type>[a-z_\[\]0-9]+) \| .* \|$")
    documented = []
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            break
        if (m := row.match(line)) and m["col"] != "column":
            documented.append((m["col"], m["type"]))
    assert documented == written
