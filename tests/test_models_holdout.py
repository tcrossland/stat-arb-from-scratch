"""The phase 5 holdout runner on the synthetic market: the read, its refusals, and that it adds no trial."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json

import numpy as np
import pytest

from helpers import MARKET_CAL
from runner_helpers import DEV_END, market_long, market_settings
from statarb.backtest import experiments
from statarb.backtest.trials import HOLDOUT_KINDS, trial_sharpes
from statarb.models import report
from statarb.models.holdout import (
    check_development_models,
    check_ready,
    check_reproduced,
    run_holdout,
)
from statarb.models.run import log_entries, run_development
from statarb.signals.tables import cut_after

STATE = {"git_commit": "c0ffee", "git_dirty": False, "config_overlay": None, "price_source": "synthetic", "price_snapshot": "2026-01-01"}
NOW = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
LATER = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)


def _written(entries: list[dict]) -> list[dict]:
    """Entries as the log holds them, after JSON."""
    return [json.loads(json.dumps(e, sort_keys=True)) for e in entries]


def _holdout_log(h, state=STATE) -> list[dict]:
    return _written([experiments.entry(c, m, 0, state, LATER) for c, m in h.entries])


@pytest.fixture(scope="module")
def logged(tmp_path_factory):
    s = market_settings()
    models = tmp_path_factory.mktemp("models")
    res = run_development(s, market_long(), models, {})
    return s, models, res, _written(log_entries(res.outcomes, res.logged, s.mc, s.cfg, STATE, NOW))


@pytest.fixture(scope="module")
def read(logged):
    s, models, _, log = logged
    walks = check_ready(log, s, STATE, repeat=False)
    return run_holdout(s, market_long(), models, walks, trial_sharpes(log))


# --- the read ----------------------------------------------------------------------------------------


def test_paths_cover_the_holdout_only(read) -> None:
    assert {o.daily.index.min() for o in read.outcomes} == {MARKET_CAL[DEV_END + 1]}
    assert {o.daily.index.max() for o in read.outcomes} == {MARKET_CAL[-1]}


def test_every_development_model_is_retrained_with_its_logged_hash(logged, read) -> None:
    _, _, res, _ = logged
    assert read.checked == sum(len(r.walk.fits) for r in res.fc.runs.values())


def test_holdout_blocks_restart_on_its_first_day(read) -> None:
    for config, metrics in read.entries[: len(read.fc.runs)]:
        assert config["kind"] == "holdout walk-forward"
        assert metrics["blocks"][0]["test_first"] == str(MARKET_CAL[DEV_END + 1].date())
    for run in read.fc.runs.values():
        assert not any(f.fold.test_start <= DEV_END < f.fold.test_stop - 1 for f in run.walk.fits)


def test_development_forecasts_do_not_change_when_the_holdout_is_loaded(logged, read) -> None:
    _, _, res, _ = logged
    for name, panel in res.fc.signal.items():
        np.testing.assert_array_equal(panel, read.fc.signal[name][: DEV_END + 1])


def test_the_holdout_adds_no_trial(logged, read) -> None:
    log = logged[3]
    assert trial_sharpes(log + _holdout_log(read)) == trial_sharpes(log)
    assert set(read.verdict["trials"]) == {len(trial_sharpes(log))}
    assert {c["kind"] for c, _ in read.entries} == set(HOLDOUT_KINDS)


def test_holdout_report_rebuilds_byte_for_byte(read, tmp_path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    report.write_holdout_report(read, a)
    report.write_holdout_report(read, b)
    for path in a.iterdir():
        assert path.read_bytes() == (b / path.name).read_bytes(), path.name
    assert "## Against the bar" in (a / "holdout.md").read_text()


def test_repeat_reproduces_the_logged_read(logged, read) -> None:
    s, models, _, log = logged
    full = log + _holdout_log(read)
    walks = check_ready(full, s, STATE, repeat=True)
    again = run_holdout(s, market_long(), models, walks, trial_sharpes(log))
    check_reproduced(full, again.entries)
    tampered = [dict(e, metrics={**e["metrics"], "sharpe": 9.0}) if e["config"]["kind"] == "holdout path" else e for e in full]
    with pytest.raises(ValueError, match="differs from the logged"):
        check_reproduced(tampered, again.entries)


# --- refusals --------------------------------------------------------------------------------------


def test_refuses_a_dirty_tree(logged) -> None:
    s, _, _, log = logged
    with pytest.raises(ValueError, match="commit first"):
        check_ready(log, s, {**STATE, "git_dirty": True}, repeat=False)


def test_refuses_a_second_read(logged, read) -> None:
    s, _, _, log = logged
    with pytest.raises(ValueError, match="already been read"):
        check_ready(log + _holdout_log(read), s, STATE, repeat=False)
    with pytest.raises(ValueError, match="has none"):
        check_ready(log, s, STATE, repeat=True)


def test_refuses_without_a_clean_development_run(logged) -> None:
    s, _, _, log = logged
    with pytest.raises(ValueError, match="no development run"):
        check_ready([], s, STATE, repeat=False)
    with pytest.raises(ValueError, match="clean tree"):
        check_ready([{**e, "git_dirty": True} for e in log], s, STATE, repeat=False)
    with pytest.raises(ValueError, match="price_snapshot"):
        check_ready(log, s, {**STATE, "price_snapshot": "2026-02-01"}, repeat=False)


@pytest.mark.parametrize(
    "change",
    [
        lambda s: dataclasses.replace(s, mc=dataclasses.replace(s.mc, lightgbm=dataclasses.replace(s.mc.lightgbm, learning_rate=0.1))),
        lambda s: dataclasses.replace(s, mc=dataclasses.replace(s.mc, runs=dataclasses.replace(s.mc.runs, rules=("decile sort",)))),
        lambda s: dataclasses.replace(s, ccfg=dataclasses.replace(s.ccfg, impact=dataclasses.replace(s.ccfg.impact, headline_coefficient=0.5))),
    ],
    ids=["model setting", "rules", "cost model"],
)
def test_refuses_a_configuration_unlike_the_last_development_run(logged, change) -> None:
    s, _, _, log = logged
    with pytest.raises(ValueError, match="configuration differs"):
        check_ready(log, change(s), STATE, repeat=False)


def test_refuses_a_development_model_unlike_its_logged_hash(logged, read) -> None:
    s, _, _, log = logged
    walks = check_ready(log, s, STATE, repeat=False)
    H = next(iter(walks))
    blocks = walks[H]["metrics"]["blocks"]
    tampered = {**walks, H: {**walks[H], "metrics": {**walks[H]["metrics"], "blocks": [{**blocks[0], "model_sha256": "0" * 64}, *blocks[1:]]}}}
    saved = {(h, k): (b["model_file"], b["model_sha256"]) for h, e in walks.items() for k, b in enumerate(e["metrics"]["blocks"])}
    with pytest.raises(ValueError, match="differs from the development run"):
        check_development_models(read.fc, saved, tampered, read.plab.lab.tables.dates, read.fc.start)


def test_refuses_tables_that_end_before_the_holdout_does(logged, tmp_path) -> None:
    s, _, _, log = logged
    walks = check_ready(log, s, STATE, repeat=False)
    with pytest.raises(ValueError, match="before the holdout's last day"):
        run_holdout(s, cut_after(market_long(), MARKET_CAL[-10]), tmp_path, walks, {})
