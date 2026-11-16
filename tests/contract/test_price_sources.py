"""Contract every PriceSource adapter must pass (phase 0 brief, "Source interfaces")."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from helpers import SplitAdjustedSource, truth_fixture
from statarb.data.canonical import to_unadjusted
from statarb.data.returns import total_returns
from statarb.data.schema import BAR_COLUMNS
from statarb.data.sources import PriceBasis

TICKER = "BRK.B"
START = dt.date(2020, 1, 1)
EARLY_END = dt.date(2020, 1, 22)   # after the 4:1 split, before the second dividend and the 2:1 split
LATE_END = dt.date(2020, 2, 5)     # all events


class UnadjustedReference:
    """A trivial adapter over the truth data, to keep the contract source-agnostic."""

    name = "reference"
    basis = PriceBasis.UNADJUSTED

    def __init__(self, truth: pd.DataFrame) -> None:
        self._truth = truth

    def source_symbol(self, ticker: str) -> str:
        return ticker

    def fetch(self, ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        t = self._truth
        return t.loc[(t["date"] >= pd.Timestamp(start)) & (t["date"] < pd.Timestamp(end))].reset_index(drop=True)


ADAPTERS = {
    "reference": UnadjustedReference,
    "split-adjusted": lambda truth: SplitAdjustedSource({TICKER: truth}),
}


@pytest.fixture(params=sorted(ADAPTERS))
def adapter(request):
    return ADAPTERS[request.param](truth_fixture())


def test_declares_an_eligible_basis(adapter) -> None:
    assert isinstance(adapter.basis, PriceBasis)
    assert adapter.basis is not PriceBasis.FULLY_ADJUSTED


def test_bars_have_schema_and_normalised_dates(adapter) -> None:
    bars = adapter.fetch(TICKER, START, LATE_END)
    assert list(bars.columns) == BAR_COLUMNS
    assert bars["date"].dtype == "datetime64[ns]"
    assert bars["date"].dt.tz is None
    assert (bars["date"] == bars["date"].dt.normalize()).all()
    assert bars["date"].is_monotonic_increasing and bars["date"].is_unique
    assert (bars["date"] >= pd.Timestamp(START)).all() and (bars["date"] < pd.Timestamp(LATE_END)).all()


def test_events_are_reported(adapter) -> None:
    bars = adapter.fetch(TICKER, START, LATE_END)
    assert sorted(bars.loc[bars["split_ratio"] != 1.0, "split_ratio"]) == [2.0, 4.0]
    assert (bars["cash"] >= 0).all() and (bars["cash"] > 0).sum() == 2
    assert (bars["split_ratio"] > 0).all()


def test_symbol_mapping_is_a_string(adapter) -> None:
    assert isinstance(adapter.source_symbol(TICKER), str)


def test_unadjusted_round_trip_matches_truth(adapter) -> None:
    truth = truth_fixture()
    unadj = to_unadjusted(adapter.fetch(TICKER, START, LATE_END), adapter.basis)
    for col in ["open", "close", "cash"]:
        np.testing.assert_allclose(unadj[col].to_numpy(), truth[col].to_numpy(), rtol=1e-12)
    np.testing.assert_allclose(unadj["volume"].to_numpy(), truth["volume"].to_numpy(), rtol=0, atol=0.5)


def test_returns_stable_when_later_events_arrive(adapter) -> None:
    def returns(end: dt.date) -> pd.DataFrame:
        bars = to_unadjusted(adapter.fetch(TICKER, START, end), adapter.basis).assign(ticker=TICKER)
        return total_returns(bars)

    early, late = returns(EARLY_END), returns(LATE_END)
    shared = late.loc[late["date"] < pd.Timestamp(EARLY_END)].reset_index(drop=True)
    pd.testing.assert_frame_equal(early, shared, check_exact=False, rtol=1e-12)


def test_no_jump_on_split_days(adapter) -> None:
    bars = to_unadjusted(adapter.fetch(TICKER, START, LATE_END), adapter.basis).assign(ticker=TICKER)
    rets = total_returns(bars)
    split_days = rets.loc[rets["split_ratio"] != 1.0, "ret"]
    assert len(split_days) == 2 and (split_days.abs() < 0.05).all()
