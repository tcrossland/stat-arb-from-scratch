from __future__ import annotations

import pandas as pd
import pytest

from statarb.data.clean import ConflictingDuplicateError, clean_bars

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
