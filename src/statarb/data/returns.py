"""Daily total returns from unadjusted bars.

Holding one share at the previous close gives split_ratio shares today, each
worth today's close plus any cash going ex today:

    ret = split_ratio * (close + cash) / previous close - 1

Inputs are unadjusted, so earlier returns never change when later events
are appended.
"""

from __future__ import annotations

import pandas as pd

from statarb.data.schema import DATE, TICKER


def total_returns(bars: pd.DataFrame) -> pd.DataFrame:
    """bars: long frame with date, ticker, close, cash, split_ratio (unadjusted)."""
    ordered = bars.sort_values([TICKER, DATE], kind="mergesort").reset_index(drop=True)
    grouped = ordered.groupby(TICKER, sort=False)
    prev_close = grouped["close"].shift(1)
    prev_date = grouped[DATE].shift(1)
    ret = ordered["split_ratio"] * (ordered["close"] + ordered["cash"]) / prev_close - 1.0
    out = pd.DataFrame(
        {
            DATE: ordered[DATE],
            TICKER: ordered[TICKER],
            "ret": ret,
            "prev_date": prev_date,
            "split_ratio": ordered["split_ratio"],
            "cash": ordered["cash"],
        }
    )
    return out.loc[prev_close.notna()].reset_index(drop=True)
