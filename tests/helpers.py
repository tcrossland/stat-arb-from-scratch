"""Test helpers: synthetic sources built from synthetic, unadjusted truth data. No real data."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from statarb.data.schema import BAR_COLUMNS, normalise_bars
from statarb.data.sources import PriceBasis


def synthetic_truth(
    dates: pd.DatetimeIndex,
    seed: int,
    price: float = 100.0,
    volume: float = 1_000_000.0,
    splits: dict[pd.Timestamp, float] | None = None,
    cash: dict[pd.Timestamp, float] | None = None,
) -> pd.DataFrame:
    """Unadjusted bars with a random walk close, for any number of days."""
    rng = np.random.default_rng(seed)
    splits = splits or {}
    cash = cash or {}
    rows = []
    for d in dates:
        if d in splits:
            price /= splits[d]
            volume *= splits[d]
        price *= float(np.exp(0.01 * rng.standard_normal()))
        rows.append(
            {
                "date": d,
                "open": price * 1.001,
                "high": price * 1.005,
                "low": price * 0.995,
                "close": price,
                "volume": float(round(volume * float(np.exp(0.3 * rng.standard_normal())))),
                "cash": cash.get(d, 0.0),
                "split_ratio": splits.get(d, 1.0),
            }
        )
    return pd.DataFrame(rows).astype({"date": "datetime64[ns]"})


def truth_fixture() -> pd.DataFrame:
    """A month of one ticker with a 4:1 split, two dividends and a 2:1 split."""
    return synthetic_truth(
        pd.bdate_range("2020-01-02", "2020-02-04"),
        seed=7,
        price=400.0,
        splits={pd.Timestamp("2020-01-15"): 4.0, pd.Timestamp("2020-01-29"): 2.0},
        cash={pd.Timestamp("2020-01-09"): 0.8, pd.Timestamp("2020-01-23"): 0.21},
    )


class SplitAdjustedSource:
    """A synthetic source whose bars are split-adjusted as of the download date `end`, not dividend-adjusted,
    with cash and volume on the same basis. Written independently of statarb.data.canonical, so the
    canonical step is checked against a basis it did not produce."""

    name = "synthetic"
    basis = PriceBasis.SPLIT_ADJUSTED

    def __init__(self, truths: dict[str, pd.DataFrame]) -> None:
        self._truths = truths

    def source_symbol(self, ticker: str) -> str:
        return ticker

    def fetch(self, ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        if ticker not in self._truths:
            return normalise_bars(pd.DataFrame({c: [] for c in BAR_COLUMNS}))
        t = self._truths[ticker]
        t = t.loc[t["date"] < pd.Timestamp(end)].reset_index(drop=True)
        ratios = t["split_ratio"].tolist()
        factor = np.array([float(np.prod(ratios[i + 1 :])) for i in range(len(ratios))])
        out = t.assign(
            **{c: t[c].to_numpy() / factor for c in ("open", "high", "low", "close", "cash")},
            volume=t["volume"].to_numpy() * factor,
        )
        return normalise_bars(out.loc[out["date"] >= pd.Timestamp(start)])
