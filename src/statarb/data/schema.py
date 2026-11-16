"""Column names and dtypes shared across the data pipeline.

Every frame is in long format with explicit ``date`` and ``ticker`` columns.
Dates are tz-naive ``datetime64[ns]`` at midnight and mean the exchange
trading date.
"""

from __future__ import annotations

import pandas as pd

DATE = "date"
TICKER = "ticker"

PRICE_COLUMNS = ["open", "high", "low", "close"]

# What a PriceSource returns for one ticker, on the basis it declares.
# cash: cash distributions going ex that day.
# split_ratio: new shares per old share going ex that day; 1.0 when there is none.
BAR_COLUMNS = [DATE, *PRICE_COLUMNS, "volume", "cash", "split_ratio"]


def normalise_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with exactly BAR_COLUMNS, standard dtypes, sorted by date."""
    missing = set(BAR_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"bars missing columns: {sorted(missing)}")
    out = frame.loc[:, BAR_COLUMNS].copy()
    out[DATE] = pd.to_datetime(out[DATE]).astype("datetime64[ns]")
    for col in [*PRICE_COLUMNS, "volume", "cash", "split_ratio"]:
        out[col] = out[col].astype("float64")
    return out.sort_values(DATE, kind="mergesort").reset_index(drop=True)
