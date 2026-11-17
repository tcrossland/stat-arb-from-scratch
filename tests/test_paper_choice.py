"""The phase 6 choice runner on the synthetic market: slope rules, its checks against phase 5's log, and its trials."""

from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from runner_helpers import market_long, market_settings
from statarb.backtest import experiments
from statarb.backtest.trials import path_id, trial_sharpes
from statarb.config import load_config
from statarb.models.forecast import ModelHashError
from statarb.models.holdout import (
    check_ready,
    development_rates,
    development_trials,
    run_holdout,
)
from statarb.models.run import DECILE, PARTIAL, log_entries, run_development
from statarb.paper import day, frozen, report, reproduce
from statarb.paper.choice import (
    CHOICE,
    DIAGNOSTIC,
    forward,
    holdout_days,
    label,
    parse_label,
    run_choice,
    slope,
)
from statarb.paper.choice import (
    log_entries as choice_entries,
)
from statarb.paper.config import (
    SLOPE_RULES,
    TRAILING,
    Frozen,
    PaperConfig,
    model_horizon,
)

STATE = {"git_commit": "c0ffee", "git_dirty": False, "config_overlay": None, "price_source": "synthetic", "price_snapshot": "2026-01-01"}
NOW, LATER, LATEST = (dt.datetime(2026, 1, d, tzinfo=dt.UTC) for d in (1, 2, 3))


def _written(entries: list[dict]) -> list[dict]:
    return [json.loads(json.dumps(e, sort_keys=True)) for e in entries]


@pytest.fixture(scope="module")
def models(tmp_path_factory):
    """Where phase 5 saves its block models, development and holdout."""
    return tmp_path_factory.mktemp("models")


@pytest.fixture(scope="module")
def phase5(models):
    """Phase 5's log on the synthetic market: the development run, then the holdout read."""
    s = market_settings()
    res = run_development(s, market_long(), models, {})
    log = _written(log_entries(res.outcomes, res.logged, s.mc, s.cfg, STATE, NOW))
    h = run_holdout(s, market_long(), models, check_ready(log, s, STATE, repeat=False), development_trials(log, {}), development_rates(log))
    return s, log + _written([experiments.entry(c, m, 0, STATE, LATER) for c, m in h.entries])


@pytest.fixture(scope="module")
def chosen(phase5):
    s, log = phase5
    return run_choice(s, market_long(), SLOPE_RULES, log, {})


# --- slope rules -------------------------------------------------------------------------------------


def test_labels_round_trip() -> None:
    for rule in SLOPE_RULES:
        assert parse_label(label("model H=3", rule)) == ("model H=3", rule)
    assert label("baseline", TRAILING) == "baseline"


def _panel(seed: int = 0, days: int = 120, stocks: int = 25):
    rng = np.random.default_rng(seed)
    signal = rng.standard_normal((days, stocks))
    residual = -0.02 * signal + 0.01 * rng.standard_normal((days, stocks))
    return signal, residual, np.ones((days, stocks), dtype=bool)


def test_floored_slope_is_the_trailing_slope_never_below_zero() -> None:
    signal, residual, members = _panel()
    trailing = slope(-signal, residual, members, TRAILING, 5, 30, 10)
    floored = slope(-signal, residual, members, "floored", 5, 30, 10)
    assert (trailing[np.isfinite(trailing)] < 0).any()
    np.testing.assert_array_equal(np.isnan(floored), np.isnan(trailing))
    np.testing.assert_array_equal(floored[np.isfinite(floored)], np.maximum(trailing[np.isfinite(trailing)], 0.0))


@pytest.mark.parametrize("rule", SLOPE_RULES)
def test_a_slope_does_not_see_later_rows(rule) -> None:
    signal, residual, members = _panel(1)
    t = 70
    before = slope(signal, residual, members, rule, 5, 30, 10)
    rng = np.random.default_rng(9)
    s2, r2 = signal.copy(), residual.copy()
    s2[t + 1 :] += rng.standard_normal(s2[t + 1 :].shape)
    r2[t + 1 :] += rng.standard_normal(r2[t + 1 :].shape)
    after = slope(s2, r2, members, rule, 5, 30, 10)
    np.testing.assert_array_equal(before[: t + 1], after[: t + 1])


def test_expanding_slope_differs_from_trailing_after_the_window() -> None:
    signal, residual, members = _panel(2)
    trailing = slope(signal, residual, members, TRAILING, 5, 30, 10)
    expanding = slope(signal, residual, members, "expanding", 5, 30, 10)
    first = np.flatnonzero(np.isfinite(trailing))[0]
    assert np.flatnonzero(np.isfinite(expanding))[0] == first
    assert not np.allclose(trailing[-10:], expanding[-10:])


def test_unknown_slope_rule_is_refused() -> None:
    signal, residual, members = _panel()
    with pytest.raises(ValueError, match="unknown slope rule"):
        slope(signal, residual, members, "fixed", 5, 30, 10)


def test_forward_compounds_later_rows() -> None:
    r = np.array([[0.1], [0.2], [-0.1], [0.05]])
    out = forward(r, 1, 2)
    assert out[0, 0] == pytest.approx(1.2 * 0.9 - 1)
    assert np.isnan(out[2, 0]) and np.isnan(out[3, 0])


def test_holdout_days_are_none_past_the_end() -> None:
    dates = pd.bdate_range("2024-01-01", periods=5)
    assert holdout_days(dates, dates, 5).sum() == 0
    assert holdout_days(dates, dates, 3).tolist() == [False, False, False, True, True]


# --- the run against phase 5 -------------------------------------------------------------------------


def test_every_model_matches_phase_5(chosen, phase5) -> None:
    _, log = phase5
    blocks = sum(len(e["metrics"]["blocks"]) for e in log if e["config"]["kind"] in ("walk-forward", "holdout walk-forward"))
    dev_blocks = sum(len(e["metrics"]["blocks"]) for e in log if e["config"]["kind"] == "walk-forward")
    assert chosen.checked == blocks + dev_blocks


def test_trailing_paths_reproduce_phase_5_and_keep_their_ids(chosen, phase5) -> None:
    _, log = phase5
    p5 = {path_id(e["config"]) for e in log if e["config"]["kind"] == "path" and e["config"]["rule"] != PARTIAL}
    trailing = [rec for _, rec in chosen.records if rec["kind"] == CHOICE and rec["slope_rule"] == TRAILING]
    assert chosen.reproduced == len(trailing) > 0
    assert {path_id(rec) for rec in trailing} == p5


def test_no_partial_adjustment_and_one_decile_sort_per_forecast(chosen) -> None:
    assert not any(o.rule == PARTIAL for o in chosen.outcomes)
    deciles = [o for o in chosen.outcomes if o.rule == DECILE]
    assert all(parse_label(o.forecast)[1] == TRAILING for o in deciles)


def test_diagnostic_paths_run_through_the_holdout(chosen, phase5) -> None:
    s, _ = phase5
    assert chosen.boundary < len(chosen.full.lab.tables.dates)
    assert all(o.daily.index.max() == pd.Timestamp(s.mc.period.holdout_end) for o in chosen.diagnostic)
    assert all(o.daily.index.max() == pd.Timestamp(s.mc.period.development_end) for o in chosen.outcomes)


def test_refuses_a_model_unlike_phase_5s(phase5) -> None:
    s, log = phase5
    bad = copy.deepcopy(log)
    e = next(e for e in bad if e["config"]["kind"] == "holdout walk-forward")
    e["metrics"]["blocks"][0]["model_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="differs from phase 5's"):
        run_choice(s, market_long(), SLOPE_RULES, bad, {})


def test_refuses_a_trailing_path_unlike_phase_5s(phase5) -> None:
    s, log = phase5
    bad = copy.deepcopy(log)
    e = next(e for e in bad if e["config"]["kind"] == "path" and e["config"]["rule"] != PARTIAL)
    e["metrics"]["turnover"] += 1e-12
    with pytest.raises(ValueError, match="does not reproduce phase 5's metrics: turnover"):
        run_choice(s, market_long(), (TRAILING,), bad, {})


# --- the log and its trials ------------------------------------------------------------------------


def test_only_new_development_paths_are_trials(chosen, phase5) -> None:
    _, log = phase5
    entries = _written(choice_entries(chosen, STATE, LATEST))
    before = trial_sharpes(log)
    after = trial_sharpes(log + entries)
    new = set(after) - set(before)
    expected = {
        path_id(e["config"]) for e in entries
        if e["config"]["kind"] == CHOICE and e["config"]["slope_rule"] != TRAILING and e["metrics"]["identical_to"] is None
    }
    assert new == expected
    assert len(new) == chosen.trials_new
    assert {k: after[k] for k in before} == before        # the trailing paths repeat phase 5's statistics


def test_identical_paths_name_their_trailing_version(chosen) -> None:
    names = {f"{o.name}, {o.book:g}" for o in chosen.outcomes}
    for k, v in chosen.same.items():
        assert k in names
        assert parse_label(v.split(", ")[0])[1] == TRAILING


def test_entries_are_choice_paths_then_diagnostic_paths(chosen) -> None:
    kinds = [rec["kind"] for _, rec in chosen.records]
    assert kinds == [CHOICE] * len(chosen.outcomes) + [DIAGNOSTIC] * len(chosen.diagnostic)


def test_report_rebuilds_byte_for_byte(chosen, tmp_path) -> None:
    log = _written(choice_entries(chosen, STATE, LATEST))
    a, b = tmp_path / "a", tmp_path / "b"
    report.write_choice_report(chosen, log, a)
    report.write_choice_report(chosen, log, b)
    files = sorted(p.name for p in a.iterdir())
    assert "choice.md" in files and "decile_profile.png" in files
    for name in files:
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_a_negative_slope_is_measured_by_period(chosen) -> None:
    assert set(chosen.by_sign["period"]) == {"development", "holdout"}
    assert set(chosen.negative_share["forecast"]) == set(chosen.full_fc.names)


def test_refuses_a_slope_rule_list_without_trailing_first() -> None:
    raw = load_config("paper")
    with pytest.raises(ValueError, match="must start with 'trailing'"):
        PaperConfig.from_dict({**raw, "choice": {"slope_rules": ["floored", TRAILING]}})


# --- the reproduction check on the logged choice paths -------------------------------------------------


@pytest.fixture(scope="module")
def phase6(chosen):
    return _written(choice_entries(chosen, STATE, LATEST))


def _frozen(phase5, phase6, models, forecast: str, rule: str, slope_rule: str, book: float):
    s, log = phase5
    f = Frozen(forecast, rule, slope_rule, book, "")
    strategy = frozen.strategy_from(s, f, frozen.model_files(log, model_horizon(forecast)), models)
    entry = reproduce.logged_entry(phase6, frozen.strategy_config(s, f, log, STATE["price_source"]))
    return strategy, entry


PATHS = [
    ("baseline", "no-trade zone", TRAILING, 500_000.0),
    ("three-day lookback", "optimiser κ = 1", "expanding", 5_000_000.0),
    ("model H=1", "no-trade zone", "floored", 5_000_000.0),
    ("model H=3", "decile sort", TRAILING, 500_000.0),
    ("model H=3", "optimiser κ = 1", "floored", 500_000.0),
]


@pytest.mark.parametrize(("forecast", "rule", "slope_rule", "book"), PATHS)
def test_the_frozen_record_names_a_logged_choice_path(phase5, phase6, models, forecast, rule, slope_rule, book) -> None:
    _, entry = _frozen(phase5, phase6, models, forecast, rule, slope_rule, book)
    assert entry["config"]["kind"] == CHOICE and entry["config"]["slope_rule"] == slope_rule


@pytest.mark.parametrize(("forecast", "rule", "slope_rule", "book"), PATHS)
def test_the_daily_jobs_code_reproduces_every_logged_metric(phase5, phase6, models, forecast, rule, slope_rule, book) -> None:
    """The job's builders, with a model forecast from the saved files, give the choice run's path exactly."""
    strategy, entry = _frozen(phase5, phase6, models, forecast, rule, slope_rule, book)
    assert reproduce.check(market_long(), strategy, entry) == []


def test_a_code_change_the_frozen_record_cannot_see_fails_the_check(phase5, phase6, models, monkeypatch) -> None:
    strategy, entry = _frozen(phase5, phase6, models, "baseline", "no-trade zone", TRAILING, 500_000.0)
    real = day.expected_move
    monkeypatch.setattr(day, "expected_move", lambda *a: real(*a) * 1.5)        # a calibration that overstates the move
    problems = reproduce.check(market_long(), strategy, entry)
    assert problems and all(" logged, " in p for p in problems)


def test_a_strategy_the_choice_run_did_not_log_is_refused(phase5, phase6, models) -> None:
    s, log = phase5
    f = Frozen("baseline", "decile sort", "floored", 500_000.0, "")     # the decile sort ignores the slope: logged once
    with pytest.raises(ValueError, match="no choice path"):
        reproduce.logged_entry(phase6, frozen.strategy_config(s, f, log, STATE["price_source"]))
    with pytest.raises(ValueError, match="no choice path"):
        reproduce.logged_entry(phase6, frozen.strategy_config(s, replace(f, slope_rule=TRAILING), log, "another source"))


def test_a_changed_model_file_stops_the_frozen_strategy_loading(phase5, models, tmp_path) -> None:
    s, log = phase5
    files = frozen.model_files(log, 1)
    for m in files:
        shutil.copyfile(models / m["file"], tmp_path / m["file"])
    (tmp_path / files[-1]["file"]).write_text((tmp_path / files[-1]["file"]).read_text() + "\n")
    with pytest.raises(ModelHashError, match=files[-1]["file"]):
        frozen.strategy_from(s, Frozen("model H=1", "decile sort", TRAILING, 500_000.0, ""), files, tmp_path)
