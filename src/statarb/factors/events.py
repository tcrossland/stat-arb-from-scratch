"""Crude event flag: unusual volume on the day of a move.

The ratio on day t is volume on t over the median volume of the previous
`lookback` trading days. Both are known at the close of t. Volumes are as
traded, so each is first divided by the product of all split ratios up to and
including its own day; the common factor cancels in the ratio, and a split
does not register as a volume spike.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from statarb.factors.model import wide


def volume_ratio(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    stocks: Sequence[str],
    calendar: pd.DatetimeIndex,
    lookback: int,
) -> pd.DataFrame:
    """Calendar x stocks panel of volume over its trailing median; NaN without a full lookback."""
    volume = wide(prices.astype({"volume": "float64"}), "volume", calendar, stocks)
    splits = wide(returns, "split_ratio", calendar, stocks).fillna(1.0).cumprod()
    volume = volume / splits
    baseline = volume.rolling(lookback, min_periods=lookback).median().shift(1)
    return volume / baseline.where(baseline > 0)
