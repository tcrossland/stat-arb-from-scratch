"""The model interface: a gradient-boosting library behind a small seam, chosen by name in config.

A backend fits a model on feature rows, with early stopping on a validation
set when one is given, and a fitted model predicts, gives each feature's
contribution to each prediction (TreeSHAP for trees), gives each feature's
total gain, and saves itself in the library's own text format, returning the
file's SHA-256 for the experiment log. Nothing else in the pipeline imports
the library, so a second backend is a new entry in `BACKENDS` and a change of
`[model] library` in `config/models.toml`; its models are a different
configuration and new trials. `tests/contract/test_models.py` runs every
backend through the same checks.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from statarb.models.lgbm import LightGbmBackend


class Model(Protocol):
    """A fitted model."""

    def predict(self, x: np.ndarray) -> np.ndarray:
        """One forecast per row."""
        ...

    def contributions(self, x: np.ndarray) -> np.ndarray:
        """(rows, features + 1): each feature's contribution to each forecast, then the expected value; rows sum to the forecast."""
        ...

    def gain(self) -> pd.Series:
        """Total gain of each feature's splits, indexed by feature name."""
        ...

    def save(self, path: Path) -> str:
        """Write the model in the library's text format and return the file's SHA-256."""
        ...


class Backend(Protocol):
    """A model library."""

    @property
    def name(self) -> str:
        """The name it is chosen by in `[model] library`."""
        ...

    def fit(
        self,
        x: np.ndarray,
        y: np.ndarray,
        names: list[str],
        hyper: Mapping[str, int],
        rounds: int,
        validation: tuple[np.ndarray, np.ndarray] | None = None,
        patience: int | None = None,
    ) -> tuple[Model, int]:
        """A model of at most `rounds` trees on (x, y) with the grid point `hyper`, and the number of trees it uses.

        With `validation`, training stops once the validation loss has not
        improved for `patience` rounds, and the model uses the best number of
        trees seen; without it, it uses all `rounds`.
        """
        ...

    def load(self, path: Path) -> Model:
        """A model saved by `Model.save`, using every tree in the file (phase 6: the daily job's forecast)."""
        ...


# Every backend, by the name `[model] library` chooses it by, each built from its own settings table.
BACKENDS: dict[str, Callable[[object], Backend]] = {"lightgbm": LightGbmBackend}


def make_backend(name: str, settings: object) -> Backend:
    if name not in BACKENDS:
        raise KeyError(f"no model library registered as {name!r}; registered: {sorted(BACKENDS)}")
    return BACKENDS[name](settings)
