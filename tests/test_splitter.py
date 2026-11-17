"""The walk-forward splitter: blocks, the purge, the embargo, the inner validation split and the development rows."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from statarb.models.splitter import (
    Fold,
    development_rows,
    inner_split,
    train_mask,
    walk_forward,
)

CAL = pd.bdate_range("2021-01-04", periods=300)
DAY = np.repeat(np.arange(len(CAL)), 3)          # three rows a day, as member-days are


def _targets(day: np.ndarray, horizon: int) -> set[int]:
    """Every date position a set of rows' targets cover: d+1 to d+H."""
    return {d + k for d in np.unique(day) for k in range(1, horizon + 1)}


@pytest.mark.parametrize("horizon", [1, 3, 5])
def test_walk_forward_trains_only_on_targets_known_at_the_block_start(horizon: int) -> None:
    folds = walk_forward(CAL, CAL[150], CAL[279], 40, horizon)
    for f in folds:
        train = DAY[DAY < f.train_stop]
        test = DAY[(DAY >= f.test_start) & (DAY < f.test_stop)]
        assert train.max() + horizon == f.test_start                        # the last target is known at the close of s
        assert not _targets(train, horizon) & _targets(test, horizon)       # no train-test overlap after the purge
        assert not set(np.unique(train)) & set(np.unique(test))


def test_walk_forward_blocks_are_contiguous_and_end_at_the_last_date() -> None:
    folds = walk_forward(CAL, CAL[150], CAL[279], 40, 1)
    assert [(f.test_start, f.test_stop) for f in folds] == [(150, 190), (190, 230), (230, 270), (270, 280)]
    assert folds[-1].test_stop - 1 == 279                                  # cut short, never past the last date


def test_walk_forward_starts_on_the_next_trading_day_and_refuses_an_empty_first_window() -> None:
    between = CAL[149] + pd.Timedelta(hours=12)                           # not a trading date
    assert walk_forward(CAL, between, CAL[279], 40, 1)[0].test_start == 150
    with pytest.raises(ValueError, match="no training rows"):
        walk_forward(CAL, CAL[2], CAL[279], 40, 3)
    with pytest.raises(ValueError, match="block_days"):
        walk_forward(CAL, CAL[150], CAL[279], 0, 1)


@pytest.mark.parametrize(("horizon", "embargo"), [(1, 0), (3, 0), (3, 5), (5, 2)])
def test_train_mask_purges_both_sides_and_embargoes_after(horizon: int, embargo: int) -> None:
    s, e = 100, 140
    keep = train_mask(DAY, s, e, horizon, embargo)
    test = DAY[(DAY >= s) & (DAY < e)]
    kept = np.unique(DAY[keep])
    assert not _targets(kept, horizon) & _targets(test, horizon)
    before, after = kept[kept < s], kept[kept >= e]
    assert before.max() == s - horizon                                     # purged before: the last row whose target ends by s
    assert after.min() == e + horizon - 1 + embargo                        # purged and embargoed after
    # The rows dropped after the block: the purge reaches the last test target, the embargo goes further.
    dropped_after = set(range(e, len(CAL))) - set(after)
    assert dropped_after == set(range(e, e + horizon - 1 + embargo))


def test_inner_split_validates_on_the_end_of_the_training_window() -> None:
    fold = Fold(200, 240, 3)
    train, val = inner_split(DAY, fold, 40, 5)
    vdays, tdays = np.unique(DAY[val]), np.unique(DAY[train])
    assert vdays.min() == fold.train_stop - 40 and vdays.max() == fold.train_stop - 1
    assert vdays.max() + fold.horizon == fold.test_start                  # validation targets known at the block start
    assert tdays.max() + fold.horizon == vdays.min()                      # inner training purged before validation
    assert not _targets(tdays, 3) & _targets(vdays, 3)
    assert not (train & val).any()


def test_inner_split_with_a_short_window_validates_on_all_of_it() -> None:
    train, val = inner_split(DAY, Fold(30, 70, 1), 252, 5)
    assert not train.any() and np.unique(DAY[val]).tolist() == list(range(30))


def test_development_rows_stop_where_targets_reach_past_the_last_date() -> None:
    rows = development_rows(DAY, CAL, CAL[279], 3)
    assert np.unique(DAY[rows]).max() == 276
    assert not rows[DAY > 276].any()
