from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from statarb.config import load_config, repo_root
from statarb.data.clean import (
    ConflictingDuplicateError,
    clean_bars,
    parse_listing_starts,
)

CAL = pd.DatetimeIndex(pd.bdate_range("2021-01-04", periods=5))


def _row(day, close=10.0, open_=10.0, ticker="A", volume=1.0):
    return {"date": pd.Timestamp(day), "ticker": ticker, "open": open_, "high": close, "low": close, "close": close,
            "volume": volume, "cash": 0.0, "split_ratio": 1.0}


def test_rules_drop_and_log_with_reasons() -> None:
    bars = pd.DataFrame(
        [
            _row("2021-01-04"),
            _row("2021-01-04"),                       # identical duplicate: collapsed silently
            _row("2021-01-09"),                       # Saturday
            _row("2021-01-05", close=float("nan")),
            _row("2021-01-06", close=-1.0),
            _row("2021-01-07", volume=0.0),           # kept
        ]
    )
    clean, log = clean_bars(bars, CAL)
    assert clean["date"].tolist() == [pd.Timestamp("2021-01-04"), pd.Timestamp("2021-01-07")]
    assert sorted(log["reason"]) == ["missing open or close", "non-positive price", "not a trading day"]


def test_conflicting_duplicates_raise() -> None:
    bars = pd.DataFrame([_row("2021-01-04", close=10.0), _row("2021-01-04", close=11.0)])
    with pytest.raises(ConflictingDuplicateError):
        clean_bars(bars, CAL)


def test_history_before_a_configured_listing_start_is_dropped() -> None:
    cal = pd.DatetimeIndex(pd.bdate_range("2020-02-03", periods=10))
    bars = pd.DataFrame([_row(d, ticker=t) for d in cal for t in ("A", "B")])
    clean, log = clean_bars(bars, cal, listing_starts={"A": pd.Timestamp("2020-02-10")})
    assert clean.loc[clean["ticker"] == "A", "date"].min() == pd.Timestamp("2020-02-10")
    assert clean.loc[clean["ticker"] == "B", "date"].min() == cal[0]
    assert (log["reason"] == "before listing (configured)").sum() == 5


def test_listing_start_for_an_unknown_ticker_raises() -> None:
    bars = pd.DataFrame([_row("2021-01-04")])
    with pytest.raises(ValueError, match="ZZZ"):
        clean_bars(bars, CAL, listing_starts={"ZZZ": pd.Timestamp("2021-01-05")})


def _start(**overrides):
    entry = {"ticker": "A", "first_date": dt.date(2020, 2, 10), "note": "n", "source": "s"}
    entry.update(overrides)
    return {k: v for k, v in entry.items() if v is not None}


@pytest.mark.parametrize(
    "entries",
    [
        [_start(source=None)],                         # missing key
        [{**_start(), "frist_date": dt.date(2020, 1, 1)}],  # unknown key
        [_start(first_date="2020-02-10")],             # string, not a TOML date
        [_start(), _start()],                          # duplicate ticker
    ],
)
def test_bad_listing_start_entries_raise(entries) -> None:
    with pytest.raises((ValueError, TypeError)):
        parse_listing_starts(entries)


def test_repository_listing_starts_are_valid_and_cite_sources() -> None:
    entries = load_config("listing_starts", repo_root()).get("start", [])
    starts = parse_listing_starts(entries)
    assert starts["VRT"] == pd.Timestamp("2020-02-10")
    assert all(e["source"].startswith("https://") for e in entries)
