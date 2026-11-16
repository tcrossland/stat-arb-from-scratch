"""Shared conversion from a source's declared basis to unadjusted data.

Unadjusted prices are what actually traded on each day. They never change
when a later split or dividend occurs, which is what makes rebuilds and a
later daily append stable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from statarb.data.schema import PRICE_COLUMNS, normalise_bars
from statarb.data.sources import IneligibleSourceError, PriceBasis


def splits_after(split_ratio: np.ndarray) -> np.ndarray:
    """For each row, the product of split ratios on strictly later rows."""
    if len(split_ratio) == 0:
        return np.ones(0)
    from_here = np.cumprod(split_ratio[::-1])[::-1]
    return np.append(from_here[1:], 1.0)


def to_unadjusted(bars: pd.DataFrame, basis: PriceBasis) -> pd.DataFrame:
    """Convert one ticker's bars (schema.BAR_COLUMNS) to unadjusted form."""
    out = normalise_bars(bars)
    if basis is PriceBasis.UNADJUSTED:
        return out
    if basis is PriceBasis.FULLY_ADJUSTED:
        raise IneligibleSourceError("fully adjusted prices cannot be converted to unadjusted form")
    if basis is not PriceBasis.SPLIT_ADJUSTED:
        raise ValueError(f"unknown basis: {basis}")
    factor = splits_after(out["split_ratio"].to_numpy())
    for col in [*PRICE_COLUMNS, "cash"]:
        out[col] = out[col] * factor
    out["volume"] = np.rint(out["volume"] / factor)
    return out
