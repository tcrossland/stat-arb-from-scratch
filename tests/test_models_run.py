"""The phase 5 development runner on the synthetic market: end to end, its refusals, and its trial identities."""

from __future__ import annotations

import dataclasses
import hashlib
from types import SimpleNamespace

import pandas as pd
import pytest

from helpers import MARKET_CAL, MARKET_ETFS
from runner_helpers import DEV_END, market_long, market_settings
from statarb.backtest import cost_run
from statarb.backtest.cost_run import headline
from statarb.backtest.trials import path_id
from statarb.models import report
from statarb.models.config import RULES, ModelsConfig
from statarb.models.run import (
    DECILE,
    OPTIMISER,
    PARTIAL,
    ZONE,
    Outcome,
    build_development_lab,
    check_development,
    log_entries,
    model_forecast,
    path_record,
    run_development,
)
from statarb.portfolio import run as portfolio_run
from statarb.portfolio.paths import DECILE as PHASE_4_DECILE
from statarb.portfolio.paths import optimiser_specs
from statarb.signals.tables import build_tables

_long, _settings = market_long, market_settings


@pytest.fixture(scope="module")
def developed(tmp_path_factory):
    models = tmp_path_factory.mktemp("models")
    s = _settings()
    s.validate()
    return s, models, run_development(s, _long(), models, {})


# --- end to end ------------------------------------------------------------------------------------


@pytest.mark.slow
def test_nothing_reaches_past_the_development_end(developed) -> None:
    _, _, res = developed
    end = MARKET_CAL[DEV_END]
    assert res.plab.lab.tables.dates[-1] == end
    for run in res.fc.runs.values():
        assert all(f.fold.test_stop <= DEV_END + 1 for f in run.walk.fits)
    for o in res.outcomes:
        assert o.daily.index.max() <= end


@pytest.mark.slow
def test_every_path_runs_over_the_same_dates(developed) -> None:
    s, _, res = developed
    first = {o.daily.index.min() for o in res.outcomes}
    last = {o.daily.index.max() for o in res.outcomes}
    assert first == {res.plab.lab.tables.dates[res.fc.start]} and len(last) == 1
    assert res.fc.start > 150                                    # the model's forecast starts with the first block, then calibrates
    forecasts = [*s.mc.runs.variants, *(model_forecast(H) for H in s.mc.target.horizons)]
    expected = {(f, r, b) for f in forecasts for r in RULES for b in s.pc.run.book_sizes}
    assert {(o.forecast, o.rule, o.book) for o in res.outcomes} == expected


@pytest.mark.slow
def test_models_are_saved_with_their_hashes(developed) -> None:
    _, models, res = developed
    blocks = [b for config, metrics in res.logged.walk_forward.values() for b in metrics["blocks"]]
    assert len(blocks) == sum(len(r.walk.fits) for r in res.fc.runs.values())
    for b in blocks:
        assert hashlib.sha256((models / b["model_file"]).read_bytes()).hexdigest() == b["model_sha256"]
        assert len(b["grid"]) == 4 and b["chosen"] in b["grid"]


@pytest.mark.slow
def test_log_has_a_walk_forward_entry_per_horizon_then_every_path(developed) -> None:
    s, _, res = developed
    entries = log_entries(res.outcomes, res.logged, s.mc, s.cfg, {"git_commit": None}, pd.Timestamp("2026-01-01", tz="UTC").to_pydatetime())
    kinds = [e["config"]["kind"] for e in entries]
    assert kinds == ["walk-forward"] * len(s.mc.target.horizons) + ["path"] * len(res.outcomes)
    ids = res.logged.walk_forward_ids
    for e in entries[len(ids):]:
        model = e["config"]["model"]
        assert (model is None) == (e["config"]["signal"] != "model")
        if model is not None:
            assert model["walk_forward"] == ids[model["horizon"]]
    assert "runs" not in entries[0]["config"]["models"] and "partial_adjustment" not in entries[0]["config"]["models"]   # neither changes a model


@pytest.mark.slow
def test_model_paths_are_new_trials_and_variant_paths_are_not(developed) -> None:
    s, _, res = developed
    trials = res.verdict.groupby("book")["trials"].first()
    rules = len(s.mc.runs.rules)
    assert (trials == rules * len(s.mc.target.horizons) + rules * len(s.mc.runs.variants)).all()   # no earlier phase in this test
    earlier = {path_id(rec): 0.0 for o, rec in zip(res.outcomes, res.logged.paths, strict=True) if not o.forecast.startswith("model")}
    assert len(earlier) == rules * len(s.mc.runs.variants)


@pytest.mark.slow
def test_report_rebuilds_byte_for_byte(developed, tmp_path) -> None:
    _, _, res = developed
    a, b = tmp_path / "a", tmp_path / "b"
    report.write_report(res, a)
    report.write_report(res, b)
    for path in a.iterdir():
        assert path.read_bytes() == (b / path.name).read_bytes(), path.name
    text = (a / "ml.md").read_text()
    assert "## Against the bar" in text and "Dispersion over the whole stock axis" in text


@pytest.mark.slow
def test_the_run_reproduces(developed, tmp_path) -> None:
    s, _, res = developed
    again = run_development(s, _long(), tmp_path, {})
    first = [b["model_sha256"] for _, m in res.logged.walk_forward.values() for b in m["blocks"]]
    second = [b["model_sha256"] for _, m in again.logged.walk_forward.values() for b in m["blocks"]]
    assert first == second
    for o, p in zip(res.outcomes, again.outcomes, strict=True):
        assert o.metrics == p.metrics


@pytest.mark.slow
def test_partial_adjustment_matches_the_optimisers_turnover_over_the_whole_grid(developed) -> None:
    s, _, res = developed
    optimiser = {(o.forecast, o.book): o.metrics["turnover"] for o in res.outcomes if o.rule == OPTIMISER and o.kappa == s.mc.runs.cost_multipliers[0]}
    partial = [o for o in res.outcomes if o.rule == PARTIAL]
    assert len(partial) == len(optimiser)
    for o in partial:
        m = o.metrics
        tried = {float(r): x for r, x in m["turnover_by_rate"].items()}
        assert len(tried) == round(1 / s.mc.partial_adjustment.rate_step)
        target = optimiser[(o.forecast, o.book)]
        assert m["matched_turnover"] == target and m["turnover"] == tried[m["trade_rate"]]
        assert abs(m["turnover"] - target) == min(abs(x - target) for x in tried.values())


@pytest.mark.slow
def test_dispersion_defect_is_measured_on_a_late_starter(developed) -> None:
    _, _, res = developed
    # Every synthetic stock's residuals start on day 20: before it, only the whole-axis definition has a value.
    assert res.defect["days_differ"] == 0 and res.defect["days_one_defined"] == 19
    long = _long()
    r = long["residuals"]
    late = r["ticker"] == "S03"
    long["residuals"] = r.loc[~late | (r["date"] >= MARKET_CAL[200])]
    from statarb.models.run import dispersion_defect

    plab = build_development_lab(long, _settings())
    d = dispersion_defect(plab.lab.tables)
    assert d["first_differ"] == str(MARKET_CAL[20].date()) and d["last_differ"] == str(MARKET_CAL[199].date())
    assert d["days_differ"] == 180 and d["largest_difference"] > 0


# --- refusals ---------------------------------------------------------------------------------------


def test_refuses_tables_past_the_development_end() -> None:
    s = _settings()
    tables = build_tables(*_long().values(), "SPY", MARKET_ETFS)
    with pytest.raises(ValueError, match="holdout"):
        check_development(tables, s.mc.period)
    assert build_development_lab(_long(), s).lab.tables.dates[-1] == MARKET_CAL[DEV_END]


def test_refuses_partial_adjustment_without_the_optimiser() -> None:
    raw = dataclasses.asdict(_settings().mc)
    raw["runs"]["rules"] = ["decile sort", "partial adjustment"]
    with pytest.raises(ValueError, match="optimiser must run too"):
        ModelsConfig.from_dict(raw)
    raw["runs"]["rules"] = list(RULES)
    raw["partial_adjustment"]["rate_step"] = 0.3
    with pytest.raises(ValueError, match="divide 1"):
        ModelsConfig.from_dict(raw)


def test_refuses_a_development_end_in_the_holdout() -> None:
    raw = dataclasses.asdict(_settings().mc)
    raw["period"]["development_end"] = raw["period"]["holdout_start"]
    with pytest.raises(ValueError, match="development_end"):
        ModelsConfig.from_dict(raw)


@pytest.mark.parametrize(
    ("runs", "match"),
    [
        ({"variants": ("three-day lookback",)}, "headline variant"),
        ({"variants": ("baseline", "missing")}, "not a"),
        ({"cost_multipliers": (2.0, 1.0)}, "first cost multiplier"),
    ],
)
def test_refuses_runs_outside_the_earlier_phases(runs, match) -> None:
    with pytest.raises(ValueError, match=match):
        _settings(**runs).validate()


# --- trial identities -------------------------------------------------------------------------------


def test_variant_paths_share_their_phase_3_and_4_ids() -> None:
    """A variant's path through the decile sort, the zone or the optimiser is the trial phases 3 and 4 logged."""
    s = _settings()
    head = headline(s.ccfg)
    variant = dict(cost_run.variants(s.cfg, s.ccfg))["baseline"]
    book = s.pc.run.book_sizes[0]
    first, last = MARKET_CAL[100], MARKET_CAL[DEV_END]
    lab = SimpleNamespace(ccfg=s.ccfg, cfg=s.cfg)

    def ours(rule, kappa=None):
        o = Outcome("baseline", rule, kappa, book, pd.DataFrame(), {})
        return path_id(path_record(o, s.cfg, s.ccfg, s.pc, s.mc, variant, {}, first, last))

    zone_3 = cost_run.record(SimpleNamespace(variant=variant, name="baseline", book=book, setting=head, no_trade=True), lab)
    assert ours(ZONE) == path_id(zone_3)
    plab = SimpleNamespace(pc=s.pc, lab=lab, variants={"baseline": variant})
    head_spec = optimiser_specs(s.pc)[0]
    decile_spec = dataclasses.replace(head_spec, name=PHASE_4_DECILE, group="decile", risk=None, risk_aversion=None, cost_multiplier=None, min_trade_dollars=None, re_solve=None)
    for rule, spec in ((DECILE, decile_spec), (OPTIMISER, head_spec)):
        phase_4 = portfolio_run.record(SimpleNamespace(spec=spec, book=book, setting=head), plab)
        assert ours(rule, 1.0 if rule == OPTIMISER else None) == path_id(phase_4)
    model = Outcome(model_forecast(1), DECILE, None, book, pd.DataFrame(), {})
    assert path_id(path_record(model, s.cfg, s.ccfg, s.pc, s.mc, variant, {1: "wf"}, first, last)) != ours(DECILE)
    assert ours(PARTIAL) not in {ours(DECILE), ours(ZONE), ours(OPTIMISER, 1.0)}          # partial adjustment is a new trial
