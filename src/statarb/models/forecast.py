"""The walk-forward model forecast as a `Signal`, and the calibration of any forecast to return units.

The forecast enters through the same interface as the reversal signals, so the
look-ahead contract in `tests/contract/test_signals.py` runs over it,
perturbing later values and removing later rows, and it reaches the
calibration, the cost model and the portfolio rules by the baseline's route.

On day t in a test block starting on s, the score is the forecast of the model
trained at the close of s, on rows whose target was known by then, from the
features on t. The walk-forward runs in blocks from `[period] first_test` to
the development end, or the last date of the tables if earlier, and, when the
tables reach the holdout, in blocks that restart on its first day
(`forecast_folds`). No block straddles the boundary, so every development
block, and its model, is the same whether or not the holdout is loaded. The
development runner cuts every table at the development end first; only the
holdout runner loads more. Days before the first block, and member-days
without features, have no score.

Phase 6's daily job does not retrain: `saved_forecast` reads the walk-forward's
saved model files, each checked against the SHA-256 the frozen record holds,
and on each day uses the model of the latest block starting on or before it.
After the last block that model continues. On the days the walk-forward covers
it gives the walk-forward's forecast.

The calibration is phase 3's: the slope of the residual move over the next h
days on the demeaned score, from signal-outcome pairs whose outcome is known by
the close of t (`statarb.signals.calibration`), times the day's demeaned score.
The model's forecast and the baseline go through it alike.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from statarb.models.backend import Backend, Model, make_backend
from statarb.models.config import ModelsConfig
from statarb.models.features import FeatureSet, build_features, ranked_target
from statarb.models.splitter import Fold, walk_forward
from statarb.models.training import WalkForward, walk_forward_forecast
from statarb.signals.base import Scores
from statarb.signals.calibration import calibration_slope, expected_move, forward_sum
from statarb.signals.tables import TABLES, Tables


def forecast_folds(dates: pd.DatetimeIndex, cfg: ModelsConfig, horizon: int) -> list[Fold]:
    """Development blocks from `first_test`, the last cut short at the development end; then, when the
    dates reach the holdout, holdout blocks from its first day to its last."""
    p, block = cfg.period, cfg.walk_forward.block_days
    folds = walk_forward(dates, pd.Timestamp(p.first_test), min(dates[-1], pd.Timestamp(p.development_end)), block, horizon)
    if dates[-1] >= pd.Timestamp(p.holdout_start):
        folds += walk_forward(dates, pd.Timestamp(p.holdout_start), min(dates[-1], pd.Timestamp(p.holdout_end)), block, horizon)
    return folds


@dataclass(frozen=True)
class ForecastRun:
    """Everything a walk-forward produced: the feature rows, their target, and each block's fit and forecasts."""

    features: FeatureSet
    target: np.ndarray           # per feature row
    walk: WalkForward

    def panel(self, shape: tuple[int, int]) -> np.ndarray:
        """(dates x stocks) forecast, NaN outside the test blocks."""
        return self.features.to_panel(self.walk.forecast, shape)


@dataclass(frozen=True)
class ForecastSignal:
    """The model forecast for a target horizon, by the settings of `config/models.toml`."""

    config: ModelsConfig
    horizon: int
    progress: object = None      # a callable taking a line of progress, or None

    name = "model"
    source = "features"
    reads = TABLES

    def __post_init__(self) -> None:
        if self.horizon not in self.config.target.horizons:
            raise ValueError(f"horizon {self.horizon} is not in [target] horizons {self.config.target.horizons}")

    def run(self, tables: Tables, features: FeatureSet | None = None) -> ForecastRun:
        """The walk-forward on `tables`; `features`, if given, must be `build_features` of the same tables."""
        cfg = self.config
        fs = build_features(tables, cfg.features) if features is None else features
        y = fs.values_of(ranked_target(tables.residual.to_numpy(), tables.members, self.horizon))
        folds = forecast_folds(tables.dates, cfg, self.horizon)
        backend = make_backend(cfg.model.library, cfg.lightgbm)
        walk = walk_forward_forecast(
            backend, fs, y, tables.dates, folds, cfg.tuning, cfg.lightgbm.max_rounds, cfg.lightgbm.early_stopping_rounds,
            cfg.walk_forward.embargo_days, self.progress,
        )
        return ForecastRun(fs, y, walk)

    def scores(self, tables: Tables) -> Scores:
        return Scores(self.run(tables).panel((len(tables.dates), len(tables.stocks))))


@dataclass(frozen=True)
class SavedBlock:
    """One walk-forward block's model file, as the phase 5 log records it."""

    test_first: pd.Timestamp     # the block's first test date
    file: str                    # name in `[paths] models`
    sha256: str


class ModelHashError(RuntimeError):
    """A model file is missing or differs from the SHA-256 recorded for it: retraining is a new decision."""


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_checked(backend: Backend, model_dir: Path, block: SavedBlock) -> Model:
    """The block's model, refused unless its file has the recorded SHA-256."""
    path = model_dir / block.file
    if not path.is_file():
        raise ModelHashError(f"model file {block.file} is missing from {model_dir}")
    digest = file_sha256(path)
    if digest != block.sha256:
        raise ModelHashError(f"model file {block.file} has SHA-256 {digest}, not the recorded {block.sha256}")
    return backend.load(path)


def saved_forecast(fs: FeatureSet, dates: pd.DatetimeIndex, models: Sequence[tuple[pd.Timestamp, Model]], shape: tuple[int, int]) -> np.ndarray:
    """(dates x stocks) forecast from saved models: each feature row by the model of the latest block that starts on
    or before its date; NaN before the first block."""
    starts = [pd.Timestamp(t) for t, _ in models]
    if starts != sorted(starts) or len(set(starts)) != len(starts):
        raise ValueError("saved models must be in order of their blocks' first test dates, without repeats")
    x = fs.matrix()
    row_dates = dates[fs.day]
    values = np.full(len(fs.day), np.nan)
    for k, (first, model) in enumerate(models):
        upto = starts[k + 1] if k + 1 < len(starts) else None
        rows = (row_dates >= first) if upto is None else (row_dates >= first) & (row_dates < upto)
        if rows.any():
            values[rows] = model.predict(x[rows])
    return fs.to_panel(values, shape)


def calibrated_move(signal: np.ndarray, residual: np.ndarray, members: np.ndarray, horizon: int, window: int, min_days: int) -> np.ndarray:
    """(dates x stocks) expected residual move over the next `horizon` days; NaN until the calibration has `min_days` dates."""
    outcome = forward_sum(residual, horizon)
    slope = calibration_slope(signal, outcome, members, horizon, window, min_days)
    return expected_move(signal, members, slope)
