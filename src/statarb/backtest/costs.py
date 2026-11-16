"""Trading cost models behind one interface, chosen in config.

Phase 2 has one: a flat cost per dollar traded. Phase 3 adds the spread,
impact and commission components behind the same `CostModel`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


class CostModel(Protocol):
    """Trading cost per day by component, in the engine's weight units.

    `trades` is the (dates x tickers) panel of weights traded and `gross` the
    gross exposure per day that the day's returns are measured on, so a model
    that works in dollars can scale the book to a stated size and back.
    """

    def components(self, trades: np.ndarray, gross: np.ndarray) -> dict[str, np.ndarray]: ...


@dataclass(frozen=True)
class FlatCost:
    """A flat one-way cost per dollar traded, in basis points."""

    bps: float

    def components(self, trades: np.ndarray, gross: np.ndarray) -> dict[str, np.ndarray]:
        return {"flat": self.bps * 1e-4 * np.abs(trades).sum(axis=1)}


