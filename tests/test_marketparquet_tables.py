"""Tests for this source's tables and its universe. Synthetic bars only."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from statarb.data import marketparquet as mp
from statarb.data import marketparquet_tables as mt

CAL = pd.bdate_range("2025-10-01", periods=90)
RANKING = {"size": 3, "liquidity_window_days": 20, "liquidity_min_observations": 15}
DEAD = f"DDD{mp.SUFFIX}"
# Dollar volume falls down the list, so the first three are the universe until LATE overtakes them.
STOCKS = {"AAA": 9e6, DEAD: 8e6, "BRK.B": 7e6, "EEE": 2e6, "FFFFW": 1e6}


def bars(volumes: dict[str, float], seed: int = 0, late: float | None = None) -> pd.DataFrame:
    """Random-walk bars; `late` adds LATE, the heaviest name, from the calendar's midpoint."""
    rng = np.random.default_rng(seed)
    rows = []
    for ticker, volume in {**volumes, **({"LATE": late} if late else {})}.items():
        close = 50 * np.cumprod(1 + rng.normal(0, 0.01, len(CAL)))
        for t, day in enumerate(CAL):
            if ticker == "LATE" and t < len(CAL) // 2:
                continue
            rows.append((day, ticker, close[t] * 0.999, close[t] * 1.01, close[t] * 0.99, close[t], volume / close[t]))
    return pd.DataFrame(rows, columns=mt.BAR)


def etf_bars() -> pd.DataFrame:
    return bars({"SPY": 5e9, "XLK": 1e9}, seed=1)


def tables(stocks: pd.DataFrame) -> mt.SourceTables:
    return mt.build_tables(stocks, etf_bars(), "SPY", RANKING)


def test_the_rules_drop_bars_with_no_volume_and_bars_that_contradict_themselves() -> None:
    day = CAL[0]
    frame = pd.DataFrame(
        [
            (day, "GOOD", 10.0, 11.0, 9.0, 10.5, 100.0),
            (day, "ZERO", 10.0, 11.0, 9.0, 10.5, 0.0),
            (day, "NOVOL", 10.0, 11.0, 9.0, 10.5, float("nan")),
            (day, "OPEN", 12.0, 11.0, 9.0, 10.5, 100.0),
            (day, "CLOSE", 10.0, 11.0, 9.0, 8.0, 100.0),
            (day, "RANGE", 10.0, 9.0, 11.0, 10.0, 100.0),
            (day, "NONE", float("nan"), 11.0, 9.0, 10.0, 100.0),
            (day, "NEG", 10.0, 11.0, -1.0, 10.0, 100.0),
            (day, "BOTH", 12.0, 11.0, 9.0, 10.5, 0.0),
            (pd.Timestamp("2025-10-04"), "SAT", 10.0, 11.0, 9.0, 10.5, 100.0),
        ],
        columns=mt.BAR,
    )
    kept, log = mt.apply_rules(frame, CAL)
    assert kept["ticker"].tolist() == ["GOOD"] and list(kept.columns) == mt.BAR
    assert log.set_index("ticker")["reason"].to_dict() == {
        "ZERO": mt.ZERO_VOLUME, "NOVOL": mt.ZERO_VOLUME, "BOTH": mt.ZERO_VOLUME, "SAT": mt.NOT_A_SESSION,
        **dict.fromkeys(["OPEN", "CLOSE", "RANGE", "NONE", "NEG"], mt.CONTRADICTS),
    }
    assert mt.drops_by_year(log).iloc[0].to_dict() == {"year": 2025, "not_a_trading_day": 1, "zero_volume": 3, "contradicts_itself": 5}


def test_returns_are_price_returns_from_the_previous_bar() -> None:
    frame = bars({"AAA": 1e6})
    gapped = frame.drop(index=frame.index[5])
    got = mt.price_returns(gapped)
    assert (got["split_ratio"] == 1.0).all() and (got["cash"] == 0.0).all() and len(got) == len(gapped) - 1
    after = got.loc[got["date"] == CAL[6]].iloc[0]
    assert after["prev_date"] == CAL[4]
    assert after["ret"] == pytest.approx(frame["close"].iloc[6] / frame["close"].iloc[4] - 1)


def test_shape_describes_the_symbol_with_the_suffix_aside() -> None:
    assert [mt.shape(s) for s in ["A", "ABCD", f"ABCD{mp.SUFFIX}", "GOOGL", f"FFFFW{mp.SUFFIX}", "BRK.B", "C.PRN", "AB1"]] == [
        mt.SHAPES[0], mt.SHAPES[0], mt.SHAPES[0], mt.SHAPES[1], mt.SHAPES[1], mt.SHAPES[2], mt.SHAPES[2], mt.SHAPES[3],
    ]


def test_every_stock_symbol_is_ranked_and_no_etf_is() -> None:
    built = tables(bars(STOCKS))
    assert set(built.universe["ticker"]) == {"AAA", DEAD, "BRK.B"}
    assert built.calendar.equals(CAL) and set(built.prices["ticker"]) == {*STOCKS, "SPY", "XLK"}
    assert built.universe["date"].min() == CAL[CAL.get_loc(built.universe["rebalanced_on"].min()) + 1]
    with pytest.raises(ValueError, match="both datasets"):
        mt.build_tables(bars({**STOCKS, "XLK": 1e6}), etf_bars(), "SPY", RANKING)
    with pytest.raises(ValueError, match="no bars for the market"):
        mt.build_tables(bars(STOCKS), etf_bars(), "QQQ", RANKING)


def test_a_dropped_bar_is_a_day_without_one() -> None:
    frame = bars(STOCKS)
    hit = (frame["ticker"] == "AAA") & (frame["date"] == CAL[10])
    built = tables(frame.assign(volume=frame["volume"].where(~hit, 0.0)))
    assert len(built.drops) == 1 and built.drops["reason"].item() == mt.ZERO_VOLUME
    assert not ((built.prices["ticker"] == "AAA") & (built.prices["date"] == CAL[10])).any()
    after = built.returns.loc[(built.returns["ticker"] == "AAA") & (built.returns["date"] == CAL[11])]
    assert after["prev_date"].item() == CAL[9]


def test_the_suffix_decides_nothing_in_the_universe() -> None:
    """Decision record 0008, point 8: with every suffix replaced by a label that means nothing, the same
    securities are members on the same days."""
    frame = bars(STOCKS, late=2e7)
    relabelled = frame.assign(ticker=frame["ticker"].str.replace(mp.SUFFIX, "~7", regex=False))
    plain, other = tables(frame), tables(relabelled)
    back = other.universe.assign(ticker=other.universe["ticker"].str.replace("~7", mp.SUFFIX, regex=False))
    key = ["date", "ticker"]
    pd.testing.assert_frame_equal(
        plain.universe.sort_values(key).reset_index(drop=True), back.sort_values(key).reset_index(drop=True)
    )
    assert DEAD in set(plain.universe["ticker"])


def test_universe_membership_has_no_look_ahead() -> None:
    frame = bars(STOCKS, late=2e7)
    cut = CAL[55]
    noise = np.random.default_rng(9).uniform(0.2, 5.0, len(frame))
    later = frame["date"] > cut
    shaken = frame.assign(
        **{c: frame[c].where(~later, frame[c] * noise) for c in ["open", "high", "low", "close"]},
        volume=frame["volume"].where(~later, frame["volume"] * noise[::-1]),
    )
    a, b = tables(frame).universe, tables(shaken).universe
    decided = a["rebalanced_on"] <= cut
    assert decided.any() and (~decided).any()
    pd.testing.assert_frame_equal(
        a.loc[decided].reset_index(drop=True), b.loc[b["rebalanced_on"] <= cut].reset_index(drop=True)
    )
    assert "LATE" in set(a["ticker"]) and "LATE" not in set(a.loc[a["rebalanced_on"] <= CAL[len(CAL) // 2 + 10], "ticker"])


def test_near_copies_are_pairs_of_members_and_read_nothing_after_the_month_end() -> None:
    frame = bars(STOCKS)
    twin = frame.loc[frame["ticker"] == "AAA"].assign(ticker="AAB")
    twin = twin.assign(**{c: twin[c] * 2 for c in ["open", "high", "low", "close"]}, volume=twin["volume"] / 2 * 0.99)
    built = mt.build_tables(pd.concat([frame, twin], ignore_index=True), etf_bars(), "SPY", RANKING)
    args = (built.calendar, RANKING["liquidity_window_days"], RANKING["liquidity_min_observations"], 0.98)
    copies = mt.near_copies(built.universe, built.returns, *args)
    assert (copies["pairs"] == 1).all() and (copies["members"] == 2).all()
    first = copies["rebalanced_on"].min()
    changed = built.returns.assign(ret=built.returns["ret"].where(built.returns["date"] <= first, 0.5))
    assert mt.near_copies(built.universe, changed, *args).iloc[0].equals(copies.iloc[0])
    by_year = mt.near_copies_by_year(copies)
    assert by_year["mean_pairs"].tolist() == ["1.00"] * len(by_year) and by_year["most_pairs"].eq(1).all()


def test_members_by_year_counts_shapes_and_the_suffix() -> None:
    built = tables(bars(STOCKS))
    got = mt.members_by_year(built.universe).iloc[0]
    assert got["symbols"] == 3 and got["one_to_four_letters"] == "66.67%" and got["a_letter_after_a_dot"] == "33.33%"
    assert got["suffixed"] == "33.33%"


def test_overlap_is_the_share_of_the_other_universes_member_days_found_here() -> None:
    built = tables(bars(STOCKS))
    other = built.universe.assign(ticker=built.universe["ticker"].replace({"BRK.B": "ZZZ"}))
    got = mt.overlap_by_year(built.universe, other)
    assert set(got["also_here"]) == {"66.67%"} and got["member_days"].sum() == len(other)


def test_the_report_is_the_same_on_a_second_build() -> None:
    def text() -> str:
        return mt.universe_report(
            tables(bars(STOCKS, late=2e7)), "listed", "2026-01-01", "0" * 64, dt.date(2025, 10, 1), dt.date(2026, 2, 4), RANKING, 0.98, None,
        )

    first = text()
    assert first == text() and "# Phase 7 universe report: `listed`" in first and "## Against the existing universe" not in first
