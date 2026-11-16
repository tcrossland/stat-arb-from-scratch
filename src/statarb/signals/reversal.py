"""Cross-sectional reversal: the phase 2 baseline and its raw-return control.

Signal on day t, from data up to the close of t: minus the series (Model A's
residual or the total return) summed over the last n trading days, optionally
divided by its rolling volatility times sqrt(n).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from statarb.signals.base import Scores
from statarb.signals.tables import Tables

SOURCES = {"residual": "residuals", "raw": "returns"}   # series -> the table it comes from


def reversal_signal(
    series: pd.DataFrame,
    lookback: int,
    vol_scaled: bool = False,
    vol_window: int = 60,
    vol_min_observations: int = 45,
) -> pd.DataFrame:
    """(dates x tickers) signal from a (dates x tickers) series. NaN unless all n days are present."""
    total = series.rolling(lookback, min_periods=lookback).sum()
    if vol_scaled:
        vol = series.rolling(vol_window, min_periods=vol_min_observations).std()
        total = total / (vol * np.sqrt(lookback))
    return -total


@dataclass(frozen=True)
class ReversalSignal:
    name: str
    source: str                  # "residual" or "raw"
    lookback_days: int
    vol_scaled: bool
    vol_window_days: int
    vol_min_observations: int

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"reversal source must be one of {sorted(SOURCES)}")
        if self.lookback_days < 1:
            raise ValueError("lookback must be positive")

    @property
    def reads(self) -> tuple[str, ...]:
        return (SOURCES[self.source],)

    def scores(self, tables: Tables) -> Scores:
        series = tables.residual if self.source == "residual" else tables.raw
        panel = reversal_signal(series, self.lookback_days, self.vol_scaled, self.vol_window_days, self.vol_min_observations)
        return Scores(panel.to_numpy())
