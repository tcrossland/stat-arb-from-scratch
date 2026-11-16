"""Point-in-time universe.

On the last trading day of each month, rank candidates by median dollar
volume over the trailing window of trading days, using only data up to and
including that day. A candidate with bars on fewer than `min_obs` days of the
window is not ranked that month. The top `size` names are members from the
next trading day up to and including the next rebalance day.
"""

from __future__ import annotations

import pandas as pd

from statarb.data.schema import DATE, TICKER


def month_end_rebalance_dates(calendar: pd.DatetimeIndex) -> pd.DatetimeIndex:
    cal = pd.Series(calendar, index=calendar)
    return pd.DatetimeIndex(cal.groupby(calendar.to_period("M")).max().to_numpy())


def trailing_median_dollar_volume(
    bars: pd.DataFrame, calendar: pd.DatetimeIndex, window: int, min_obs: int
) -> pd.DataFrame:
    """Calendar x ticker frame; NaN where fewer than min_obs days in the window."""
    dollar_volume = bars.assign(dv=bars["close"] * bars["volume"]).pivot(index=DATE, columns=TICKER, values="dv")
    dollar_volume = dollar_volume.reindex(calendar)
    return dollar_volume.rolling(window, min_periods=min_obs).median()


def build_universe(
    bars: pd.DataFrame,
    tickers: list[str],
    calendar: pd.DatetimeIndex,
    size: int,
    window: int,
    min_obs: int,
) -> pd.DataFrame:
    """Return membership as rows (date, ticker), plus the rebalance day that set it."""
    stock_bars = bars.loc[bars[TICKER].isin(tickers)]
    medians = trailing_median_dollar_volume(stock_bars, calendar, window, min_obs)
    rebalances = month_end_rebalance_dates(calendar)
    rows = []
    for i, day in enumerate(rebalances):
        ranked = medians.loc[day].dropna()
        if ranked.empty:
            continue
        order = pd.DataFrame({TICKER: ranked.index, "dv": ranked.to_numpy()})
        order = order.sort_values(["dv", TICKER], ascending=[False, True], kind="mergesort")
        members = order[TICKER].head(size).tolist()
        next_day = rebalances[i + 1] if i + 1 < len(rebalances) else calendar[-1]
        effective = calendar[(calendar > day) & (calendar <= next_day)]
        for d in effective:
            rows.extend((d, t, day) for t in members)
    return pd.DataFrame(rows, columns=[DATE, TICKER, "rebalanced_on"]).astype(
        {DATE: "datetime64[ns]", "rebalanced_on": "datetime64[ns]"}
    )
