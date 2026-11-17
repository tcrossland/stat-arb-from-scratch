"""Tuning, block fits and the walk-forward forecast, and the daily rank IC."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from models_helpers import LIGHTGBM, TUNING, synthetic_rows
from statarb.models.backend import make_backend
from statarb.models.ic import daily_rank_ic, ic_summary
from statarb.models.splitter import Fold, walk_forward
from statarb.models.training import (
    GridPoint,
    choose,
    fit_block,
    model_name,
    walk_forward_forecast,
)

BACKEND = make_backend("lightgbm", LIGHTGBM)
ROUNDS, PATIENCE, EMBARGO = LIGHTGBM.max_rounds, LIGHTGBM.early_stopping_rounds, 5


def _fit(fs, y, dates, fold):
    return fit_block(BACKEND, fs, fs.matrix(), y, dates, fold, TUNING, ROUNDS, PATIENCE, EMBARGO)


def test_every_grid_point_is_tried_and_the_best_validation_ic_chosen() -> None:
    fs, y, dates = synthetic_rows()
    fit = _fit(fs, y, dates, Fold(150, 180, 1))
    assert [(g.num_leaves, g.min_data_in_leaf) for g in fit.grid] == [(15, 20), (15, 80), (63, 20), (63, 80)]
    assert fit.chosen.validation_ic == max(g.validation_ic for g in fit.grid)
    assert fit.train_first == dates[0] and fit.train_last == dates[149] and fit.train_rows == 150 * 40
    assert model_name(fit) == f"h1_train_{dates[0].date()}_{dates[149].date()}.txt"


def test_choose_breaks_ties_and_skips_nan_in_config_order() -> None:
    g = [GridPoint(15, 500, 5, 0.02, 0.1), GridPoint(15, 2000, 5, 0.02, 0.1), GridPoint(63, 500, 5, float("nan"), 0.1)]
    assert choose(tuple(g)) is g[0]
    nan = [GridPoint(15, 500, 5, float("nan"), 0.1), GridPoint(63, 500, 5, float("nan"), 0.1)]
    assert choose(tuple(nan)) is nan[0]


@pytest.mark.parametrize("horizon", [1, 3])
def test_a_block_model_does_not_change_with_targets_unknown_at_its_start(horizon: int, tmp_path) -> None:
    fs, y, dates = synthetic_rows()
    fold = Fold(150, 180, horizon)
    later = fs.day >= fold.train_stop                                     # targets not known at the close of s
    y2 = np.where(later, np.random.default_rng(1).permutation(y), y)
    x2 = fs.matrix().copy()
    x2[fs.day >= fold.test_start, 0] *= -1                                # and features of the block itself
    a = _fit(fs, y, dates, fold)
    b = fit_block(BACKEND, fs, x2, y2, dates, fold, TUNING, ROUNDS, PATIENCE, EMBARGO)
    assert a.grid == b.grid and a.chosen == b.chosen
    assert a.model.save(tmp_path / "a.txt") == b.model.save(tmp_path / "b.txt")


def test_walk_forward_forecasts_only_test_rows_each_from_its_own_block() -> None:
    fs, y, dates = synthetic_rows()
    folds = walk_forward(dates, dates[120], dates[199], 30, 1)
    wf = walk_forward_forecast(BACKEND, fs, y, dates, folds, TUNING, ROUNDS, PATIENCE, EMBARGO)
    tested = fs.day >= 120
    assert np.isfinite(wf.forecast[tested]).all() and np.isnan(wf.forecast[~tested]).all()
    assert len(wf.fits) == len(folds) == 3
    block = (fs.day >= 150) & (fs.day < 180)
    np.testing.assert_array_equal(wf.forecast[block], wf.fits[1].model.predict(fs.matrix()[block]))
    ic = daily_rank_ic(fs.day[tested], wf.forecast[tested], y[tested])
    assert ic.mean() > 0.1                                                # out of sample, it finds the reversal


def test_walk_forward_forecast_of_a_block_ignores_everything_after_its_start() -> None:
    fs, y, dates = synthetic_rows()
    folds = walk_forward(dates, dates[120], dates[199], 30, 1)
    cut = folds[1].test_start
    y2 = np.where(fs.day >= cut, -y, y)
    x2 = fs.matrix().copy()
    x2[fs.day >= folds[2].test_start] = 0.0
    fs2 = dataclasses.replace(fs, frame=fs.frame.assign(**{n: x2[:, i] for i, n in enumerate(fs.names)}))
    a = walk_forward_forecast(BACKEND, fs, y, dates, folds, TUNING, ROUNDS, PATIENCE, EMBARGO)
    b = walk_forward_forecast(BACKEND, fs2, y2, dates, folds, TUNING, ROUNDS, PATIENCE, EMBARGO)
    upto = fs.day < folds[2].test_start
    np.testing.assert_array_equal(a.forecast[upto], b.forecast[upto])


def test_daily_rank_ic() -> None:
    day = np.repeat(np.arange(5), 12)
    f = np.tile(np.arange(12.0), 5)
    np.testing.assert_allclose(daily_rank_ic(day, f, f * 2 + 1).to_numpy(), 1.0)
    np.testing.assert_allclose(daily_rank_ic(day, f, -f).to_numpy(), -1.0)
    assert daily_rank_ic(day, f, f, min_names=13).empty                   # too few names a day
    s = ic_summary(pd.Series([0.1, 0.3]))
    assert s["mean"] == pytest.approx(0.2) and s["days"] == 2 and s["t_stat"] == pytest.approx(0.2 / np.std([0.1, 0.3], ddof=1) * np.sqrt(2))
