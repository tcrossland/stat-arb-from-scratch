"""Phase 6 daily job: process every due session of the forward run.

    uv run python -m statarb.paper.daily                    # download today's snapshot if needed, then run
    uv run python -m statarb.paper.daily --no-download      # use the latest complete snapshot
    uv run python -m statarb.paper.daily --now 2027-01-05T06:00-05:00

Nothing here runs until the forward run's decision record sets `[frozen]` and
`[run]` in `config/paper.toml`: before that the job refuses at step 2, before
any download. Each run:

1. takes a lock, so two runs never overlap;
2. refuses to run if the config differs from the frozen record
   (`statarb.paper.frozen`), a model file differs from its recorded SHA-256,
   the ledger fails its integrity check, a session of the run is missing from
   the ledger, or the ledger has a day that is not a session;
3. works out the due sessions (`statarb.paper.sessions`): a session is due
   once New York's date has passed it and its clock has reached `[run]
   run_time`, so the scheduler may fire early, late or twice. None due means
   steps 4 to 6 are skipped;
4. rebuilds the reference tables from the pinned snapshot and the frozen path
   on them, and refuses to run unless it gives its logged metrics exactly
   (`statarb.paper.reproduce`);
5. takes today's price snapshot from the source in `[source]` of
   `config/data.toml` into the raw store (reused if complete) and builds the
   phase 0 tables and Model A residuals from it into
   `data/paper/processed/<snapshot>/`, never into the development tables;
6. for each due session in order, cuts the tables at the session, takes the
   step from the previous ledger day and records the decision
   (`statarb.paper.day`), and writes a daily note to `reports/phase-06/daily/`
   and then the ledger day. A session the tables lack stops the run there; the
   next run retries it;
7. on an intact ledger, whatever happened above, copies the ledger into the
   backup clone in `data/paper/backup/`, commits and pushes
   (`statarb.paper.backup`); a failure is recorded, not raised;
8. appends a record of the run to `data/paper/runs.jsonl`, refused and failed
   runs included.

A second run with nothing due changes nothing but the run log.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import shutil
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from statarb.backtest import experiments
from statarb.config import load_config, raw_store, repo_root, resolve_path
from statarb.data import cache
from statarb.data.schema import DATE, TICKER, exchange_today
from statarb.io import read_parquet, write_parquet
from statarb.paper import backup as backup_
from statarb.paper import frozen, ledger, reproduce
from statarb.paper import sessions as sessions_
from statarb.paper.config import OPTIMISER, ZONE, load_paper_config
from statarb.paper.day import MissingSession, Strategy, ledger_day, session_inputs
from statarb.signals.tables import TABLES

LEDGER, PROCESSED, RUNS, LOCK, BACKUP = "ledger", "processed", "runs.jsonl", "daily.lock", "backup"
NOTES = Path("phase-06") / "daily"        # under [paths] reports
DRIFT = Path("phase-06") / "drift"        # under [paths] reports: the weekly drift reports (statarb.paper.drift)
COMPLETE = "COMPLETE"
FAILED = "failed.json"      # beside the tables: tickers the snapshot gave no bars for, failed downloads and failed rules
PRICE_SOURCES = ("alpaca",)


@dataclass(frozen=True)
class Snapshot:
    name: str                              # download date of the price snapshot
    tables: Mapping[str, pd.DataFrame]
    failed: tuple[str, ...] = ()           # tickers the snapshot gave no bars for: failed downloads and failed rules


@dataclass(frozen=True)
class Reproduction:
    entry: str                             # config id of the frozen path's log entry
    problems: tuple[str, ...] = ()         # metrics that differ; none means it reproduced


@dataclass(frozen=True)
class Job:
    """Everything a run needs. `reproduce` and `snapshot` are called only when a session is due; `backup` on every
    run whose ledger is intact."""

    now: dt.datetime
    first: pd.Timestamp
    sessions: pd.DatetimeIndex
    run_time: dt.time                      # New York; see `statarb.paper.sessions.due`
    strategy: Strategy
    ledger_root: Path
    notes_root: Path
    runs_log: Path
    config_hash: str
    git: dict[str, Any]
    reproduce: Callable[[], Reproduction]
    snapshot: Callable[[], Snapshot]
    backup: Callable[[], backup_.BackupResult]


@dataclass(frozen=True)
class RunResult:
    status: str                            # "nothing due", "done", "incomplete" or "refused"
    message: str
    due: tuple[pd.Timestamp, ...] = ()
    processed: tuple[pd.Timestamp, ...] = ()
    snapshot: str | None = None
    problems: tuple[str, ...] = field(default=())
    reproduced: str | None = None          # the log entry the frozen path reproduced in this run
    backup: str | None = None              # `BackupResult.text()`; None when the run was refused for its ledger


def ledger_problems(job: Job, done: list[pd.Timestamp]) -> list[str]:
    problems = ledger.check(job.ledger_root)
    problems += [f"{d:%Y-%m-%d}: a session of the run missing from the ledger" for d in sessions_.gaps(job.sessions, done, job.first)]
    problems += [f"{d:%Y-%m-%d}: in the ledger but not a session of the run" for d in sessions_.extra(job.sessions, done, job.first)]
    return problems


def run_job(job: Job) -> RunResult:
    done = ledger.dates(job.ledger_root)
    problems = ledger_problems(job, done)
    if problems:                                          # a damaged ledger is never backed up
        return _log(job, RunResult("refused", "the ledger needs attention before the run can continue", problems=tuple(problems)))
    result = _process(job, done, previous_backup(job.runs_log))
    return _log(job, replace(result, backup=job.backup().text()))


def _process(job: Job, done: list[pd.Timestamp], backed_up: str) -> RunResult:
    """Every due session in order, on an intact ledger."""
    due = tuple(sessions_.due(job.sessions, job.now, job.first, done[-1] if done else None, job.run_time))
    if not due:
        return RunResult("nothing due", "no session is due")
    check = job.reproduce()
    if check.problems:
        return RunResult("refused", f"the frozen path no longer gives the metrics of log entry {check.entry}", due, problems=check.problems)
    snap = job.snapshot()
    carry = ledger.carry_of(ledger.read_day(job.ledger_root, done[-1])) if done else ledger.Carry.flat(())
    processed = []
    for date in due:
        try:
            inputs = session_inputs(snap.tables, date, job.first, job.strategy)
        except MissingSession as err:
            message = f"stopped at {date:%Y-%m-%d}: {err}; the next run retries it"
            return RunResult("incomplete", message, due, tuple(processed), snap.name, reproduced=check.entry)
        meta = ledger.DayMeta(job.strategy.book_size, job.config_hash, job.git.get("git_commit"), job.git.get("git_dirty"), snap.name)
        frame, _ = ledger_day(inputs, carry, meta)
        write_note(job.notes_root, frame, job.strategy, snap, check.entry, backed_up)   # first: a crash before the ledger day reruns the day
        ledger.write_day(job.ledger_root, frame)
        carry = ledger.carry_of(frame)
        processed.append(date)
    return RunResult("done", f"processed {len(processed)} session(s)", due, tuple(processed), snap.name, reproduced=check.entry)


def previous_backup(runs_log: Path) -> str:
    """The backup result of the last run that reached the backup, for the daily note."""
    results = [r["backup"] for r in experiments.read(runs_log) if r.get("backup")]
    return results[-1] if results else "no earlier run has backed up the ledger"


def run_record(now: dt.datetime, status: str, message: str) -> dict[str, Any]:
    return {
        "recorded_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "as_of": now.astimezone(dt.UTC).isoformat(timespec="seconds"),
        "status": status,
        "message": message,
    }


def _log(job: Job, result: RunResult) -> RunResult:
    record = {
        **run_record(job.now, result.status, result.message),
        "due": [f"{d:%Y-%m-%d}" for d in result.due],
        "processed": [f"{d:%Y-%m-%d}" for d in result.processed],
        "problems": list(result.problems),
        "snapshot": result.snapshot,
        "reproduced": result.reproduced,
        "backup": result.backup,
        "config_hash": job.config_hash,
        **job.git,
    }
    experiments.append(job.runs_log, [record])
    return result


# Daily note ----------------------------------------------------------------------------------------


def dollars(amount: float) -> str:
    """US dollars with the sign before the symbol: -$1,234."""
    return f"{'-' if amount < 0 else ''}${abs(amount):,.0f}"


def decision_lines(frame: pd.DataFrame, strategy: Strategy) -> list[str]:
    first = frame.iloc[0]
    slope = float(first["slope"])
    target = frame["target"]
    out = []
    if strategy.rule == OPTIMISER:
        out.append("- The optimiser solves at the next open on the expected move recorded here.")
    else:
        out.append(f"- Targets: {int((target > 0).sum())} long and {int((target < 0).sum())} short; {int(target.isna().sum())} names keep their holding.")
    warn = {ZONE: " (negative: the zone will not open positions)", OPTIMISER: " (negative: the optimiser bets on continuation)"}
    out.append(f"- Calibration slope ({strategy.slope_rule}): {slope:.4f}" + (warn.get(strategy.rule, "") if slope < 0 else "") + ".")
    return out


def note_text(frame: pd.DataFrame, strategy: Strategy, snap: Snapshot, reproduced: str, backed_up: str) -> str:
    """A short markdown note on one ledger day, in dollars of the frozen book."""
    first = frame.iloc[0]
    book = float(first["book_size"])
    costs = {k: float(first[f"cost_{k}"]) * book for k in ("spread", "impact", "commission")}
    gross, borrow = float(frame["pnl"].sum()) * book, float(frame["borrow"].sum()) * book
    net = gross - borrow - sum(costs.values())
    held, after = frame["held"], frame["holding"]
    traded = frame["trade"] != 0
    status = str(first["status"])
    lines = [
        f"# Paper trading: {first[DATE]:%Y-%m-%d}",
        "",
        (f"Generated by `uv run python -m statarb.paper.daily`. Snapshot {snap.name}, frozen config `{first['config_hash']}`, "
         f"commit `{str(first['git_commit'])[:7]}`{' with uncommitted changes' if first['git_dirty'] else ''}."),
        "",
        "## Day",
        "",
        "| | US dollars |",
        "|---|---:|",
        f"| gross P&L, previous fill to this fill | {gross:,.0f} |",
        f"| borrow | {-borrow:,.0f} |",
        f"| spread | {-costs['spread']:,.0f} |",
        f"| impact | {-costs['impact']:,.0f} |",
        f"| commission | {-costs['commission']:,.0f} |",
        f"| **net** | **{net:,.0f}** |",
        "",
        (f"- Book of ${book:,.0f}. Held into the fill: ${np.abs(held).sum() * book:,.0f} gross, "
         f"{int((held > 0).sum())} long and {int((held < 0).sum())} short."),
        (f"- Traded at the fill: {int(traded.sum())} names, ${np.abs(frame['trade']).sum() * book:,.0f}. "
         f"Held after: ${np.abs(after).sum() * book:,.0f} gross, {int((after > 0).sum())} long and {int((after < 0).sum())} short, "
         f"net {dollars(after.sum() * book)}."),
        f"- Held names without a return today (booked as zero): {int(first['missing_returns'])}.",
    ]
    if strategy.rule == OPTIMISER and status:
        lines.append(f"- Optimiser: {status}" + ("." if status == "optimal" else "; the book was held, as in the backtest."))
    lines += ["", "## Decision at the close, for the next fill", "", *decision_lines(frame, strategy), ""]
    lines += [
        "## Data",
        "",
        f"- Tickers the source failed to return: {', '.join(snap.failed) if snap.failed else 'none'}.",
        f"- Reproduction check: the frozen path gave the metrics of log entry `{reproduced}` exactly, on the reference tables.",
        f"- Ledger backup at the previous run: {backed_up}.",
        "",
    ]
    return "\n".join(lines)


def write_note(notes_root: Path, frame: pd.DataFrame, strategy: Strategy, snap: Snapshot, reproduced: str, backed_up: str) -> Path:
    path = notes_root / f"{frame[DATE].iloc[0]:%Y-%m-%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(note_text(frame, strategy, snap, reproduced, backed_up))
    os.replace(tmp, path)
    return path


# Snapshot and tables ---------------------------------------------------------------------------------


def download_snapshot(root: Path, today: dt.date) -> Path:
    """Today's price snapshot for the pinned candidate list, the market and the sector ETFs. Never called by a test."""
    from statarb.data.alpaca import AlpacaSource
    from statarb.data.build import (
        download_prices,
        price_rules,
        select_constituent_snapshot,
    )
    from statarb.data.wikipedia import WikipediaConstituents

    cfg = load_config("data", root)
    name = cfg["source"]["name"]
    if name not in PRICE_SOURCES:
        raise ValueError(f"unsupported price source: {name}")
    u = load_config("universe", root)
    raw_root = raw_store(cfg["paths"]["raw"], root)
    c_path = select_constituent_snapshot(raw_root, WikipediaConstituents.name, int(u["revision_id"]), u.get("snapshot", ""), u.get("digest", ""))
    tickers = WikipediaConstituents().parse((c_path / "page.html").read_bytes())[TICKER].tolist()
    tickers += [cfg["factors"]["market"], *cfg["factors"]["sectors"]]
    source = AlpacaSource(price_rules(name, root))   # reads the keys from the environment first
    d = cfg["download"]
    return download_prices(source, raw_root, sorted(set(tickers)), cfg["dates"]["start"], today, d["pause_seconds"], d["retries"])


def build_tables(root: Path, snapshot: str, digest: str, out_dir: Path) -> None:
    """Phase 0 tables and Model A residuals from one price snapshot, into `out_dir`, written whole or not at all."""
    from statarb.data.build import build, price_rules
    from statarb.data.wikipedia import WikipediaConstituents
    from statarb.factors.build import build_residuals, stocks_to_model

    cfg = load_config("data", root)
    cfg = {**cfg, "source": {**cfg["source"], "snapshot": snapshot, "digest": digest}}
    name = cfg["source"]["name"]
    out = build(
        raw_store(cfg["paths"]["raw"], root), cfg, load_config("universe", root), load_config("sector_changes", root).get("change", []),
        WikipediaConstituents(), name, load_config("listing_starts", root).get("start", []), price_rules(name, root),
    )
    tmp = out_dir.with_name(out_dir.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    for table, key in (("candidates", [TICKER]), ("prices", [DATE, TICKER]), ("actions", [DATE, TICKER]), ("returns", [DATE, TICKER]),
                       ("universe", [DATE, TICKER]), ("sectors", [TICKER, "valid_from"])):
        write_parquet(getattr(out, table), tmp / f"{table}.parquet", key)
    (tmp / "data_quality.md").write_text(out.report)
    (tmp / FAILED).write_text(json.dumps(out.failed, indent=2, sort_keys=True) + "\n")
    residuals = build_residuals(
        out.returns, out.sectors, out.prices, stocks_to_model(out.candidates, out.returns), load_config("factors", root), cfg["factors"]["market"]
    )
    write_parquet(residuals, tmp / "residuals.parquet", [DATE, TICKER])
    (tmp / COMPLETE).write_text(snapshot + "\n")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    os.replace(tmp, out_dir)


def read_tables(out_dir: Path) -> dict[str, pd.DataFrame]:
    return {k: read_parquet(out_dir / f"{k}.parquet") for k in TABLES}


def daily_snapshot(root: Path, today: dt.date, download: bool) -> Snapshot:
    cfg = load_config("data", root)
    raw_root = raw_store(cfg["paths"]["raw"], root)
    source = cfg["source"]["name"]
    path = cache.snapshot_dir(raw_root, source, today)
    if not cache.is_complete(path):
        path = download_snapshot(root, today) if download else cache.select_snapshot(raw_root, source)
    processed = resolve_path(cfg["paths"]["paper"], root) / PROCESSED
    out_dir = processed / path.name
    if not (out_dir / COMPLETE).exists():
        build_tables(root, path.name, cache.read_manifest(path)["digest"], out_dir)
    for other in processed.iterdir():                 # derived and large: keep only the snapshot in use
        if other != out_dir and other.is_dir():
            shutil.rmtree(other)
    failed = tuple(sorted(json.loads((out_dir / FAILED).read_text())))
    return Snapshot(path.name, read_tables(out_dir), failed)


def reproduction(root: Path, strategy: Strategy | None = None) -> Reproduction:
    """The reproduction check on reference tables rebuilt from the pinned snapshot with the code as it is now.

    Rebuilt every time, not reused: tables built by earlier code would hide a
    change to the data or residual build, which the day's tables go through.
    """
    frozen.require(root)
    strategy = strategy or frozen.load_strategy(root)
    entry = reproduce.frozen_entry(root)
    tables, digest = reproduce.reference(root)
    tables.parent.mkdir(parents=True, exist_ok=True)
    build_tables(root, tables.name, digest, tables)
    return Reproduction(entry["config_id"], tuple(reproduce.check(read_tables(tables), strategy, entry)))


# Entry point -------------------------------------------------------------------------------------------


class AlreadyRunning(RuntimeError):
    pass


@contextmanager
def locked(path: Path) -> Iterator[None]:
    """An exclusive lock for the run, released when the process ends however it ends."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as err:
            raise AlreadyRunning(f"another daily run holds {path}") from err
        yield


def calendar_for(name: str, first: pd.Timestamp, today: dt.date) -> pd.DatetimeIndex:
    if pd.Timestamp(today) < first:
        return pd.DatetimeIndex([], dtype="datetime64[ns]")
    return sessions_.market_sessions(name, first, pd.Timestamp(today))


def build_job(root: Path, now: dt.datetime, download: bool) -> Job:
    """The real job: refuses first if the config is not the frozen one, before any download."""
    config_hash = frozen.require(root)
    pc = load_paper_config(root)
    if pc.run.first is None:
        raise frozen.FrozenConfigError("[run] first_session in config/paper.toml is not set")
    cfg = load_config("data", root)
    paper = resolve_path(cfg["paths"]["paper"], root)
    reports = resolve_path(cfg["paths"]["reports"], root)
    today = exchange_today(now)
    strategy = frozen.load_strategy(root)
    return Job(
        now=now,
        first=pc.run.first,
        sessions=calendar_for(pc.run.calendar, pc.run.first, today),
        run_time=pc.run.run_time,
        strategy=strategy,
        ledger_root=paper / LEDGER,
        notes_root=reports / NOTES,
        runs_log=paper / RUNS,
        config_hash=config_hash,
        git=experiments.git_state(root, ignore=tuple(str((reports / p).relative_to(root)) for p in (NOTES, DRIFT))),
        reproduce=lambda: reproduction(root, strategy),
        snapshot=lambda: daily_snapshot(root, today, download),
        backup=lambda: backup_.sync(paper / LEDGER, paper / BACKUP, pc.backup.remote),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-download", action="store_true", help="use the latest complete snapshot instead of downloading")
    parser.add_argument("--now", help="run as of this time (ISO 8601 with an offset), for catch-up and checks")
    args = parser.parse_args(argv)
    now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(dt.UTC)
    root = repo_root()
    paper = resolve_path(load_config("data", root)["paths"]["paper"], root)
    with locked(paper / LOCK):
        try:
            result = run_job(build_job(root, now, not args.no_download))
        except Exception as err:                     # recorded for the drift report, then raised
            experiments.append(paper / RUNS, [run_record(now, "failed", f"{type(err).__name__}: {err}")])
            raise
    processed = [f"{d:%Y-%m-%d}" for d in result.processed]
    print(json.dumps({"status": result.status, "message": result.message, "processed": processed, "backup": result.backup}))
    for p in result.problems:
        print(f"  {p}", file=sys.stderr)
    return 0 if result.status in ("done", "nothing due") else 1


if __name__ == "__main__":
    sys.exit(main())
