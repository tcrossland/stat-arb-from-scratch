"""The auction counts and their report (docs/plans/auction-closes.md), on synthetic prints and bars."""

from __future__ import annotations

import dataclasses
import datetime as dt

import pandas as pd
import pytest

from auction_helpers import auction_day, bar_snapshot, fake_auctions
from statarb.config import RAW_ENV, load_config, repo_root
from statarb.data import auction_counts, auctions, cache
from statarb.data.auction_counts import ETF, STOCK, count_tables, render, ticker_days
from statarb.data.auction_report import report
from statarb.data.listings import intervals, parse_listings

ROOT = repo_root()
TOL = 0.00005
D = pd.bdate_range("2026-11-02", periods=4)


def bars(closes: list[float], opens: list[float] | None = None, dates=D) -> pd.DataFrame:
    opens = opens or [c - 1 for c in closes]
    return pd.DataFrame({"date": dates[: len(closes)], "open": opens, "close": closes})


def prints_of(days: list[dict]) -> pd.DataFrame:
    return auctions.prints([{"auctions": {"AAA": days}}], "AAA")


def codes(value: str | None, n: int) -> pd.Series:
    return pd.Series([value] * n, dtype="object")


def tables_for(days: pd.DataFrame, kind: str = STOCK, ticker: str = "AAA") -> auction_counts.Tables:
    return count_tables(days.assign(ticker=ticker, kind=kind), TOL)


def count(t: auction_counts.Tables, price: str, kind: str = STOCK) -> dict:
    row = t.counts.loc[(t.counts["price"] == price) & (t.counts["kind"] == kind)].iloc[0]
    return {"compared": row["compared"], "differ": row["differ"], "median_bp": row["median_bp"]}


def test_each_auction_price_is_compared_with_the_bar() -> None:
    p = prints_of([
        auction_day(D[0], opens=[("Q", "O", 10.0, 500.0), ("Q", "Q", 10.0, None)],
                    closes=[("Q", "6", 11.0, 900.0), ("Q", "M", 11.0, None), ("P", "6", 11.2, 100.0), ("P", "M", 11.2, None)]),
        auction_day(D[1], opens=[("Q", "O", 11.0, 400.0)], closes=[("Q", "6", 12.06, 900.0), ("Q", "M", 12.06, None)]),
    ])
    days = ticker_days(p, bars([11.0, 12.0, 13.0], [10.0, 11.0, 12.0]), codes("Q", 3))
    assert list(days["any_auction"]) == [True, True, False]
    assert list(days["close_cross"].fillna(-1)) == [11.0, 12.06, -1]
    assert list(days["m_listing"]) == [True, True, False] and list(days["m_other"]) == [True, False, False]
    assert days["largest"].iloc[0] == "Q" and pd.isna(days["official_open"].iloc[1])
    t = tables_for(days)
    assert count(t, "close_cross") == {"compared": 2, "differ": 1, "median_bp": pytest.approx(50.0)}
    assert count(t, "official_open")["compared"] == 1 and count(t, "official_open")["differ"] == 0
    cond = t.conditions.iloc[0]
    assert cond["m_listing"] == 1.0 and cond["m_other"] == 0.5 and cond["largest_is_listing"] == 1.0


def test_a_difference_within_the_tolerance_is_not_counted() -> None:
    p = prints_of([auction_day(D[0], [], [("N", "6", 20.00004, None)]), auction_day(D[1], [], [("N", "6", 20.0001, None)])])
    t = tables_for(ticker_days(p, bars([20.0, 20.0]), codes("N", 2)))
    assert count(t, "close_cross")["differ"] == 1


def test_only_the_listing_exchanges_prints_count_and_a_transfer_moves_it() -> None:
    p = prints_of([
        auction_day(D[0], [], [("Q", "6", 30.5, 900.0), ("N", "6", 30.0, 10.0)]),
        auction_day(D[1], [], [("Q", "6", 31.0, 10.0), ("N", "6", 31.5, 900.0)]),
    ])
    held = pd.Series(["Q", "N"], dtype="object")
    days = ticker_days(p, bars([30.5, 31.5]), held)
    assert list(days["close_cross"]) == [30.5, 31.5]
    assert list(days["largest"]) == ["Q", "N"]
    assert tables_for(days).listing_check.empty
    unknown = ticker_days(p, bars([30.5, 31.5]), codes(None, 2))
    assert unknown["close_cross"].isna().all() and not unknown["listing_close"].any()
    assert tables_for(unknown).coverage["no_listing_days"].iloc[0] == 2


def test_the_listing_check_flags_a_ticker_whose_largest_close_is_elsewhere() -> None:
    p = prints_of([auction_day(d, [], [("Q", "6", 5.0, 10.0), ("P", "6", 5.0, 900.0)]) for d in D[:3]]
                  + [auction_day(D[3], [], [("Q", "6", 5.0, 50.0), ("P", "6", 5.0, 50.0)])])
    days = ticker_days(p, bars([5.0] * 4), codes("Q", 4))
    assert list(days["largest_tie"]) == [False, False, False, True]
    check = tables_for(days).listing_check
    assert check.to_dict("records") == [{"year": 2026, "ticker": "AAA", "days": 3, "mismatched": 3, "share": 1.0, "venue": "P"}]
    assert len(auction_counts.flagged(check, 0.5)) == 1 and auction_counts.flagged(check.assign(share=0.4), 0.5).empty


def test_stocks_and_etfs_are_counted_apart() -> None:
    p = prints_of([auction_day(D[0], [], [("P", "6", 7.0, 1.0)])])
    stock = ticker_days(p, bars([7.0]), codes("P", 1)).assign(ticker="AAA", kind=STOCK)
    etf = ticker_days(p, bars([7.5]), codes("P", 1)).assign(ticker="SPY", kind=ETF)
    t = count_tables(pd.concat([stock, etf], ignore_index=True), TOL)
    assert count(t, "close_cross", STOCK)["differ"] == 0 and count(t, "close_cross", ETF)["differ"] == 1
    assert sorted(t.coverage["kind"]) == [ETF, STOCK]


def test_the_report_holds_no_price() -> None:
    p = prints_of([auction_day(D[0], [("Q", "O", 37.913, 3.0)], [("Q", "6", 41.287, 9.0), ("Q", "M", 41.287, None)])])
    days = ticker_days(p, bars([41.251], [37.877]), codes("Q", 1))
    text = render(tables_for(days), {"Run": "synthetic"}, 0.5, {"nasdaq": "Q"})
    for value in ("37.9", "41.2", "37.8", "3.0", "9.0"):
        assert value not in text
    assert "## Listing check" in text and "Official close (`M`)" in text and "nasdaq `Q`" in text


@pytest.fixture
def snapshots(tmp_path, monkeypatch):
    """A raw bar snapshot and an auction snapshot of a stock and an ETF, and the configs that pin them."""
    monkeypatch.delenv(RAW_ENV, raising=False)
    raw = tmp_path / "raw"
    dates = pd.bdate_range("2026-11-02", "2026-11-13")
    closes = [73.17 + i for i in range(len(dates))]
    b = bar_snapshot(raw, dt.date(2026, 11, 16), {"AAA": bars(closes, dates=dates), "SPY": bars(closes, dates=dates)})
    days = {t: [auction_day(d, [(x, "O", c - 1, 5.0)], [(x, "6", c + (0.01 if i % 2 else 0.0), 9.0), (x, "M", c, None)])
                for i, (d, c) in enumerate(zip(dates, closes, strict=True))] for t, x in (("AAA", "Q"), ("SPY", "P"))}
    s = dataclasses.replace(auctions.parse_settings(load_config("auctions", ROOT), dt.date(2026, 11, 16)), start=dt.date(2026, 11, 2))
    a = auctions.download(fake_auctions(days, page_size=5), raw, ["AAA", "SPY"], s, dt.date(2026, 11, 27), "alpaca/2026-11-16",
                          sleep=lambda x: None)
    data_cfg = load_config("data", ROOT)
    data_cfg = {**data_cfg, "paths": {**data_cfg["paths"], "raw": str(raw)},
                "source": {**data_cfg["source"], "snapshot": "2026-11-16", "digest": cache.read_manifest(b)["digest"]}}
    s = dataclasses.replace(s, snapshot="2026-11-27", digest=cache.read_manifest(a)["digest"])
    table = intervals(parse_listings({"current": {"nasdaq": ["AAA"], "arca": ["SPY"]}}))
    return tmp_path, data_cfg, s, table


def test_the_report_runs_end_to_end_on_pinned_snapshots(snapshots) -> None:
    root, data_cfg, s, table = snapshots
    text = report(root, load_config("auctions", ROOT), data_cfg, s, table)
    assert "2026-11-27, digest" in text and "2026-11-16, digest" in text and "2026-11-02 to 2026-11-13" in text
    close = [line for line in text.splitlines() if line.startswith("| 2026 | stocks | 10 | 5 |")]
    assert close, "half the stock's closing crosses differ from the bar"
    assert "| 2026 | ETFs |" in text and "No ticker-year is flagged." in text
    assert "73.17" not in text and "74.17" not in text
    assert "- Left out: none" in text


def test_a_ticker_left_out_is_not_compared(snapshots) -> None:
    root, data_cfg, s, table = snapshots
    text = report(root, load_config("auctions", ROOT), data_cfg, s, table, {"SPY": "listing not settled"})
    assert "Tickers compared: 1;" in text and "- Left out: SPY (listing not settled)" in text and "| 2026 | ETFs |" not in text


def test_a_listing_start_cuts_the_bars_before_it(snapshots) -> None:
    root, data_cfg, s, table = snapshots
    text = report(root, load_config("auctions", ROOT), data_cfg, s, table, None, {"AAA": pd.Timestamp("2026-11-09")})
    assert [line for line in text.splitlines() if line.startswith("| 2026 | stocks | 5 | 5 |")]


def test_the_report_refuses_an_unpinned_or_mismatched_snapshot(snapshots) -> None:
    root, data_cfg, s, table = snapshots
    cfg = load_config("auctions", ROOT)
    with pytest.raises(ValueError, match="pin the auction snapshot"):
        report(root, cfg, data_cfg, dataclasses.replace(s, digest=""), table)
    with pytest.raises(ValueError, match="start is 2026-11-02"):
        report(root, cfg, data_cfg, dataclasses.replace(s, start=dt.date(2016, 1, 1)), table)
    with pytest.raises(cache.SnapshotDigestError):
        report(root, cfg, data_cfg, dataclasses.replace(s, digest="0" * 64), table)
