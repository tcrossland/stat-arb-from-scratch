"""Every model library behind `statarb.models.backend` through the same checks.

A backend must fit with and without early stopping, predict one value per row,
give contributions that add up to the forecast, give the gain of every
feature, and save a model whose bytes, and SHA-256, are the same each time it
is rebuilt from the same rows and settings.
"""

from __future__ import annotations

import numpy as np
import pytest

from models_helpers import CFG, LIGHTGBM, NAMES, synthetic_rows
from statarb.models.backend import BACKENDS, make_backend

SETTINGS = {"lightgbm": LIGHTGBM}
HYPER = {"num_leaves": 15, "min_data_in_leaf": 20}


def test_every_backend_has_contract_settings() -> None:
    assert set(SETTINGS) == set(BACKENDS)
    assert CFG.model.library in BACKENDS


def test_an_unknown_library_is_refused() -> None:
    with pytest.raises(KeyError, match="no model library"):
        make_backend("xgboost", LIGHTGBM)


def _data():
    fs, y, _ = synthetic_rows()
    x = fs.matrix()
    train, val = fs.day < 150, (fs.day >= 150) & (fs.day < 180)
    return x, y, train, val


@pytest.mark.parametrize("name", sorted(BACKENDS))
def test_fit_predict_contributions_and_gain(name: str) -> None:
    backend = make_backend(name, SETTINGS[name])
    x, y, train, val = _data()
    model, rounds = backend.fit(x[train], y[train], NAMES, HYPER, 30)
    assert rounds == 30
    pred = model.predict(x[val])
    assert pred.shape == (int(val.sum()),) and np.isfinite(pred).all()
    contrib = model.contributions(x[val])
    assert contrib.shape == (int(val.sum()), len(NAMES) + 1)
    np.testing.assert_allclose(contrib.sum(axis=1), pred, rtol=1e-9, atol=1e-12)
    gain = model.gain()
    assert list(gain.index) == NAMES and (gain >= 0).all() and gain["res_sum_1"] == gain.max()
    assert np.corrcoef(pred, y[val])[0, 1] > 0.1                          # it learns the fixture's reversal


@pytest.mark.parametrize("name", sorted(BACKENDS))
def test_early_stopping_uses_the_best_round_seen(name: str) -> None:
    backend = make_backend(name, SETTINGS[name])
    x, y, train, val = _data()
    model, rounds = backend.fit(x[train], y[train], NAMES, HYPER, 60, (x[val], y[val]), 5)
    assert 1 <= rounds <= 60
    again, _ = backend.fit(x[train], y[train], NAMES, HYPER, rounds)
    np.testing.assert_array_equal(model.predict(x[val]), again.predict(x[val]))   # the stopped model is the first `rounds` trees
    with pytest.raises(ValueError, match="patience"):
        backend.fit(x[train], y[train], NAMES, HYPER, 60, (x[val], y[val]))


@pytest.mark.parametrize("name", sorted(BACKENDS))
def test_a_rebuilt_model_is_byte_identical(name: str, tmp_path) -> None:
    backend = make_backend(name, SETTINGS[name])
    x, y, train, _ = _data()
    first, _ = backend.fit(x[train], y[train], NAMES, HYPER, 30)
    second, _ = backend.fit(x[train], y[train], NAMES, HYPER, 30)
    sha1, sha2 = first.save(tmp_path / "a" / "m.txt"), second.save(tmp_path / "b" / "m.txt")
    assert sha1 == sha2 and len(sha1) == 64
    assert (tmp_path / "a" / "m.txt").read_bytes() == (tmp_path / "b" / "m.txt").read_bytes()
    other, _ = backend.fit(x[train], y[train], NAMES, {**HYPER, "num_leaves": 63}, 30)
    assert other.save(tmp_path / "c" / "m.txt") != sha1
