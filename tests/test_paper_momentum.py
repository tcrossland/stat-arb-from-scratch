"""Decision record 0010's momentum forward run: its strategy steps as its backtest, its config, records and job, on the
synthetic market and a copy of the repository's config."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
import shutil
import subprocess
import tomllib
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_CAL
from runner_helpers import market_long, market_settings
from statarb.backtest import experiments
from statarb.backtest.rules import DecileRule
from statarb.backtest.trials import path_id
from statarb.config import load_config, repo_root
from statarb.io import write_parquet
from statarb.models.run import build_period_lab
from statarb.paper import daily, frozen, ledger, momentum
from statarb.paper.config import DECILE, load_paper_config
from statarb.paper.day import (
    MomentumRule,
    Strategy,
    ledger_day,
    momentum_strategy,
    session_inputs,
    strategy_panels,
)
from statarb.signals.base import Scores
from statarb.signals.tables import cut_after
from test_paper_day import META, assert_matches_backtest, live_run

NY = ZoneInfo("America/New_York")
TOTAL = MomentumRule("momentum", 40, 5, 0.1, 5)          # a window the synthetic market's 320 days can fill
RESIDUAL = MomentumRule("residual_momentum", 40, 5, 0.1, 5)


@pytest.fixture(scope="module")
def settings():
    return market_settings()


@pytest.fixture(scope="module")
def long():
    return market_long()


def _first(settings, long, strategy) -> int:
    return momentum.first_book(build_period_lab(long, settings, MARKET_CAL[-1]), strategy)


# --- the strategy ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("rule", [TOTAL, RESIDUAL], ids=["total-return", "residual"])
def test_a_run_of_sessions_gives_the_backtests_path(settings, long, rule) -> None:
    strategy = momentum_strategy(settings, rule, 500_000)
    first = _first(settings, long, strategy) + 2
    assert_matches_backtest(long, strategy, first, live_run(long, strategy, first, 8))


@pytest.mark.parametrize("rule", [TOTAL, RESIDUAL], ids=["total-return", "residual"])
def test_the_decision_is_the_decile_sort_of_the_signal_with_no_calibration(settings, long, rule) -> None:
    strategy = momentum_strategy(settings, rule, 500_000)
    start = _first(settings, long, strategy)
    p = strategy_panels(long, MARKET_CAL[-1], MARKET_CAL[start], strategy)
    tables = p.plab.lab.tables
    signal = rule.make().scores(tables).score
    np.testing.assert_array_equal(p.signal, signal)
    expected = DecileRule(rule.decile, rule.holding_days).targets(Scores(signal), tables.members, start, len(tables.hedges))
    np.testing.assert_array_equal(p.targets, expected)
    assert np.isnan(p.targets[:start]).all() and np.isfinite(p.targets[start:]).all()
    assert np.isnan(p.slopes).all()
    n = len(tables.stocks)
    assert np.isnan(p.move[:, :n]).all() and (p.move[:, n:] == 0).all()


def test_a_ledger_day_records_no_expected_move_and_no_slope(settings, long) -> None:
    strategy = momentum_strategy(settings, TOTAL, 500_000)
    first = _first(settings, long, strategy)
    frame, _ = ledger_day(session_inputs(long, MARKET_CAL[first], MARKET_CAL[first], strategy), ledger.Carry.flat(()), META)
    hedge = frame["ticker"].isin({settings.market, *settings.sector_etfs.values()})
    assert frame.loc[~hedge, "expected_move"].isna().all() and (frame.loc[hedge, "expected_move"] == 0).all()
    assert frame["slope"].isna().all()
    assert (frame["target"] > 0).sum() == (frame["target"] < 0).sum() > 0
    assert ledger.check_day(frame, None) == []


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"forecast": "raw", "momentum": MomentumRule("raw", 40, 5, 0.1, 5)}, "momentum rule runs"),
        ({"momentum": MomentumRule("momentum", 40, 5, 0.6, 5)}, "decile"),
        ({"momentum": MomentumRule("momentum", 40, 5, 0.1, 0)}, "holding period"),
        ({"slope_rule": "floored"}, "no slope rule"),
        ({"rule": "no-trade zone"}, "decile sort"),
        ({"forecast": "residual_momentum"}, "decile sort"),
    ],
)
def test_refuses_a_momentum_strategy_it_cannot_run(settings, change, match) -> None:
    fields = {"settings": settings, "forecast": "momentum", "rule": DECILE, "kappa": None, "slope_rule": "", "book_size": 1.0, "momentum": TOTAL}
    with pytest.raises(ValueError, match=match):
        Strategy(**{**fields, **change}).validate()


def test_the_note_names_the_signal_and_leaves_out_the_slope(settings, long) -> None:
    strategy = momentum_strategy(settings, RESIDUAL, 500_000)
    first = _first(settings, long, strategy)
    frame, _ = ledger_day(session_inputs(long, MARKET_CAL[first], MARKET_CAL[first], strategy), ledger.Carry.flat(()), META)
    text = daily.note_text(frame, strategy, daily.Snapshot("2026-01-01", {}), "f00d", "pushed: abc")
    assert text.startswith(f"# Paper trading, residual_momentum: {MARKET_CAL[first]:%Y-%m-%d}")
    assert "statarb.paper.momentum daily" in text and "Calibration slope" not in text


# --- the run's config -----------------------------------------------------------------------------------


def test_the_config_is_record_0010s_and_shares_the_reversal_runs_sessions() -> None:
    cfg = momentum.load_momentum_config(repo_root())
    run = load_paper_config(repo_root()).run
    assert (cfg.run.first_session, cfg.run.calendar, cfg.run.run_time) == (run.first_session, run.calendar, run.run_time)
    assert cfg.last_before == run.last_before
    assert (cfg.run.book_size, cfg.run.window_days, cfg.run.skip_days, cfg.run.decile, cfg.run.holding_days) == (5_000_000, 252, 21, 0.1, 21)
    assert [(p.name, p.signal) for p in cfg.runs] == [("total-return", "momentum"), ("residual", "residual_momentum")]
    assert "momentum_forward" not in frozen.FILES            # the reversal run's frozen record never sees this file


@pytest.mark.parametrize(
    ("old", "new", "error"),
    [
        ("holding_days = 21", "holding_days = 21\nextra = 1", ValueError),
        ('name = "residual"', 'name = "total-return"', ValueError),
        ('name = "residual"', 'name = "Residual"', ValueError),
        ('signal = "residual_momentum"', 'signal = "residual"', ValueError),
        ("first_session = 2026-11-16", 'first_session = "2026-11-16"', TypeError),
    ],
)
def test_a_bad_config_is_refused(old, new, error) -> None:
    text = (repo_root() / "config" / f"{momentum.NAME}.toml").read_text()
    assert text.count(old) == 1
    data = tomllib.loads(text.replace(old, new))
    with pytest.raises(error):
        momentum.MomentumConfig.from_dict(data)


def test_each_path_and_its_skip_is_a_trial_of_its_own(settings) -> None:
    cfg = momentum.load_momentum_config(repo_root())
    day = pd.Timestamp("2017-01-03")
    total, residual = (momentum.path_config(settings, cfg, spec, day, day) for spec in cfg.runs)
    assert total["source"] == "raw" and residual["source"] == "residual"
    assert path_id(total) != path_id(residual)
    assert path_id({**total, "skip_days": 0}) != path_id(total)
    assert path_id({**total, "book_size": 1.0, "name": "x", "first_date": "2020-01-02"}) == path_id(total)


def test_the_development_backtest_reads_no_day_after_the_cut_and_starts_at_the_first_book(settings, long) -> None:
    cut = MARKET_CAL[250]
    cfg = momentum.MomentumConfig(
        momentum.RunSettings((cut + pd.Timedelta(days=1)).date(), "XNYS", dt.time(6, 0), 500_000, 40, 5, 0.1, 5),
        momentum.Paths("data/paper-momentum"),
        (momentum.PathSpec("total-return", "momentum", ""), momentum.PathSpec("residual", "residual_momentum", "")),
    )
    paths = momentum.development_paths(long, settings, cfg)
    for (config, metrics), spec in zip(paths, cfg.runs, strict=True):
        assert config["last_date"] == str(cut.date())
        start = _first(settings, cut_after(long, cut), cfg.strategy(settings, spec))
        assert config["first_date"] == config["start"] == str(MARKET_CAL[start].date())
        assert metrics["gross_sharpe"] is not None
    assert momentum.development_paths(cut_after(long, cut), settings, cfg) == paths      # the later days are never read


def test_the_repository_matches_its_momentum_frozen_records() -> None:
    assert momentum.check(repo_root()) == []
    for spec in momentum.load_momentum_config(repo_root()).runs:
        assert momentum.frozen_entry(repo_root(), spec)["config_id"]


# --- the backtest log and the frozen records, on a copy of the config -----------------------------------


@pytest.fixture
def root(tmp_path):
    """A copy of the repository's config with no record frozen yet, and no log."""
    shutil.copytree(repo_root() / "config", tmp_path / "config")
    path = tmp_path / "config" / f"{momentum.NAME}.toml"
    path.write_text(re.sub(r'^config_hash = "[0-9a-f]*"$', 'config_hash = ""', path.read_text(), flags=re.MULTILINE))
    return tmp_path


def _log_paths(root, settings=None) -> None:
    """Log entries for each path as the backtest would, with made-up metrics: the records only need them to exist."""
    from statarb.models.run import load_settings

    s = settings or load_settings(root)
    cfg = momentum.load_momentum_config(root)
    day = pd.Timestamp("2017-03-01")
    entries = [
        experiments.entry(momentum.path_config(s, cfg, spec, day, pd.Timestamp("2026-11-13")), {"gross_sharpe": 0.1}, 0,
                          {"price_source": "alpaca"}, dt.datetime(2026, 11, 26, tzinfo=dt.UTC))
        for spec in cfg.runs
    ]
    experiments.append(frozen.reports_dir(root) / momentum.LOG, entries)


SIGNALS = {"total-return": "momentum", "residual": "residual_momentum"}


def _set_hashes(root, hashes: dict[str, str]) -> None:
    path = root / "config" / f"{momentum.NAME}.toml"
    text = path.read_text()
    for name, digest in hashes.items():
        old = f'name = "{name}"\nsignal = "{SIGNALS[name]}"\nconfig_hash = ""'
        assert text.count(old) == 1
        text = text.replace(old, old.replace('config_hash = ""', f'config_hash = "{digest}"'))
    path.write_text(text)


def test_a_record_is_written_only_after_its_path_is_logged(root) -> None:
    with pytest.raises(ValueError, match="run the backtest first"):
        momentum.write(root)
    _log_paths(root)
    hashes = momentum.write(root)
    assert set(hashes) == {"total-return", "residual"} and len(set(hashes.values())) == 2
    assert momentum.check(root) == [f"{n}: config_hash is not set in config/{momentum.NAME}.toml" for n in ("total-return", "residual")]
    _set_hashes(root, hashes)
    assert momentum.check(root) == []
    assert momentum.write(root) == hashes                                  # rewriting the same freeze is allowed
    stored = json.loads(momentum.record_path(root, momentum.load_momentum_config(root).runs[0]).read_text())
    assert stored["strategy"]["signal"] == "momentum" and "start" not in stored["strategy"]
    assert all("config_hash" not in r for r in stored["momentum"]["runs"])


def test_a_change_to_a_setting_or_a_shared_file_is_named(root) -> None:
    _log_paths(root)
    _set_hashes(root, momentum.write(root))
    path = root / "config" / f"{momentum.NAME}.toml"
    path.write_text(path.read_text().replace("holding_days = 21", "holding_days = 20"))
    problems = momentum.check(root)
    assert "total-return: changed since the freeze: momentum.run.holding_days" in problems
    assert "residual: changed since the freeze: strategy.holding_days" in problems
    path.write_text(path.read_text().replace("holding_days = 20", "holding_days = 21"))
    costs = root / "config" / "costs.toml"
    costs.write_text(costs.read_text().replace("[borrow]", "[borrow]\n# a comment is not a change", 1))
    assert momentum.check(root) == []
    path.write_text(path.read_text().replace("skip_days = 21", "skip_days = 20"))
    with pytest.raises(ValueError, match="run the backtest first"):       # a changed setting is another, unlogged path
        momentum.write(root)
    _log_paths(root)                                                       # logged, it still cannot replace the freeze
    with pytest.raises(frozen.FrozenConfigError, match="already"):
        momentum.write(root)


def test_a_refused_write_writes_no_record(root) -> None:
    _log_paths(root)
    path = root / "config" / f"{momentum.NAME}.toml"
    path.write_text(path.read_text().replace('signal = "residual_momentum"\nconfig_hash = ""', 'signal = "residual_momentum"\nconfig_hash = "0000000000000000"'))
    with pytest.raises(frozen.FrozenConfigError, match="residual: config_hash is already"):
        momentum.write(root)
    assert not any(momentum.record_path(root, spec).exists() for spec in momentum.load_momentum_config(root).runs)


def test_the_frozen_entry_is_the_logged_backtest(root) -> None:
    _log_paths(root)
    _set_hashes(root, momentum.write(root))
    cfg = momentum.load_momentum_config(root)
    entry = momentum.frozen_entry(root, cfg.runs[1])
    assert entry["config"]["signal"] == "residual_momentum" and entry["config"]["kind"] == momentum.KIND


def test_an_overlay_is_refused(root, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("STATARB_CONFIG_OVERLAY", str(tmp_path))
    assert "overlay" in momentum.check(root)[0]
    with pytest.raises(frozen.FrozenConfigError, match="overlay"):
        momentum.write(root)


def test_the_backtest_is_logged_once_and_only_from_a_clean_tree(root, settings, long, monkeypatch) -> None:
    cfg = momentum.MomentumConfig(
        momentum.RunSettings(MARKET_CAL[251].date(), "XNYS", dt.time(6, 0), 500_000, 40, 5, 0.1, 5),
        momentum.Paths("data/paper-momentum"),
        (momentum.PathSpec("total-return", "momentum", ""), momentum.PathSpec("residual", "residual_momentum", "")),
    )
    monkeypatch.setattr(momentum, "load_momentum_config", lambda _root: cfg)
    monkeypatch.setattr(momentum, "load_settings", lambda _root: settings)
    state = {"git_commit": "c0ffee", "git_dirty": True, "config_overlay": None, "price_source": "alpaca", "price_snapshot": "2026-11-16"}
    monkeypatch.setattr(experiments, "run_state", lambda _root: dict(state))
    now = dt.datetime(2026, 11, 26, tzinfo=dt.UTC)
    with pytest.raises(RuntimeError, match="uncommitted"):
        momentum.log_backtest(root, long, now)
    state["git_dirty"] = False
    entries = momentum.log_backtest(root, long, now)
    assert [e["config"]["kind"] for e in entries] == [momentum.KIND] * 2
    assert experiments.read(frozen.reports_dir(root) / momentum.LOG) == entries
    with pytest.raises(RuntimeError, match="already logged"):
        momentum.log_backtest(root, long, now)
    moved = dataclasses.replace(cfg, run=dataclasses.replace(cfg.run, first_session=MARKET_CAL[261].date()))
    monkeypatch.setattr(momentum, "load_momentum_config", lambda _root: moved)
    monkeypatch.setattr(momentum, "development_paths", lambda *_: pytest.fail("ran before refusing"))
    with pytest.raises(RuntimeError, match="already logged"):              # other dates are the same path
        momentum.log_backtest(root, long, now)
    assert len(experiments.read(frozen.reports_dir(root) / momentum.LOG)) == 2


# --- the daily job --------------------------------------------------------------------------------------


def test_a_catch_up_run_steps_a_momentum_ledger(tmp_path, settings, long) -> None:
    strategy = momentum_strategy(settings, TOTAL, 500_000)
    first = MARKET_CAL[_first(settings, long, strategy)]
    sessions = MARKET_CAL[MARKET_CAL >= first]
    nxt = (sessions[4] + pd.Timedelta(days=1)).date()
    job = daily.Job(
        now=dt.datetime(nxt.year, nxt.month, nxt.day, 7, 0, tzinfo=NY), first=first, sessions=sessions, run_time=dt.time(6, 0),
        strategy=strategy, ledger_root=tmp_path / "ledger", notes_root=tmp_path / "notes", runs_log=tmp_path / "runs.jsonl",
        config_hash="0123456789abcdef", git={"git_commit": "c0ffee", "git_dirty": False},
        reproduce=lambda: daily.Reproduction("f00d"), snapshot=lambda: daily.Snapshot("2026-01-01", long),
        backup=lambda: daily.backup_.BackupResult("not configured", "x"),
    )
    result = daily.run_job(job)
    assert result.status == "done" and list(result.processed) == list(sessions[:5])
    assert ledger.check(tmp_path / "ledger") == []
    assert all(p.read_text().startswith("# Paper trading, momentum:") for p in (tmp_path / "notes").iterdir())
    # The same run with each session's snapshot given by the hook: two snapshots, and a stop at the fifth session.
    recorded = {d: ("2026-01-01" if i < 2 else "2026-01-02") for i, d in enumerate(sessions[:4])}
    hooked = dataclasses.replace(
        job, ledger_root=tmp_path / "hooked", notes_root=tmp_path / "hooked-notes", runs_log=tmp_path / "hooked.jsonl",
        snapshot=lambda: pytest.fail("the hook replaces the run day's snapshot"),
        snapshot_for=lambda d: daily.Snapshot(recorded[d], long) if d in recorded else "the reversal run has not recorded it",
    )
    stopped = daily.run_job(hooked)
    assert stopped.status == "incomplete" and list(stopped.processed) == list(sessions[:4]) and stopped.snapshot == "2026-01-02"
    assert f"stopped at {sessions[4]:%Y-%m-%d}: the reversal run has not recorded it" in stopped.message
    assert [str(ledger.read_day(tmp_path / "hooked", d)["snapshot"].iloc[0]) for d in sessions[:4]] == list(recorded.values())
    for d in sessions[:4]:
        pd.testing.assert_frame_equal(ledger.read_day(tmp_path / "hooked", d).drop(columns="snapshot"),
                                      ledger.read_day(tmp_path / "ledger", d).drop(columns="snapshot"))


def test_the_job_waits_for_the_snapshot_and_gives_up_at_the_deadline() -> None:
    clock = {"t": 0.0}
    slept = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock["t"] += seconds

    ready = iter([False, False, True])
    assert momentum.wait_for(lambda: next(ready), 100, 30, lambda: clock["t"], sleep) is True
    assert slept == [30, 30]
    clock["t"], slept[:] = 0.0, []
    assert momentum.wait_for(lambda: False, 100, 30, lambda: clock["t"], sleep) is False
    assert slept == [30, 30, 30, 30] and clock["t"] >= 100


def test_shared_work_is_done_once() -> None:
    calls = []
    get = momentum.once(lambda: calls.append(1) or len(calls))
    assert (get(), get(), calls) == (1, 1, [1])


def test_the_jobs_leave_each_others_notes_out_of_git_dirty(tmp_path) -> None:
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "start")
    reports = tmp_path / "reports"
    for folder in (daily.NOTES, momentum.NOTES / "residual"):
        (reports / folder).mkdir(parents=True)
        (reports / folder / "2026-11-16.md").write_text("note")
    assert daily.job_git_state(tmp_path, reports)["git_dirty"] is False
    (reports / daily.FORWARD / "frozen-residual.json").write_text("{}")               # a frozen record is not a job's output
    assert daily.job_git_state(tmp_path, reports)["git_dirty"] is True
    (reports / daily.FORWARD / "frozen-residual.json").unlink()
    (tmp_path / "code.py").write_text("x = 1")
    assert daily.job_git_state(tmp_path, reports)["git_dirty"] is True


def _reversal_day(root, date: pd.Timestamp, snapshot: str) -> None:
    frame = pd.DataFrame({"date": [date], "ticker": ["S00"], "snapshot": [snapshot]})
    write_parquet(frame, ledger.path_for(momentum.reversal_ledger(root), date), ["ticker"])


def _complete(raw, root, name: str) -> None:
    named = raw / load_config("data", root)["source"]["name"] / name
    named.mkdir(parents=True)
    (named / "manifest.json").write_text("{}")


def test_each_session_is_read_from_the_snapshot_the_reversal_ledger_records(root, tmp_path, monkeypatch) -> None:
    raw = tmp_path / "raw"
    monkeypatch.setenv("STATARB_RAW", str(raw))
    built = []
    monkeypatch.setattr(daily, "daily_snapshot", lambda r, day, download, log, processed: built.append((day, download, processed)) or daily.Snapshot(str(day), {}))
    cfg = momentum.load_momentum_config(root)
    days = pd.DatetimeIndex(["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"])
    for d, name in zip(days[:3], ("2026-11-18", "2026-11-18", "2026-11-19"), strict=True):
        _reversal_day(root, d, name)
    _complete(raw, root, "2026-11-18")
    waits = []
    monkeypatch.setattr(momentum, "wait_for", lambda ready, wait, poll: waits.append(ready()) or ready())
    for_session = momentum.session_snapshots(root, cfg, daily.quiet)
    assert for_session(days[0]).name == for_session(days[1]).name == "2026-11-18"
    assert built == [(dt.date(2026, 11, 18), False, momentum.paper_dir(root, cfg) / "processed")]          # built once, never downloaded
    assert for_session(days[2]) == "the reversal run read snapshot 2026-11-19, which the raw store does not hold complete"
    _complete(raw, root, "2026-11-19")
    assert for_session(days[2]).name == "2026-11-19"
    assert waits == []                                                    # recorded sessions are never waited for
    assert for_session(days[3]) == for_session(days[3]) == "the reversal run has not recorded it"
    assert waits == [False]                                               # waited for once, not again for the second path
    assert for_session(days[0]).name == "2026-11-18" and len(built) == 3  # the tables in use are kept, the earlier rebuilt


def _job_settings(settings, long) -> momentum.MomentumConfig:
    first = max(_first(settings, long, momentum_strategy(settings, rule, 500_000)) for rule in (TOTAL, RESIDUAL))
    return momentum.MomentumConfig(
        momentum.RunSettings(MARKET_CAL[first].date(), "XNYS", dt.time(6, 0), 500_000, 40, 5, 0.1, 5),
        momentum.Paths("data/paper-momentum"),
        (momentum.PathSpec("total-return", "momentum", "aaaa"), momentum.PathSpec("residual", "residual_momentum", "bbbb")),
    )


@pytest.fixture
def job_root(root, settings, long, monkeypatch):
    """`run_daily` on the synthetic market: the config, records and reproduction stubbed, the rest as the job runs it."""
    cfg = _job_settings(settings, long)
    monkeypatch.setattr(momentum, "load_momentum_config", lambda _root: cfg)
    monkeypatch.setattr(momentum, "load_settings", lambda _root: settings)
    monkeypatch.setattr(momentum, "require", lambda _root: None)
    monkeypatch.setattr(momentum, "frozen_entry", lambda _root, spec: {"config_id": f"entry-{spec.name}"})
    monkeypatch.setattr(momentum, "reference_tables", lambda *_: {})
    monkeypatch.setattr(momentum.reproduce, "check", lambda *_: [])
    monkeypatch.setattr(daily, "job_git_state", lambda *_: {"git_commit": "c0ffee", "git_dirty": False})
    calls = []
    monkeypatch.setattr(momentum, "session_snapshots", lambda *_: lambda d: calls.append(d) or daily.Snapshot("2026-01-01", long))
    monkeypatch.delenv(momentum.REMOTE_ENV, raising=False)
    monkeypatch.delenv(daily.backup_.REMOTE_ENV, raising=False)
    return root, cfg, calls


def _now_after(cfg, sessions_ahead: int) -> dt.datetime:
    """The morning after the exchange's session `sessions_ahead` of the run, so that many and one more are due."""
    sessions = daily.calendar_for(cfg.run.calendar, cfg.first, MARKET_CAL[-1].date())
    day = (sessions[sessions_ahead] + pd.Timedelta(days=1)).date()
    return dt.datetime(day.year, day.month, day.day, 7, 0, tzinfo=NY)


def _statuses(root, cfg, name: str) -> list[str]:
    return [r["status"] for r in experiments.read(momentum.paper_dir(root, cfg) / name / "runs.jsonl")]


def test_the_job_steps_each_path_in_folders_of_its_own(job_root) -> None:
    root, cfg, calls = job_root
    results = momentum.run_daily(root, _now_after(cfg, 2), 0.0)
    assert [(name, r.status, len(r.processed)) for name, r in results] == [("total-return", "done", 3), ("residual", "done", 3)]
    for spec in cfg.runs:
        folder = momentum.paper_dir(root, cfg) / spec.name
        assert len(ledger.dates(folder / "ledger")) == 3 and ledger.check(folder / "ledger") == []
        assert {str(ledger.read_day(folder / "ledger", d)["config_hash"].iloc[0]) for d in ledger.dates(folder / "ledger")} == {spec.config_hash}
        notes = frozen.reports_dir(root) / momentum.NOTES / spec.name
        assert len(list(notes.iterdir())) == 3
        record = experiments.read(folder / "runs.jsonl")[-1]
        assert record["reproduced"] == f"entry-{spec.name}" and record["backup"].startswith("not configured")
    assert len(calls) == 6                                                 # each path asks for each session's snapshot


def test_a_run_with_nothing_due_reads_no_snapshot(job_root) -> None:
    root, cfg, calls = job_root
    early = dt.datetime.combine(cfg.run.first_session, dt.time(12, 0), tzinfo=NY)
    assert [r.status for _, r in momentum.run_daily(root, early, 0.0)] == ["nothing due", "nothing due"]
    assert calls == []


def test_a_path_that_fails_is_recorded_alone_and_the_other_still_runs(job_root, monkeypatch) -> None:
    root, cfg, _ = job_root

    def check(_tables, strategy, _entry):
        if strategy.forecast == "momentum":
            raise OSError("disk full")
        return []

    monkeypatch.setattr(momentum.reproduce, "check", check)
    with pytest.raises(OSError, match="disk full"):
        momentum.run_daily(root, _now_after(cfg, 1), 0.0)
    assert _statuses(root, cfg, "total-return") == ["failed"]
    assert _statuses(root, cfg, "residual") == ["done"]


def test_a_failure_before_any_path_runs_is_recorded_for_both(job_root, monkeypatch) -> None:
    root, cfg, _ = job_root
    monkeypatch.setattr(momentum, "require", lambda _root: (_ for _ in ()).throw(frozen.FrozenConfigError("changed")))
    with pytest.raises(frozen.FrozenConfigError):
        momentum.run_daily(root, _now_after(cfg, 1), 0.0)
    assert _statuses(root, cfg, "total-return") == _statuses(root, cfg, "residual") == ["failed"]


def test_refuses_the_reversal_runs_folder_or_backup(job_root, monkeypatch) -> None:
    root, cfg, _ = job_root
    monkeypatch.setenv(daily.backup_.REMOTE_ENV, "git@host:owner/ledger.git")
    monkeypatch.setenv(momentum.REMOTE_ENV, "git@host:owner/ledger.git")
    with pytest.raises(ValueError, match="reversal run's backup remote"):
        momentum.run_daily(root, _now_after(cfg, 1), 0.0)
    monkeypatch.setenv(momentum.REMOTE_ENV, "git@host:owner/momentum.git")
    for inside in ("data/paper", "data/paper/momentum", "data"):
        overlapping = dataclasses.replace(cfg, paths=momentum.Paths(inside))
        with pytest.raises(ValueError, match="overlaps the reversal run's"):
            momentum.check_separate(root, overlapping, "")
    momentum.check_separate(root, cfg, "git@host:owner/momentum.git")
