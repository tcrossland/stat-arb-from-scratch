from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from statarb.data.canonical import splits_after, to_unadjusted
from statarb.data.returns import total_returns
from statarb.data.schema import normalise_bars
from statarb.data.sources import IneligibleSourceError, PriceBasis


def _bars(close, cash=None, split=None, volume=None):
    n = len(close)
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2021-03-01", periods=n),
            "open": close, "high": close, "low": close, "close": close,
            "volume": volume or [100.0] * n,
            "cash": cash or [0.0] * n,
            "split_ratio": split or [1.0] * n,
        }
    )


def test_splits_after_excludes_the_split_day_itself() -> None:
    np.testing.assert_array_equal(splits_after(np.array([1.0, 2.0, 1.0, 3.0])), [6.0, 3.0, 3.0, 1.0])


def test_split_adjusted_to_unadjusted_hand_example() -> None:
    # 2:1 split on day 3. Split-adjusted closes 50, 51 are really 100, 102.
    adj = _bars([50.0, 51.0, 52.0], cash=[0.5, 0.0, 0.0], split=[1.0, 1.0, 2.0], volume=[200.0, 200.0, 100.0])
    out = to_unadjusted(adj, PriceBasis.SPLIT_ADJUSTED)
    assert out["close"].tolist() == [100.0, 102.0, 52.0]
    assert out["cash"].tolist() == [1.0, 0.0, 0.0]
    assert out["volume"].tolist() == [100.0, 100.0, 100.0]


def test_unadjusted_is_left_as_it_is() -> None:
    bars = _bars([10.0, 11.0], split=[1.0, 2.0])
    pd.testing.assert_frame_equal(to_unadjusted(bars, PriceBasis.UNADJUSTED), normalise_bars(bars))


def test_fully_adjusted_is_ineligible() -> None:
    with pytest.raises(IneligibleSourceError):
        to_unadjusted(_bars([1.0, 2.0]), PriceBasis.FULLY_ADJUSTED)


def test_total_return_hand_example() -> None:
    # Day 2: dividend of 1 on a 100 stock that closes at 100: +1%.
    # Day 3: 2:1 split, close 51 per new share: 2 * 51 / 100 - 1 = +2%.
    bars = _bars([100.0, 100.0, 51.0], cash=[0.0, 1.0, 0.0], split=[1.0, 1.0, 2.0]).assign(ticker="X")
    rets = total_returns(bars)
    np.testing.assert_allclose(rets["ret"], [0.01, 0.02])
    assert rets["prev_date"].tolist() == bars["date"].iloc[:2].tolist()


def test_returns_are_per_ticker_whatever_the_row_order() -> None:
    a = _bars([10.0, 11.0]).assign(ticker="A")
    b = _bars([20.0, 18.0]).assign(ticker="B")
    rets = total_returns(pd.concat([b, a]).iloc[::-1])
    assert rets.set_index("ticker")["ret"].round(10).to_dict() == {"A": 0.1, "B": -0.1}
