"""The config overlay: merged over the base config, refusing keys the base does not have, and logged."""

from __future__ import annotations

import datetime as dt
import shutil

import pytest

from statarb.backtest import experiments
from statarb.config import OVERLAY_ENV, load_config, merged, repo_root


@pytest.fixture
def root(tmp_path):
    shutil.copytree(repo_root() / "config", tmp_path / "config")
    (tmp_path / "overlay").mkdir()
    return tmp_path


def _overlay(root, name: str, text: str, monkeypatch) -> None:
    (root / "overlay" / f"{name}.toml").write_text(text)
    monkeypatch.setenv(OVERLAY_ENV, "overlay")


def test_merge_replaces_values_and_merges_tables() -> None:
    base = {"a": {"x": 1, "y": [1, 2]}, "b": 3}
    assert merged(base, {"a": {"y": [5]}}, "f") == {"a": {"x": 1, "y": [5]}, "b": 3}
    assert base == {"a": {"x": 1, "y": [1, 2]}, "b": 3}            # the base is not changed


def test_merge_refuses_a_key_the_base_lacks_or_a_changed_kind() -> None:
    with pytest.raises(KeyError, match=r"f\.a\.z"):
        merged({"a": {"x": 1}}, {"a": {"z": 1}}, "f")
    with pytest.raises(TypeError, match=r"f\.a"):
        merged({"a": {"x": 1}}, {"a": 1}, "f")


def test_without_an_overlay_the_base_is_read(root, monkeypatch) -> None:
    monkeypatch.delenv(OVERLAY_ENV, raising=False)
    assert load_config("backtest", root) == load_config("backtest", repo_root())


def test_an_overlay_changes_only_the_keys_it_sets(root, monkeypatch) -> None:
    monkeypatch.delenv(OVERLAY_ENV, raising=False)
    base, factors = load_config("backtest", root), load_config("factors", root)
    _overlay(root, "backtest", "[period]\nstart = 2018-01-02\n", monkeypatch)
    over = load_config("backtest", root)
    assert over["period"]["start"] == dt.date(2018, 1, 2)
    assert {k: v for k, v in over.items() if k != "period"} == {k: v for k, v in base.items() if k != "period"}
    assert load_config("factors", root) == factors                  # no file in the overlay
    assert (root / "config" / "backtest.toml").read_bytes() == (repo_root() / "config" / "backtest.toml").read_bytes()


def test_a_misspelt_overlay_key_fails(root, monkeypatch) -> None:
    _overlay(root, "backtest", "[period]\nstrat = 2018-01-02\n", monkeypatch)
    with pytest.raises(KeyError, match=r"backtest\.period\.strat"):
        load_config("backtest", root)


def test_a_missing_overlay_directory_is_an_error(root, monkeypatch) -> None:
    monkeypatch.setenv(OVERLAY_ENV, "nowhere")
    with pytest.raises(FileNotFoundError, match="nowhere"):
        load_config("backtest", root)


def test_log_entries_record_the_overlay_and_the_price_source(root, monkeypatch) -> None:
    monkeypatch.delenv(OVERLAY_ENV, raising=False)
    source = load_config("data", root)["source"]
    plain = experiments.run_state(root)
    assert plain["config_overlay"] is None
    assert (plain["price_source"], plain["price_snapshot"]) == (source["name"], source["snapshot"])
    _overlay(root, "data", '[source]\nsnapshot = "2026-11-15"\n', monkeypatch)
    over = experiments.run_state(root)
    assert (over["config_overlay"], over["price_snapshot"]) == ("overlay", "2026-11-15")
    now = dt.datetime(2026, 11, 16, tzinfo=dt.UTC)
    with_overlay, without = (experiments.entry({"a": 1}, {}, 0, state, now) for state in (over, plain))
    assert with_overlay["config_overlay"] == "overlay" and without["config_overlay"] is None
    assert with_overlay["config_id"] == without["config_id"]       # the config alone sets the id
