"""Cleaning rules for unadjusted bars. Every dropped row is logged with a reason.

Rules, applied in order:
1. duplicate (ticker, date) rows: identical duplicates are collapsed; conflicting ones raise
2. dates not in the trading calendar are dropped
3. rows with a missing open or close are dropped
4. rows with a non-positive open, high, low or close are dropped
5. history before a configured listing start is dropped: a source can carry
   a ticker's history from before its own listing, such as a SPAC's shell
   trading before its merger or another security that held the symbol.
   Starts come from config/listing_starts.toml, each with its source.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

import pandas as pd

from statarb.data.schema import DATE, PRICE_COLUMNS, TICKER


class ConflictingDuplicateError(ValueError):
    pass


LISTING_START_KEYS = frozenset({"ticker", "first_date", "note", "source"})


def parse_listing_starts(entries: list[dict[str, Any]]) -> dict[str, pd.Timestamp]:
    """Validate ``[[start]]`` entries from config/listing_starts.toml (rule 5)."""
    starts: dict[str, pd.Timestamp] = {}
    for entry in entries:
        keys = set(entry)
        if keys != LISTING_START_KEYS:
            raise ValueError(
                f"listing start {entry.get('ticker', '?')}: missing {sorted(LISTING_START_KEYS - keys)}, "
                f"unknown {sorted(keys - LISTING_START_KEYS)}"
            )
        ticker, first = entry["ticker"], entry["first_date"]
        if not isinstance(first, dt.date) or isinstance(first, dt.datetime):
            raise TypeError(f"listing start {ticker}: first_date must be a TOML date, got {first!r}")
        if ticker in starts:
            raise ValueError(f"listing start {ticker}: listed twice")
        starts[ticker] = pd.Timestamp(first)
    return starts



def clean_bars(
    bars: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    *,
    listing_starts: Mapping[str, pd.Timestamp] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (clean bars, drop log with date, ticker, reason)."""
    listing_starts = dict(listing_starts or {})
    unknown = sorted(set(listing_starts) - set(bars[TICKER]))
    if unknown:
        raise ValueError(f"listing starts configured for tickers with no bars: {unknown}")
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
    first = frame[TICKER].map(listing_starts).astype("datetime64[ns]")
    frame = drop(frame, first.notna() & (frame[DATE] < first), "before listing (configured)")

    log = pd.concat(drops, ignore_index=True) if drops else pd.DataFrame(
        {DATE: pd.Series(dtype="datetime64[ns]"), TICKER: pd.Series(dtype="str"), "reason": pd.Series(dtype="str")}
    )
    return frame.reset_index(drop=True), log
