"""Synthetic feature rows for the model tests: a ranked target that reverses the first feature, plus noise."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd

from statarb.models.config import load_models_config
from statarb.models.features import SECTOR, FeatureSet

CFG = load_models_config()
# Small enough for a fixture: fewer rows per leaf, a shorter validation window and fewer trees.
TUNING = dataclasses.replace(CFG.tuning, min_data_in_leaf=(20, 80), validation_days=40)
LIGHTGBM = dataclasses.replace(CFG.lightgbm, max_rounds=60, early_stopping_rounds=10)
NAMES = ["res_sum_1", "res_vol_20", "volume_ratio", SECTOR]


def synthetic_rows(seed: int = 0, days: int = 200, stocks: int = 40) -> tuple[FeatureSet, np.ndarray, pd.DatetimeIndex]:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=days)
    day, col = np.repeat(np.arange(days), stocks), np.tile(np.arange(stocks), days)
    x = rng.standard_normal((len(day), len(NAMES)))
    x[:, -1] = col % 4
    move = -0.5 * x[:, 0] + rng.standard_normal(len(day))
    ranks = pd.Series(move).groupby(day).rank().to_numpy()
    y = (ranks - 1) / (stocks - 1) - 0.5
    frame = pd.DataFrame({"date": dates[day], "ticker": [f"S{c:02d}" for c in col], **{n: x[:, i] for i, n in enumerate(NAMES)}})
    return FeatureSet(frame, NAMES, day, col), y, dates


def market_config(first_test: int = 150, block_days: int = 40):
    """config/models.toml cut down for helpers.synthetic_market: its calendar, 30 stocks and short history."""
    from helpers import MARKET_CAL

    period = dataclasses.replace(CFG.period, first_test=MARKET_CAL[first_test].date())
    return dataclasses.replace(
        CFG,
        period=period,
        walk_forward=dataclasses.replace(CFG.walk_forward, block_days=block_days),
        tuning=TUNING,
        lightgbm=LIGHTGBM,
    )
