"""Tune, fit and forecast one model per walk-forward block, through whichever backend config chooses.

For each block the grid is tried inside the training window only: each point
is fitted on the inner training rows with early stopping on the validation
rows (the end of the window, purged), and scored by its mean daily rank IC on
them. The best point is then refitted on the whole window with the number of
trees early stopping found, so the most recent rows are not left out of the
model that forecasts the block. Every grid point is returned for the log.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from statarb.models.backend import Backend, Model
from statarb.models.config import Tuning
from statarb.models.features import FeatureSet
from statarb.models.ic import daily_rank_ic
from statarb.models.splitter import Fold, inner_split


@dataclass(frozen=True)
class GridPoint:
    num_leaves: int
    min_data_in_leaf: int
    rounds: int                  # trees, by early stopping on the validation rows
    validation_ic: float         # mean daily rank IC on the validation days
    validation_l2: float

    @property
    def hyper(self) -> dict[str, int]:
        return {"num_leaves": self.num_leaves, "min_data_in_leaf": self.min_data_in_leaf}


@dataclass(frozen=True)
class BlockFit:
    fold: Fold
    train_first: pd.Timestamp
    train_last: pd.Timestamp
    train_rows: int
    grid: tuple[GridPoint, ...]
    chosen: GridPoint
    model: Model = field(repr=False)


def tune(
    backend: Backend, x: np.ndarray, y: np.ndarray, day: np.ndarray, names: list[str], fold: Fold,
    tuning: Tuning, max_rounds: int, patience: int, embargo: int,
) -> tuple[GridPoint, ...]:
    """Every grid point, fitted on the inner training rows and scored on the validation rows."""
    inner, val = inner_split(day, fold, tuning.validation_days, embargo)
    inner &= np.isfinite(y)
    val &= np.isfinite(y)
    out = []
    for leaves, min_leaf in itertools.product(tuning.num_leaves, tuning.min_data_in_leaf):
        hyper = {"num_leaves": leaves, "min_data_in_leaf": min_leaf}
        model, rounds = backend.fit(x[inner], y[inner], names, hyper, max_rounds, (x[val], y[val]), patience)
        pred = model.predict(x[val])
        ic = daily_rank_ic(day[val], pred, y[val])
        l2 = float(np.mean((pred - y[val]) ** 2))
        out.append(GridPoint(leaves, min_leaf, rounds, float(ic.mean()) if len(ic) else float("nan"), l2))
    return tuple(out)


def choose(grid: tuple[GridPoint, ...]) -> GridPoint:
    """Highest validation IC; ties, and an all-NaN grid, go to the earliest point in config order."""
    best = grid[0]
    for g in grid[1:]:
        if np.isfinite(g.validation_ic) and not (g.validation_ic <= best.validation_ic):
            best = g
    return best


def fit_block(
    backend: Backend, fs: FeatureSet, x: np.ndarray, y: np.ndarray, dates: pd.DatetimeIndex, fold: Fold,
    tuning: Tuning, max_rounds: int, patience: int, embargo: int,
) -> BlockFit:
    """Tune inside the fold's training window, then refit the chosen point on the whole window."""
    grid = tune(backend, x, y, fs.day, fs.names, fold, tuning, max_rounds, patience, embargo)
    chosen = choose(grid)
    rows = (fs.day < fold.train_stop) & np.isfinite(y)
    model, _ = backend.fit(x[rows], y[rows], fs.names, chosen.hyper, chosen.rounds)
    days = fs.day[rows]
    return BlockFit(fold, dates[days.min()], dates[days.max()], int(rows.sum()), grid, chosen, model)


def model_name(fit: BlockFit) -> str:
    """The model file's name: horizon and training window, so each block's file is unique and readable."""
    return f"h{fit.fold.horizon}_train_{fit.train_first.date()}_{fit.train_last.date()}.txt"


@dataclass(frozen=True)
class WalkForward:
    """Out-of-sample forecasts for every feature row in a test block (NaN elsewhere), and the fit of each block."""

    forecast: np.ndarray
    fits: tuple[BlockFit, ...]


def walk_forward_forecast(
    backend: Backend, fs: FeatureSet, y: np.ndarray, dates: pd.DatetimeIndex, folds: list[Fold],
    tuning: Tuning, max_rounds: int, patience: int, embargo: int,
    progress: Callable[[str], None] | None = None,
) -> WalkForward:
    """Each block's rows forecast by the model trained at the close of the block's first day."""
    x = fs.matrix()
    forecast = np.full(len(y), np.nan)
    fits = []
    for k, fold in enumerate(folds):
        fit = fit_block(backend, fs, x, y, dates, fold, tuning, max_rounds, patience, embargo)
        test = (fs.day >= fold.test_start) & (fs.day < fold.test_stop)
        forecast[test] = fit.model.predict(x[test])
        fits.append(fit)
        if progress is not None:
            c = fit.chosen
            progress(f"  block {k + 1}/{len(folds)} from {dates[fold.test_start].date()}: "
                     f"{c.num_leaves} leaves, {c.min_data_in_leaf} per leaf, {c.rounds} trees")
    return WalkForward(forecast, tuple(fits))
