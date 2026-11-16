"""Column names and dtypes shared across the data pipeline.

Every frame is in long format with explicit ``date`` and ``ticker`` columns.
Dates are tz-naive ``datetime64[ns]`` at midnight and mean the exchange
trading date.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd

# All dates in the project are New York trading dates. See docs/time-discipline.md.
EXCHANGE_TZ = "America/New_York"

DATE = "date"
TICKER = "ticker"

PRICE_COLUMNS = ["open", "high", "low", "close"]

# What a PriceSource returns for one ticker, on the basis it declares.
# cash: cash distributions going ex that day (dividends, and spin-offs valued as cash).
# split_ratio: new shares per old share going ex that day; 1.0 when there is none.
BAR_COLUMNS = [DATE, *PRICE_COLUMNS, "volume", "cash", "split_ratio"]

GICS_SECTORS = frozenset(
    {
        "Communication Services",
        "Consumer Discretionary",
        "Consumer Staples",
        "Energy",
        "Financials",
        "Health Care",
        "Industrials",
        "Information Technology",
        "Materials",
        "Real Estate",
        "Utilities",
    }
)

# Sectors that existed earlier in the history but not today. Telecommunication
# Services was broadened and renamed Communication Services in September 2018.
FORMER_GICS_SECTORS = frozenset({"Telecommunication Services"})


def exchange_today(now: dt.datetime | None = None) -> dt.date:
    """Today's date in New York, whatever the machine's time zone.

    ``now`` must be time zone aware; it defaults to the current time.
    """
    now = dt.datetime.now(dt.UTC) if now is None else now
    if now.tzinfo is None:
        raise ValueError("now must be time zone aware")
    return now.astimezone(ZoneInfo(EXCHANGE_TZ)).date()


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
