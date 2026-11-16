"""Cleaning rules for unadjusted bars. Every dropped row is logged with a reason.

Rules, applied in order:
1. duplicate (ticker, date) rows: identical duplicates are collapsed; conflicting ones raise
2. dates not in the trading calendar are dropped
3. rows with a missing open or close are dropped
4. rows with a non-positive open, high, low or close are dropped
"""

from __future__ import annotations

import pandas as pd

from statarb.data.schema import DATE, PRICE_COLUMNS, TICKER


class ConflictingDuplicateError(ValueError):
    pass


def clean_bars(
    bars: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (clean bars, drop log with date, ticker, reason)."""
    drops: list[pd.DataFrame] = []

    def drop(frame: pd.DataFrame, mask: pd.Series, reason: str) -> pd.DataFrame:
        if mask.any():
            drops.append(frame.loc[mask, [DATE, TICKER]].assign(reason=reason))
        return frame.loc[~mask]

    frame = bars.drop_duplicates()
    if frame.duplicated([TICKER, DATE]).any():
        bad = frame.loc[frame.duplicated([TICKER, DATE], keep=False), [TICKER, DATE]]
        raise ConflictingDuplicateError(f"conflicting rows for the same ticker and date:\n{bad.head()}")

    frame = drop(frame, ~frame[DATE].isin(calendar), "not a trading day")
    frame = drop(frame, frame["open"].isna() | frame["close"].isna(), "missing open or close")
    frame = drop(frame, (frame[PRICE_COLUMNS] <= 0).any(axis=1), "non-positive price")

    log = pd.concat(drops, ignore_index=True) if drops else pd.DataFrame(
        {DATE: pd.Series(dtype="datetime64[ns]"), TICKER: pd.Series(dtype="str"), "reason": pd.Series(dtype="str")}
    )
    return frame.reset_index(drop=True), log
