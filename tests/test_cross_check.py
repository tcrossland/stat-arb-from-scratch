"""Tests for the comparison of two price sources and the headline rebuilt on the second. Synthetic data only."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from helpers import MARKET_CAL, MARKET_ETFS, synthetic_market
from portfolio_helpers import backtest_config
from statarb.backtest import experiments, source_check
from statarb.backtest.sweep import record
from statarb.config import load_config
from statarb.data import cross_check as cc
from statarb.data import marketparquet as mp
from statarb.data.returns import total_returns
from statarb.factors.build import build_residuals

DAYS = pd.bdate_range("2025-12-29", periods=6)
FACTORS = {
    "model": {"window_days": 60, "min_observations": 45, "sector_factor": "excess"},
    "events": {"lookback_days": 20, "volume_ratio": 3.0},
    "sector_etfs": MARKET_ETFS,
}


def bars(closes: dict[str, list[float | None]], volume: float = 100.0) -> pd.DataFrame:
    """Flat bars, one per ticker and day with a close."""
    rows = [(day, ticker, c, c, c, c, volume) for ticker, series in closes.items() for day, c in zip(DAYS, series, strict=False) if c is not None]
    return pd.DataFrame(rows, columns=["date", "ticker", "open", "high", "low", "close", "volume"])


def actions(rows: list[tuple[int, str, float, float]]) -> pd.DataFrame:
    frame = pd.DataFrame([(DAYS[i], t, s, c) for i, t, s, c in rows], columns=["date", "ticker", "split_ratio", "cash"])
    return frame.astype({"date": "datetime64[ns]", "split_ratio": "float64", "cash": "float64"})


def with_actions(prices: pd.DataFrame, acts: pd.DataFrame) -> pd.DataFrame:
    merged = prices.merge(acts, on=["date", "ticker"], how="left").fillna({"split_ratio": 1.0, "cash": 0.0})
    return total_returns(merged)


def test_the_download_basis_divides_by_later_splits_only() -> None:
    prices = bars({"AAA": [100.0, 100.0, 50.0, 50.0, 25.0, 25.0], "BBB": [10.0] * 6})
    got = cc.on_download_basis(prices, actions([(2, "AAA", 2.0, 0.0), (4, "AAA", 2.0, 0.0)]))
    a = got.loc[got["ticker"] == "AAA"]
    assert a["close"].tolist() == [25.0] * 6 and a["volume"].tolist() == [400.0, 400.0, 200.0, 200.0, 100.0, 100.0]
    assert got.loc[got["ticker"] == "BBB", "close"].tolist() == [10.0] * 6


def test_pairs_keep_the_rows_of_either_source_and_say_which_holds_each() -> None:
    first = bars({"AAA": [10.0, 10.0, 10.0], "BBB": [5.0, 5.0, 5.0]})
    second = bars({"AAA": [None, 10.0, 10.0, 10.0], "BBB": [5.0, 5.0, 5.0]})
    pairs = cc.paired(first, second)
    assert pairs["held"].value_counts().to_dict() == {"both": 5, "first": 1, "second": 1}
    alone = cc.one_sided(pairs)
    assert alone[["ticker", "held", "rows"]].to_dict("list") == {"ticker": ["AAA", "AAA"], "held": ["first", "second"], "rows": [1, 1]}
    assert alone.loc[alone["held"] == "second", "first"].item() == DAYS[3]


def test_agreement_is_relative_and_by_year() -> None:
    first = bars({"AAA": [100.0, 100.0, 100.0, 100.0]})
    second = bars({"AAA": [100.0, 100.005, 100.02, 100.0]}, volume=95.0)
    got = cc.agreement_by_year(cc.paired(first, second), 1e-4, 0.01)
    assert got["year"].tolist() == [2025, 2026] and got["symbol_days"].tolist() == [3, 1]
    assert got["closes_agree"].tolist() == ["66.667%", "100.000%"] and got["volumes_agree"].tolist() == ["0.000%", "0.000%"]
    assert got["median_volume_ratio"].tolist() == [0.95, 0.95]


def sources() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Alpaca-like unadjusted prices with their returns, and a second source on the download's basis:
    SPLIT splits two for one, DIV pays a small dividend the second lacks, SPIN spins off a tenth, which the
    second folds into its adjustment, and ODD has one close the second prints differently."""
    prices = bars({
        "SPLIT": [100.0, 102.0, 51.0, 52.0, 52.0, 53.0],
        "DIV": [50.0, 50.0, 49.5, 50.0, 50.0, 50.0],
        "SPIN": [100.0, 100.0, 90.0, 90.0, 91.0, 91.0],
        "ODD": [20.0, 20.0, 20.0, 20.0, 20.0, 20.0],
    })
    acts = actions([(2, "SPLIT", 2.0, 0.0), (2, "DIV", 1.0, 0.5), (2, "SPIN", 1.0, 10.0)])
    second = bars({
        "SPLIT": [50.0, 51.0, 51.0, 52.0, 52.0, 53.0],
        "DIV": [50.0, 50.0, 49.5, 50.0, 50.0, 50.0],
        "SPIN": [90.0, 90.0, 90.0, 90.0, 91.0, 91.0],
        "ODD": [20.0, 20.0, 20.0, 21.0, 20.0, 20.0],
    })
    return cc.on_download_basis(prices, acts), second, with_actions(prices, acts)


def test_returns_are_paired_on_the_same_previous_day_and_sorted_by_what_went_ex() -> None:
    first, second, returns = sources()
    r = cc.return_pairs(first, second, returns)
    assert len(r) == 20 and r["kind"].value_counts().to_dict() == {"none": 17, "cash": 2, "split": 1}
    by_kind = cc.returns_by_kind(r, 1e-4, 0.01).set_index("went_ex")
    assert by_kind["apart"].to_dict() == {"none": 2, "cash": 1, "split": 0} and by_kind.loc["split", "agree"] == "100.000%"
    apart = cc.partings(r, 0.01)
    assert sorted(zip(apart["ticker"], apart["kind"], strict=True)) == [("ODD", "none"), ("ODD", "none"), ("SPIN", "cash")]
    assert cc.partings_by_year(r, apart)[["none", "cash", "split", "tickers"]].sum().tolist() == [2, 1, 0, 2]
    assert cc.busiest_days(apart, 1)["tickers"].tolist() == [1]
    gapped = second.loc[~((second["ticker"] == "DIV") & (second["date"] == DAYS[1]))]
    assert len(cc.return_pairs(first, gapped, returns)) == 18       # the day after the gap has another previous day


def test_cash_days_say_whether_the_second_source_holds_the_cash() -> None:
    first, second, returns = sources()
    got = cc.cash_days(cc.return_pairs(first, second, returns), 1e-4, [0.02, 0.05]).set_index("cash_over_price")
    assert got.loc["up to 2%", ["days", "price_return", "nearer_total", "nearer_price"]].tolist() == [1, 1, 0, 0]
    assert got.loc["over 5%", ["days", "price_return", "nearer_total", "nearer_price"]].tolist() == [1, 0, 1, 0]
    assert got.loc["2% to 5%", "days"] == 0


def test_variance_shares_are_zero_for_a_source_with_the_same_total_return() -> None:
    first, second, returns = sources()
    r = cc.return_pairs(first, second, returns)
    whole = r.assign(second_ret=r["total_ret"])
    got = cc.variance_shares(whole)
    assert set(got["second_return_lacks"]) == {"0.000%"} and (got["correlation"] == 1.0).all()
    assert cc.variance_shares(r).loc[0, "first_price_return_lacks"] != "0.000%"


def test_a_close_is_measured_against_its_tickers_basis() -> None:
    first, second, _ = sources()
    based = cc.against_basis(cc.paired(first, second), 3)
    odd = based.loc[based["ticker"] == "ODD"]
    assert (odd["off"] > 1e-4).tolist() == [False, False, False, True, False, False]
    spin = based.loc[based["ticker"] == "SPIN"]
    assert (spin["off"] > 1e-4).sum() == 0 and ((spin["basis"] - 1).abs() > 1e-3).tolist() == [True, True, False, False, False, False]
    other = cc.other_basis(based, 1e-3)
    assert other.to_dict("list") == {"ticker": ["SPIN"], "days": [2], "first": [DAYS[0]], "last": [DAYS[1]]}
    assert cc.other_basis_by_year(based, 1e-3).to_dict("list") == {"year": [2025, 2026], "symbol_days": [2, 0], "tickers": [1, 0]}
    assert cc.closes_by_year(based, [1e-4])["over_0.0001"].tolist() == ["0.000%", "8.333%"]


def write_days(root: Path, prices: pd.DataFrame, etfs: list[str]) -> Path:
    """The prices as a snapshot of day files: ETFs in one dataset, the rest in the other, the day in `date`."""
    stock_set, etf_set = mp.ASSETS
    is_etf = prices["ticker"].isin(etfs)
    for asset, part in ((stock_set, prices.loc[~is_etf]), (etf_set, prices.loc[is_etf])):
        for day, rows in part.groupby("date"):
            rows = rows.sort_values("ticker")
            table = pa.table({
                "date": pa.array([day.date()] * len(rows), pa.date32()), "symbol": rows["ticker"].tolist(),
                "asset_type": ["x"] * len(rows), **{c: rows[c].to_numpy(dtype="float64") for c in ["open", "high", "low", "close", "volume"]},
            })
            target = root / asset / str(day.year) / f"{day.date().isoformat()}.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(table, target)
    return root


@pytest.mark.slow
def test_the_same_prices_in_the_second_source_give_the_same_headline(tmp_path) -> None:
    returns, prices, _, universe, sectors = synthetic_market(seed=3)
    etfs = ["SPY", *sorted(MARKET_ETFS.values())]
    stocks = sorted(set(prices["ticker"]) - set(etfs))
    residuals = build_residuals(returns, sectors, prices, stocks, FACTORS, "SPY")
    long = {"returns": returns, "prices": prices, "residuals": residuals, "universe": universe, "sectors": sectors}
    candidates = pd.DataFrame({"ticker": stocks})
    cfg = backtest_config()
    last = MARKET_CAL[-3]
    cut = {name: frame.loc[frame["date"] <= last] if "date" in frame else frame for name, frame in long.items()}
    path = write_days(tmp_path / "2026-01-01", prices, etfs)

    from statarb.signals.tables import build_tables

    first = source_check.headline(build_tables(*cut.values(), "SPY", MARKET_ETFS), cfg, MARKET_ETFS)
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    entries = [
        experiments.entry(record(first.outcome.variant, cfg.fills.headline, level, cfg), m, 0, {}, now)
        for level, m in first.outcome.metrics.items()
    ]
    check = load_config("marketparquet")["cross_check"]
    manifest = {"digest": "0" * 64, "basis": "split_adjusted"}
    text = source_check.cross_check_report(
        path, manifest, cut, candidates, actions([]), entries, cfg, FACTORS, "SPY", etfs,
        MARKET_CAL[0].date(), last, check, {"snapshot": "2026-01-01", "digest": "1" * 64},
    )
    assert "exactly at every cost level: yes" in text
    assert "correlation 1.0000 net, 1.0000 gross" in text
    assert f"- Tickers: {len(stocks) + len(etfs)} in Alpaca's tables, {len(stocks) + len(etfs)} of them" in text
    assert " in both, 0 in Alpaca alone, 0 in MarketParquet alone" in text
    # No bar after the cut is read: the files of the last two days are never opened.
    for asset in mp.ASSETS:
        for day in MARKET_CAL[-2:]:
            (path / asset / str(day.year) / f"{day.date().isoformat()}.parquet").write_bytes(b"not to be opened")
    again = source_check.cross_check_report(
        path, manifest, cut, candidates, actions([]), entries, cfg, FACTORS, "SPY", etfs,
        MARKET_CAL[0].date(), last, check, {"snapshot": "2026-01-01", "digest": "1" * 64},
    )
    assert again == text


def test_logged_metrics_need_the_headline_in_the_log() -> None:
    with pytest.raises(ValueError, match="no entry for the headline"):
        source_check.logged_metrics([], backtest_config())


def test_leg_overlap_counts_the_names_both_books_hold() -> None:
    index = pd.bdate_range("2026-01-05", periods=2)
    a = pd.DataFrame([[1.0, -1.0, 0.0], [1.0, 1.0, -1.0]], index=index, columns=["A", "B", "C"])
    b = pd.DataFrame([[1.0, 0.0, -1.0], [1.0, 0.0, -1.0]], index=index, columns=["A", "B", "C"])
    got = source_check.leg_overlap(source_check.Headline(None, a, 0), source_check.Headline(None, b, 0)).set_index("leg")
    assert got["mean_share_in_common"].to_dict() == {"long": 0.75, "short": 0.5} and np.all(got["days"] == 2)
