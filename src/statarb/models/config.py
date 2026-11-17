"""Typed phase 5 configuration from config/models.toml.

As for the other phases, every table must have exactly the documented keys: a
misspelt or missing parameter raises instead of falling back.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from statarb.backtest.config import _build
from statarb.config import load_config


@dataclass(frozen=True)
class Period:
    first_test: dt.date
    development_end: dt.date
    holdout_start: dt.date
    holdout_end: dt.date


@dataclass(frozen=True)
class WalkForward:
    block_days: int
    embargo_days: int


@dataclass(frozen=True)
class Target:
    horizons: tuple[int, ...]
    headline_horizon: int


@dataclass(frozen=True)
class Features:
    residual_sums: tuple[int, ...]
    volatility_windows: tuple[int, ...]
    volatility_min_fraction: float
    volume_window_days: int
    extreme_windows: tuple[int, ...]
    market_volatility_days: int
    sectors: tuple[str, ...]


@dataclass(frozen=True)
class LightGbm:
    learning_rate: float
    feature_fraction: float
    bagging_fraction: float
    bagging_freq: int
    max_rounds: int
    early_stopping_rounds: int
    seed: int
    num_threads: int


@dataclass(frozen=True)
class Tuning:
    num_leaves: tuple[int, ...]
    min_data_in_leaf: tuple[int, ...]
    validation_days: int


@dataclass(frozen=True)
class ModelsConfig:
    period: Period
    walk_forward: WalkForward
    target: Target
    features: Features
    lightgbm: LightGbm
    tuning: Tuning

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelsConfig:
        cfg = _build(cls, data, "models")
        cfg.validate()
        return cfg

    def validate(self) -> None:
        p = self.period
        if not p.first_test <= p.development_end < p.holdout_start <= p.holdout_end:
            raise ValueError("period: needs first_test <= development_end < holdout_start <= holdout_end")
        if self.walk_forward.block_days < 1 or self.walk_forward.embargo_days < 0:
            raise ValueError("walk_forward: block_days must be positive and embargo_days not negative")
        t = self.target
        if not t.horizons or min(t.horizons) < 1 or t.headline_horizon not in t.horizons:
            raise ValueError("target: horizons must be positive and include headline_horizon")
        f = self.features
        windows = (*f.residual_sums, *f.volatility_windows, *f.extreme_windows, f.volume_window_days, f.market_volatility_days)
        if not f.residual_sums or not f.volatility_windows or not f.extreme_windows or min(windows) < 1:
            raise ValueError("features: windows must be given and positive")
        if not 0 < f.volatility_min_fraction <= 1:
            raise ValueError("features: volatility_min_fraction must be in (0, 1]")
        if not f.sectors or len(set(f.sectors)) != len(f.sectors):
            raise ValueError("features: sectors must be a list of distinct names")
        if self.lightgbm.num_threads < 1:
            raise ValueError("lightgbm: num_threads must be fixed and positive, for determinism")
        if self.tuning.validation_days < 1 or not self.tuning.num_leaves or not self.tuning.min_data_in_leaf:
            raise ValueError("tuning: needs a grid and a positive validation window")


def load_models_config(root: Path | None = None) -> ModelsConfig:
    return ModelsConfig.from_dict(load_config("models", root))
