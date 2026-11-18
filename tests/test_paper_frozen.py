"""Phase 6 frozen record, on a copy of the repository's config with a strategy frozen in it."""

from __future__ import annotations

import json
import re
import shutil

import pytest

from statarb.backtest import experiments
from statarb.config import load_config, repo_root
from statarb.paper import frozen
from statarb.paper.config import load_paper_config

UNSET = 'forecast = ""\nrule = ""\nslope_rule = ""\nbook_size = 0\nconfig_hash = ""'
FROZEN_KEYS = re.compile(r'forecast = ".*"\nrule = ".*"\nslope_rule = ".*"\nbook_size = \d+\nconfig_hash = ".*"')


def _copy(tmp_path, frozen_keys: str):
    """A copy of the repository's config and phase 5 log, with `frozen_keys` in place of its `[frozen]` values."""
    shutil.copytree(repo_root() / "config", tmp_path / "config")
    log = tmp_path / "reports" / frozen.PHASE_5_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(repo_root() / "reports" / frozen.PHASE_5_LOG, log)
    paper = tmp_path / "config" / "paper.toml"
    text, n = FROZEN_KEYS.subn(lambda _: frozen_keys, paper.read_text())
    assert n == 1
    paper.write_text(text)
    return tmp_path


def _unfrozen(tmp_path):
    return _copy(tmp_path, UNSET)


def _freeze(tmp_path, forecast: str, rule: str):
    chosen = f'forecast = "{forecast}"\nrule = "{rule}"\nslope_rule = "floored"\nbook_size = 5000000\nconfig_hash = "{{}}"'
    root = _copy(tmp_path, chosen.format(""))
    digest = frozen.write(root)
    paper = root / "config" / "paper.toml"
    paper.write_text(paper.read_text().replace('config_hash = ""', f'config_hash = "{digest}"'))
    return root


@pytest.fixture
def root(tmp_path):
    return _freeze(tmp_path, "baseline", "no-trade zone")


def _edit(root, name: str, old: str, new: str) -> None:
    path = root / "config" / f"{name}.toml"
    text = path.read_text()
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new))


def test_the_repository_matches_its_frozen_record() -> None:
    """Decision record 0007 froze the strategy: any change to what the record pins is a new decision."""
    assert frozen.check(repo_root()) == []
    f = load_paper_config(repo_root()).frozen
    assert (f.forecast, f.rule, f.slope_rule, f.book_size) == ("three-day lookback", "optimiser κ = 1", "floored", 5_000_000)


def test_nothing_frozen_is_refused(tmp_path) -> None:
    root = _unfrozen(tmp_path)
    assert frozen.check(root) == [
        "[frozen] in config/paper.toml is not set: the forward run waits for the decision record that freezes its strategy"
    ]
    with pytest.raises(frozen.FrozenConfigError, match="not set"):
        frozen.write(root)


def test_a_fresh_freeze_matches(root) -> None:
    assert frozen.check(root) == []
    assert frozen.require(root) == load_paper_config(root).frozen.config_hash
    record = json.loads((root / "reports" / frozen.RECORD).read_text())
    assert experiments.config_id(record) == load_paper_config(root).frozen.config_hash
    assert record["models"] == []
    assert record["strategy"]["slope_rule"] == "floored" and record["strategy"]["price_source"] == "alpaca"
    assert not set(frozen.DATES) & set(record["strategy"])


def test_a_changed_parameter_is_named(root) -> None:
    _edit(root, "costs", "headline_half_spread_bps = 1.5", "headline_half_spread_bps = 2.0")
    assert frozen.check(root) == [
        "changed since the freeze: files.costs.spread.headline_half_spread_bps",
        "changed since the freeze: strategy.spread",
    ]
    with pytest.raises(frozen.FrozenConfigError, match="headline_half_spread_bps"):
        frozen.require(root)


def test_the_frozen_choice_is_in_the_record(root) -> None:
    _edit(root, "paper", "book_size = 5000000", "book_size = 500000")
    assert frozen.check(root) == ["changed since the freeze: strategy.book_size"]


def test_comments_and_fetch_settings_are_not_changes(root) -> None:
    _edit(root, "costs", "headline_half_spread_bps = 1.5", "headline_half_spread_bps = 1.5   # a new comment")
    _edit(root, "data", "pause_seconds = 0.3", "pause_seconds = 1.0")
    pinned = load_config("data", root)["source"]["snapshot"]
    _edit(root, "data", f'snapshot = "{pinned}"', 'snapshot = "2099-01-02"')
    assert frozen.check(root) == []


def test_an_edited_record_fails_its_hash(root) -> None:
    path = root / "reports" / frozen.RECORD
    record = json.loads(path.read_text())
    record["strategy"]["book_size"] = 1
    path.write_text(json.dumps(record))
    problems = frozen.check(root)
    assert any("hashes to" in p for p in problems)
    assert "changed since the freeze: strategy.book_size" in problems


def test_write_refuses_to_replace_a_different_freeze(root) -> None:
    _edit(root, "costs", "headline_half_spread_bps = 1.5", "headline_half_spread_bps = 2.0")
    with pytest.raises(frozen.FrozenConfigError, match="new decision record"):
        frozen.write(root)


def test_an_overlay_is_refused(root, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("STATARB_CONFIG_OVERLAY", str(tmp_path))
    assert "overlay" in frozen.check(root)[0]


def test_a_model_forecast_pins_every_block_file(tmp_path) -> None:
    H = load_config("models")["target"]["horizons"][-1]
    root = _freeze(tmp_path, f"model H={H}", "optimiser κ = 1")
    record = json.loads((root / "reports" / frozen.RECORD).read_text())
    log = experiments.read(root / "reports" / frozen.PHASE_5_LOG)
    blocks = [b for e in log if e["config"]["kind"] in ("walk-forward", "holdout walk-forward") and e["config"]["horizon"] == H for b in e["metrics"]["blocks"]]
    assert [m["test_first"] for m in record["models"]] == sorted({b["test_first"] for b in blocks})
    assert all(len(m["sha256"]) == 64 and m["file"].startswith(f"h{H}_") for m in record["models"])
    assert record["strategy"]["model"]["horizon"] == H
    assert frozen.check(root) == []


def test_differences_and_without() -> None:
    assert frozen.differences({"a": {"b": 1, "c": [1, 2]}, "d": 1}, {"a": {"b": 2, "c": [1, 2]}, "e": 1}) == ["a.b", "d (removed)", "e (added)"]
    table = {"x": 1, "s": {"name": "y", "snapshot": "z"}, "p": {"q": 1}}
    assert frozen.without(table, (("p",), ("s", "snapshot"), ("missing", "key"))) == {"x": 1, "s": {"name": "y"}}
    assert table["s"] == {"name": "y", "snapshot": "z"}           # the input is not changed
