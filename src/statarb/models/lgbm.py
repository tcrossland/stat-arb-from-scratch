"""LightGBM behind the model interface (`statarb.models.backend`).

Models are saved in LightGBM's native text format, never pickle, and are
deterministic: `deterministic`, `force_row_wise`, a fixed seed and a fixed
thread count, so a model rebuilt from the same rows and config is
byte-identical. Contributions are LightGBM's own TreeSHAP (`pred_contrib`),
exact for trees, so no SHAP package is needed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from statarb.models.config import LightGbm
from statarb.models.features import SECTOR


def params(cfg: LightGbm, hyper: Mapping[str, int]) -> dict:
    return {
        "objective": "regression",           # squared error on the ranked target
        "learning_rate": cfg.learning_rate,
        "num_leaves": hyper["num_leaves"],
        "min_data_in_leaf": hyper["min_data_in_leaf"],
        "feature_fraction": cfg.feature_fraction,
        "bagging_fraction": cfg.bagging_fraction,
        "bagging_freq": cfg.bagging_freq,
        "seed": cfg.seed,
        "deterministic": True,
        "force_row_wise": True,
        "num_threads": cfg.num_threads,
        "verbosity": -1,
    }


def dataset(x: np.ndarray, y: np.ndarray, names: list[str], reference: lgb.Dataset | None = None) -> lgb.Dataset:
    return lgb.Dataset(
        x, label=y, feature_name=names, categorical_feature=[SECTOR] if SECTOR in names else [],
        reference=reference, free_raw_data=False,
        # The grid varies min_data_in_leaf; pre-filtering would fix the bins to the first value it saw.
        params={"feature_pre_filter": False, "verbosity": -1},
    )


@dataclass(frozen=True)
class LightGbmModel:
    booster: lgb.Booster
    rounds: int                  # trees used by predict and contributions

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.booster.predict(x, num_iteration=self.rounds)

    def contributions(self, x: np.ndarray) -> np.ndarray:
        return self.booster.predict(x, num_iteration=self.rounds, pred_contrib=True)

    def gain(self) -> pd.Series:
        return pd.Series(self.booster.feature_importance("gain", iteration=self.rounds), index=self.booster.feature_name(), name="gain")

    def save(self, path: Path) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.booster.save_model(str(path), num_iteration=self.rounds)
        return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class LightGbmBackend:
    settings: LightGbm
    name: str = "lightgbm"

    def fit(
        self,
        x: np.ndarray,
        y: np.ndarray,
        names: list[str],
        hyper: Mapping[str, int],
        rounds: int,
        validation: tuple[np.ndarray, np.ndarray] | None = None,
        patience: int | None = None,
    ) -> tuple[LightGbmModel, int]:
        train = dataset(x, y, names)
        if validation is None:
            booster = lgb.train(params(self.settings, hyper), train, num_boost_round=rounds)
            return LightGbmModel(booster, rounds), rounds
        if patience is None:
            raise ValueError("early stopping needs a patience")
        valid = dataset(*validation, names, reference=train)
        booster = lgb.train(
            params(self.settings, hyper),
            train,
            num_boost_round=rounds,
            valid_sets=[valid],
            callbacks=[lgb.early_stopping(patience, verbose=False)],
        )
        best = max(1, booster.best_iteration)
        return LightGbmModel(booster, best), best

    def load(self, path: Path) -> LightGbmModel:
        booster = lgb.Booster(model_file=str(path))
        return LightGbmModel(booster, booster.num_trees())
