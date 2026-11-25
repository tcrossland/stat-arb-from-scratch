"""Cross-sectional momentum: total-return momentum and residual momentum (phase 8).

Signal on day t, from data up to the close of t: the series over the `window`
trading days that end `skip` days before t, so the last `skip` days' returns
(the skip month, which is reversal) are left out. Total-return momentum
(Jegadeesh and Titman, 1993) compounds the total returns over the window.
Residual momentum (Blitz, Huij and Martens, 2011) sums the residuals over the
window and divides by their standard deviation over the same window. A score
needs every day of its window, and a stock is scored only from its first
residual on, the day a live run first knows it (`known_on`), as reversal is.

Written apart from `statarb.signals.reversal` rather than as minus a reversal
with its rows shifted: reversal scales by a volatility over its own window
times sqrt(n), which residual momentum does not, and the shift by `skip` is the
whole of the skip month, so it is clearer stated once here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from statarb.signals.base import Scores
from statarb.signals.tables import Tables, known_on

SOURCES = {"residual": "residuals", "raw": "returns"}   # series -> the table it comes from


def momentum_signal(series: pd.DataFrame, source: str, window: int = 252, skip: int = 21) -> pd.DataFrame:
    """(dates x tickers) momentum from a (dates x tickers) series on a sorted calendar.

    The value on row t uses rows t - skip - window + 1 to t - skip, and is NaN
    unless all `window` of them are present. On total returns (`raw`) it is the
    compounded return over those rows; on residuals it is their sum over their
    standard deviation.
    """
    if source not in SOURCES:
        raise ValueError(f"momentum source must be one of {sorted(SOURCES)}")
    if window < 2 or skip < 0:
        raise ValueError("momentum needs a window of at least 2 days and a skip of no fewer than 0")
    if not series.index.is_monotonic_increasing:
        raise ValueError("the series must be sorted by date")
    lagged = series.shift(skip)                              # row t holds the value of row t - skip
    if source == "raw":
        return np.expm1(np.log1p(lagged).rolling(window, min_periods=window).sum())
    rolling = lagged.rolling(window, min_periods=window)
    return rolling.sum() / rolling.std()


@dataclass(frozen=True)
class MomentumSignal:
    name: str
    source: str                  # "residual" or "raw"
    window_days: int = 252
    skip_days: int = 21

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"momentum source must be one of {sorted(SOURCES)}")
        if self.window_days < 2 or self.skip_days < 0:
            raise ValueError("momentum needs a window of at least 2 days and a skip of no fewer than 0")

    @property
    def reads(self) -> tuple[str, ...]:
        # Residuals also say from which day a stock is known.
        return tuple(sorted({SOURCES[self.source], "residuals"}))

    def scores(self, tables: Tables) -> Scores:
        series = tables.residual if self.source == "residual" else tables.raw
        panel = momentum_signal(series, self.source, self.window_days, self.skip_days)
        return Scores(np.where(known_on(tables.residual.to_numpy()), panel.to_numpy(), np.nan))
