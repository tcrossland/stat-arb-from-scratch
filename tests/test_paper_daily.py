"""Phase 6 daily job: catch-up, idempotency, missing data, refusals and crashes, on the synthetic market."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from dataclasses import replace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_CAL
from runner_helpers import market_long, market_settings
from statarb.backtest import experiments
from statarb.config import repo_root
from statarb.paper import backup as backup_
from statarb.paper import daily, frozen, ledger
from statarb.paper.config import TRAILING
from statarb.paper.day import strategy_of, strategy_panels

NY = ZoneInfo("America/New_York")
ENTRY = "f00dfeedf00dfeed"
BACKUP_LINE = b"- Ledger backup at the previous run:"

SETTINGS = market_settings()
LONG = market_long()
STRATEGY = strategy_of(SETTINGS, "baseline", "no-trade zone", TRAILING, 500_000)
FIRST = MARKET_CAL[int(np.flatnonzero(np.isfinite(strategy_panels(LONG, MARKET_CAL[-1], MARKET_CAL[0], STRATEGY).slopes))[0]) + 3]
SESSIONS = MARKET_CAL[MARKET_CAL >= FIRST]


def _morning_after(date: pd.Timestamp) -> dt.datetime:
    """06:00 in New York on the calendar day after `date`."""
    nxt = (date + pd.Timedelta(days=1)).date()
    return dt.datetime(nxt.year, nxt.month, nxt.day, 6, 0, tzinfo=NY)


def _job(tmp_path, now, tables=None, calls=None, mismatch=(), checks=None, backups=None, backup=None, strategy=STRATEGY) -> daily.Job:
    tables = LONG if tables is None else tables
    backup = backup or backup_.BackupResult("pushed", "abc1234 to the test remote")

    def snapshot() -> daily.Snapshot:
        if calls is not None:
            calls.append(1)
        return daily.Snapshot("2026-01-01", tables, ("ZZZ",))

    def reproduce() -> daily.Reproduction:
        if checks is not None:
            checks.append(1)
        return daily.Reproduction(ENTRY, tuple(mismatch))

    def back_up() -> backup_.BackupResult:
        if backups is not None:
            backups.append(1)
        return backup

    return daily.Job(
        now=now,
        first=FIRST,
        sessions=SESSIONS,
        run_time=dt.time(6, 0),
        strategy=strategy,
        ledger_root=tmp_path / "ledger",
        notes_root=tmp_path / "notes",
        runs_log=tmp_path / "runs.jsonl",
        config_hash="0123456789abcdef",
        git={"git_commit": "deadbeef", "git_dirty": False},
        reproduce=reproduce,
        snapshot=snapshot,
        backup=back_up,
    )


def _files(path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(path.iterdir())} if path.exists() else {}


def _decisions(path) -> dict[str, bytes]:
    """Notes without the backup line: what the run did before them depends on how the days were run, not on the days."""
    return {k: b"\n".join(x for x in v.split(b"\n") if not x.startswith(BACKUP_LINE)) for k, v in _files(path).items()}


def test_catch_up_processes_every_due_session_in_order(tmp_path) -> None:
    result = daily.run_job(_job(tmp_path, _morning_after(SESSIONS[5])))
    assert result.status == "done"
    assert list(result.processed) == list(SESSIONS[:6])
    assert ledger.dates(tmp_path / "ledger") == list(SESSIONS[:6])
    assert sorted(p.name for p in (tmp_path / "notes").iterdir()) == [f"{d:%Y-%m-%d}.md" for d in SESSIONS[:6]]
    assert ledger.check(tmp_path / "ledger") == []
    log = experiments.read(tmp_path / "runs.jsonl")
    assert [r["status"] for r in log] == ["done"] and log[0]["processed"][0] == f"{FIRST:%Y-%m-%d}"


def test_a_second_run_changes_nothing_but_the_run_log(tmp_path) -> None:
    now = _morning_after(SESSIONS[3])
    daily.run_job(_job(tmp_path, now))
    before = (_files(tmp_path / "ledger"), _files(tmp_path / "notes"))
    calls, checks = [], []
    result = daily.run_job(_job(tmp_path, now, calls=calls, checks=checks))
    assert result.status == "nothing due"
    assert calls == [] and checks == []                      # no reproduction, no snapshot taken, no tables built
    assert (_files(tmp_path / "ledger"), _files(tmp_path / "notes")) == before
    assert [r["status"] for r in experiments.read(tmp_path / "runs.jsonl")] == ["done", "nothing due"]


def test_rerunning_a_day_overwrites_only_that_day_with_the_same_bytes(tmp_path) -> None:
    now = _morning_after(SESSIONS[3])
    daily.run_job(_job(tmp_path, now))
    before = _files(tmp_path / "ledger")
    ledger.path_for(tmp_path / "ledger", SESSIONS[3]).unlink()
    assert daily.run_job(_job(tmp_path, now)).processed == (SESSIONS[3],)
    assert _files(tmp_path / "ledger") == before


def test_a_run_before_the_first_session_has_passed_does_nothing(tmp_path) -> None:
    calls = []
    first_day = dt.datetime(FIRST.year, FIRST.month, FIRST.day, 23, 0, tzinfo=NY)
    assert daily.run_job(_job(tmp_path, first_day, calls=calls)).status == "nothing due"
    assert calls == [] and ledger.dates(tmp_path / "ledger") == []


@pytest.mark.parametrize("zone", ["America/New_York", "Europe/London", "Asia/Tokyo", "Pacific/Auckland"])
def test_a_run_before_a_session_is_due_does_nothing_whatever_the_machines_zone(tmp_path, zone) -> None:
    calls = []
    early = (_morning_after(SESSIONS[0]) - dt.timedelta(minutes=1)).astimezone(ZoneInfo(zone))
    assert daily.run_job(_job(tmp_path, early, calls=calls)).status == "nothing due"
    assert calls == []
    on_time = (_morning_after(SESSIONS[0])).astimezone(ZoneInfo(zone))
    assert daily.run_job(_job(tmp_path, on_time)).processed == (SESSIONS[0],)


def test_daily_runs_equal_one_catch_up_run(tmp_path) -> None:
    for i in range(6):
        daily.run_job(_job(tmp_path / "daily", _morning_after(SESSIONS[i])))
    daily.run_job(_job(tmp_path / "once", _morning_after(SESSIONS[5])))
    assert _files(tmp_path / "daily" / "ledger") == _files(tmp_path / "once" / "ledger")
    assert _decisions(tmp_path / "daily" / "notes") == _decisions(tmp_path / "once" / "notes")


def test_a_session_missing_from_the_data_stops_the_run_and_is_retried(tmp_path) -> None:
    gap = {k: (v.loc[v["date"] != SESSIONS[3]] if "date" in v else v) for k, v in LONG.items()}
    now = _morning_after(SESSIONS[5])
    result = daily.run_job(_job(tmp_path, now, tables=gap))
    assert result.status == "incomplete" and str(SESSIONS[3].date()) in result.message
    assert ledger.dates(tmp_path / "ledger") == list(SESSIONS[:3])
    result = daily.run_job(_job(tmp_path, now))                  # a later snapshot has the bar
    assert result.status == "done" and list(result.processed) == list(SESSIONS[3:6])

    once = tmp_path / "once"
    daily.run_job(_job(once, now))
    assert _files(tmp_path / "ledger") == _files(once / "ledger")


def test_a_crash_before_the_ledger_day_is_written_is_recovered(tmp_path, monkeypatch) -> None:
    now = _morning_after(SESSIONS[5])
    real = ledger.write_day
    count = {"n": 0}

    def flaky(root, frame):
        count["n"] += 1
        if count["n"] == 3:
            raise OSError("disk went away")
        return real(root, frame)

    monkeypatch.setattr(ledger, "write_day", flaky)
    with pytest.raises(OSError):
        daily.run_job(_job(tmp_path, now))
    assert ledger.dates(tmp_path / "ledger") == list(SESSIONS[:2])
    monkeypatch.setattr(ledger, "write_day", real)
    assert daily.run_job(_job(tmp_path, now)).status == "done"

    once = tmp_path / "once"
    daily.run_job(_job(once, now))
    assert _files(tmp_path / "ledger") == _files(once / "ledger")
    assert _decisions(tmp_path / "notes") == _decisions(once / "notes")


def test_a_frozen_path_that_does_not_reproduce_stops_the_run(tmp_path) -> None:
    now = _morning_after(SESSIONS[2])
    daily.run_job(_job(tmp_path, _morning_after(SESSIONS[0])))
    before = (_files(tmp_path / "ledger"), _files(tmp_path / "notes"))
    calls, checks = [], []
    mismatch = ("sharpe: 0.7193500537604423 logged, 0.7193500537604424 now",)
    result = daily.run_job(_job(tmp_path, now, calls=calls, mismatch=mismatch, checks=checks))
    assert result.status == "refused" and ENTRY in result.message and result.problems == mismatch
    assert checks == [1] and calls == []                     # checked before any snapshot is taken
    assert (_files(tmp_path / "ledger"), _files(tmp_path / "notes")) == before
    record = experiments.read(tmp_path / "runs.jsonl")[-1]
    assert record["status"] == "refused" and record["problems"] == list(mismatch) and record["reproduced"] is None
    assert record["due"] == [f"{d:%Y-%m-%d}" for d in SESSIONS[1:3]]

    result = daily.run_job(_job(tmp_path, now))              # fixed: the next run catches up
    assert result.status == "done" and list(result.processed) == list(SESSIONS[1:3])
    once = tmp_path / "once"
    daily.run_job(_job(once, now))
    assert _files(tmp_path / "ledger") == _files(once / "ledger")


def test_each_run_that_processes_a_session_records_the_reproduction(tmp_path) -> None:
    daily.run_job(_job(tmp_path, _morning_after(SESSIONS[1])))
    assert experiments.read(tmp_path / "runs.jsonl")[-1]["reproduced"] == ENTRY
    assert f"`{ENTRY}` exactly" in (tmp_path / "notes" / f"{SESSIONS[1]:%Y-%m-%d}.md").read_text()


@pytest.mark.parametrize("damage", ["gap", "extra", "tampered"])
def test_a_damaged_ledger_is_refused(tmp_path, damage) -> None:
    daily.run_job(_job(tmp_path, _morning_after(SESSIONS[4])))
    root = tmp_path / "ledger"
    if damage == "gap":
        ledger.path_for(root, SESSIONS[2]).unlink()
    elif damage == "extra":
        saturday = SESSIONS[4] + pd.Timedelta(days=(5 - SESSIONS[4].day_of_week) % 7 or 7)
        ledger.write_day(root, ledger.read_day(root, SESSIONS[4]).assign(date=saturday))
    else:
        frame = ledger.read_day(root, SESSIONS[3])
        frame.loc[0, "held"] += 0.01
        frame.loc[0, "pnl"] = frame.loc[0, "held"] * frame.loc[0, "ret"]
        frame.loc[0, "drifted"] = frame.loc[0, "held"] * (1 + frame.loc[0, "ret"])
        ledger.write_day(root, frame)
    calls, checks, backups = [], [], []
    result = daily.run_job(_job(tmp_path, _morning_after(SESSIONS[8]), calls=calls, checks=checks, backups=backups))
    assert result.status == "refused" and result.problems and calls == [] and checks == []
    assert backups == [] and experiments.read(tmp_path / "runs.jsonl")[-1]["backup"] is None    # never back up a damaged ledger


def test_a_run_before_the_run_time_does_nothing_but_back_up(tmp_path) -> None:
    calls, backups = [], []
    early = _morning_after(SESSIONS[0]) - dt.timedelta(minutes=1)
    result = daily.run_job(_job(tmp_path, early, calls=calls, backups=backups))
    assert result.status == "nothing due" and calls == [] and backups == [1]
    assert daily.run_job(_job(tmp_path, _morning_after(SESSIONS[0]))).processed == (SESSIONS[0],)


def test_every_run_on_an_intact_ledger_backs_up_after_the_ledger_is_written(tmp_path) -> None:
    seen = []

    def watch(*status):
        return lambda: (seen.append(ledger.dates(tmp_path / "ledger")), backup_.BackupResult(*status))[1]

    job = _job(tmp_path, _morning_after(SESSIONS[1]))
    assert daily.run_job(replace(job, backup=watch("pushed", "abc1234"))).backup == "pushed: abc1234"
    assert seen[-1] == list(SESSIONS[:2])                         # the days of this run are in the backup
    for mismatch in ((), ("sharpe",)):                            # nothing due, then refused by the reproduction check
        job = _job(tmp_path, _morning_after(SESSIONS[1 if not mismatch else 2]), mismatch=mismatch)
        assert daily.run_job(replace(job, backup=watch("up to date", "nothing new to push"))).backup is not None
    assert len(seen) == 3
    assert [r["backup"] for r in experiments.read(tmp_path / "runs.jsonl")] == [
        "pushed: abc1234", "up to date: nothing new to push", "up to date: nothing new to push"
    ]


def test_the_note_shows_the_backup_of_the_previous_run(tmp_path) -> None:
    failed = backup_.BackupResult("failed", "git push: Permission denied (publickey).")
    daily.run_job(_job(tmp_path, _morning_after(SESSIONS[0]), backup=failed))
    daily.run_job(_job(tmp_path, _morning_after(SESSIONS[1])))
    notes = tmp_path / "notes"
    assert "previous run: no earlier run has backed up the ledger." in (notes / f"{SESSIONS[0]:%Y-%m-%d}.md").read_text()
    assert "previous run: failed: git push: Permission denied (publickey)." in (notes / f"{SESSIONS[1]:%Y-%m-%d}.md").read_text()


def test_note_text_reports_the_day_in_dollars(tmp_path) -> None:
    daily.run_job(_job(tmp_path, _morning_after(SESSIONS[8])))
    frame = ledger.read_day(tmp_path / "ledger", SESSIONS[8])
    text = (tmp_path / "notes" / f"{SESSIONS[8]:%Y-%m-%d}.md").read_text()
    book = frame["book_size"].iloc[0]
    net = (frame["pnl"].sum() - frame["borrow"].sum() - frame[["cost_spread", "cost_impact", "cost_commission"]].iloc[0].sum()) * book
    assert f"**{net:,.0f}**" in text
    assert text.startswith(f"# Paper trading: {SESSIONS[8]:%Y-%m-%d}")
    assert "ZZZ" in text and "0123456789abcdef" in text and "—" not in text


def test_an_optimiser_note_shows_a_held_book(tmp_path, monkeypatch) -> None:
    from statarb.portfolio.optimiser import Optimiser

    strategy = strategy_of(SETTINGS, "baseline", "optimiser κ = 1", TRAILING, 500_000)
    daily.run_job(_job(tmp_path, _morning_after(SESSIONS[2]), strategy=strategy))
    monkeypatch.setattr(Optimiser, "solve", lambda self, values, fixed=None: ("infeasible", None))
    daily.run_job(_job(tmp_path, _morning_after(SESSIONS[3]), strategy=strategy))
    assert ledger.read_day(tmp_path / "ledger", SESSIONS[3])["status"].iloc[0] == "infeasible"
    assert "Optimiser: infeasible; the book was held" in (tmp_path / "notes" / f"{SESSIONS[3]:%Y-%m-%d}.md").read_text()
    assert ledger.check(tmp_path / "ledger") == []


# The real job's preamble ------------------------------------------------------------------------


def test_build_job_refuses_an_unset_frozen_strategy_before_any_download(monkeypatch) -> None:
    monkeypatch.setattr(daily, "download_snapshot", lambda *a: pytest.fail("downloaded with no frozen strategy"))
    monkeypatch.setattr(daily, "build_tables", lambda *a: pytest.fail("built tables with no frozen strategy"))
    with pytest.raises(frozen.FrozenConfigError, match="waits for the decision record"):
        daily.build_job(repo_root(), dt.datetime(2027, 1, 5, 6, tzinfo=NY), download=True)


def test_the_real_reproduction_rebuilds_the_reference_tables_every_time(tmp_path, monkeypatch) -> None:
    """Tables built by earlier code would hide a change to the data or residual build."""
    built, checked = [], []
    record = {"strategy": {"price_source": "alpaca"}}
    reports = tmp_path / "reports"
    (reports / frozen.RECORD).parent.mkdir(parents=True)
    (reports / frozen.RECORD).write_text(json.dumps(record))
    monkeypatch.setattr(daily.frozen, "require", lambda root: "hash")
    monkeypatch.setattr(daily.frozen, "reports_dir", lambda root: reports)
    monkeypatch.setattr(daily.reproduce, "reference", lambda root: (tmp_path / "paper" / "reference" / "2026-11-16", "d1ge57"))
    monkeypatch.setattr(daily.reproduce, "logged_entry", lambda log, strategy: {"config_id": "f644749155058ba3"})

    def build(root, snapshot, digest, out_dir):
        built.append((snapshot, digest))
        out_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(daily, "build_tables", build)
    monkeypatch.setattr(daily, "read_tables", lambda out_dir: {"from": out_dir})
    monkeypatch.setattr(daily.reproduce, "check", lambda long, strategy, entry: (checked.append(long["from"]), [])[1])
    assert daily.reproduction(tmp_path, STRATEGY) == daily.Reproduction("f644749155058ba3", ())
    assert daily.reproduction(tmp_path, STRATEGY).problems == ()
    assert built == [("2026-11-16", "d1ge57")] * 2 and checked == [tmp_path / "paper" / "reference" / "2026-11-16"] * 2


def test_the_lock_refuses_a_second_run(tmp_path) -> None:
    with daily.locked(tmp_path / "daily.lock"), pytest.raises(daily.AlreadyRunning), daily.locked(tmp_path / "daily.lock"):
        pass
    with daily.locked(tmp_path / "daily.lock"):                 # released
        pass


def test_git_state_ignores_the_notes_directory(tmp_path) -> None:
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "start")
    (tmp_path / "reports" / "phase-06" / "daily").mkdir(parents=True)
    (tmp_path / "reports" / "phase-06" / "daily" / "2027-01-04.md").write_text("note")
    ignore = ("reports/phase-06/daily",)
    assert experiments.git_state(tmp_path, ignore=ignore)["git_dirty"] is False
    assert experiments.git_state(tmp_path)["git_dirty"] is True
    (tmp_path / "code.py").write_text("x = 1")
    assert experiments.git_state(tmp_path, ignore=ignore)["git_dirty"] is True


def test_run_records_are_json_lines(tmp_path) -> None:
    daily.run_job(_job(tmp_path, _morning_after(SESSIONS[1])))
    record = json.loads((tmp_path / "runs.jsonl").read_text().splitlines()[0])
    assert {"recorded_at", "as_of", "status", "message", "due", "processed", "snapshot", "reproduced", "backup", "config_hash", "git_commit", "git_dirty"} <= set(record)


def test_dollars_put_the_sign_first() -> None:
    assert daily.dollars(-23_177.4) == "-$23,177" and daily.dollars(5e6) == "$5,000,000" and daily.dollars(0.0) == "$0"
