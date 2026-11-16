"""The `Signal` interface (decision record 0002).

A signal declares the stored tables it reads and returns a score per stock and
day from them. The score on day t uses only what was known after the close of t,
which `tests/contract/test_signals.py` checks for every registered signal by
perturbing the tables after a cut-off. How often a book trades is the portfolio
rule's business, not the signal's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from statarb.signals.tables import Tables


@dataclass(frozen=True)
class Hedge:
    """Hedge ratios a signal estimates beside its score, for rules that hedge each position."""

    beta_market: np.ndarray      # dates x stocks
    beta_sector: np.ndarray      # dates x stocks, to the sector ETF in excess of the market
    etf_index: np.ndarray        # dates x stocks, the hedge column of the stock's sector ETF; -1 if none


@dataclass(frozen=True)
class Scores:
    score: np.ndarray            # dates x stocks; NaN where the signal has no view
    hedge: Hedge | None = None


class Signal(Protocol):
    """A score per stock and day from the tables it reads, cut at that day."""

    @property
    def name(self) -> str:
        """The name it is registered and chosen by in config."""
        ...

    @property
    def source(self) -> str:
        """The series it is built from, logged with each run."""
        ...

    @property
    def reads(self) -> tuple[str, ...]:
        """The stored tables it reads, from `statarb.signals.tables.TABLES`."""
        ...

    def scores(self, tables: Tables) -> Scores: ...
