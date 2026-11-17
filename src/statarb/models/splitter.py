"""Walk-forward splits with a purge and an embargo (López de Prado, *Advances in Financial Machine Learning*, chapter 7).

Rows are member-days, identified by their date position d. A row's target is
the residual move over d+1 to d+H, so it is known at the close of d+H. A test
block covers decision dates s to e-1, and its targets span s+1 to e-1+H.

- **Purge.** A training row whose target window overlaps the test targets is
  dropped: before the block, every row with d + H > s; after it, every row with
  d + 1 <= e - 1 + H.
- **Embargo.** After the block a further `embargo` rows are dropped, because
  the features of rows just after the block (a 20-day residual sum, say) are
  built from returns inside the test targets.

The walk-forward is expanding and purely forward: the model for a block is
trained at the close of the block's first day s on every row whose target is
known by then, d <= s - H. No training set follows the block it predicts, so
the embargo removes nothing there; `train_mask` implements both sides so each
can be tested, and any scheme that is not purely forward gets the embargo.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Fold:
    """One walk-forward block, in date positions."""

    test_start: int              # s: first decision date of the block
    test_stop: int               # e: one past its last decision date
    horizon: int                 # H

    @property
    def train_stop(self) -> int:
        """One past the last training date: rows with d <= s - H have known targets at the close of s."""
        return self.test_start - self.horizon + 1


def train_mask(day: np.ndarray, test_start: int, test_stop: int, horizon: int, embargo: int) -> np.ndarray:
    """Rows usable for training around a test block [test_start, test_stop): purged before, purged and embargoed after."""
    before = day + horizon <= test_start
    after = day >= test_stop + horizon - 1 + embargo
    return before | after


def walk_forward(dates: pd.DatetimeIndex, first_test: pd.Timestamp, last_date: pd.Timestamp, block_days: int, horizon: int) -> list[Fold]:
    """Consecutive test blocks of `block_days` decision dates from `first_test` to `last_date`, both included.

    The last block is cut short at `last_date`. The runners pass the
    development end, or start the holdout's blocks on its first day, so no
    block straddles the two.
    """
    start = int(dates.searchsorted(pd.Timestamp(first_test)))
    stop = int(dates.searchsorted(pd.Timestamp(last_date), side="right"))
    if block_days < 1:
        raise ValueError("block_days must be positive")
    if start - horizon + 1 <= 0:
        raise ValueError("the first test block leaves no training rows")
    return [Fold(s, min(s + block_days, stop), horizon) for s in range(start, stop, block_days)]


def inner_split(day: np.ndarray, fold: Fold, validation_days: int, embargo: int) -> tuple[np.ndarray, np.ndarray]:
    """Inner training and validation rows inside a fold's training window, for tuning.

    Validation is the last `validation_days` dates of the training window
    (d <= s - H), and the inner training rows are purged before it. Nothing in
    the training window follows the validation set, so the embargo again
    removes nothing; it is passed so the split applies the same rule as
    `train_mask`.
    """
    last = fold.train_stop                       # exclusive
    first = max(0, last - validation_days)
    in_window = day < last
    validation = in_window & (day >= first)
    training = in_window & train_mask(day, first, last, fold.horizon, embargo)
    return training, validation


def development_rows(day: np.ndarray, dates: pd.DatetimeIndex, last_date: pd.Timestamp, horizon: int) -> np.ndarray:
    """Rows whose target is known by the close of `last_date`: the only rows development metrics may read."""
    last = int(dates.searchsorted(pd.Timestamp(last_date), side="right")) - 1
    return day + horizon <= last
