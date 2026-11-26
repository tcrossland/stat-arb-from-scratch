"""Decision record 0010: the momentum forward run, beside the reversal run.

    uv run python -m statarb.paper.momentum backtest          # each path's development backtest, logged once
    uv run python -m statarb.paper.momentum frozen [--write]  # check each path's frozen record, or write it once
    uv run python -m statarb.paper.momentum reproduce         # the reproduction check on its own
    uv run python -m statarb.paper.momentum daily [--now T]   # the daily job: every due session of each path

Two paths, total-return and residual momentum, each through the decile sort
held in overlapping slices (`statarb.paper.day.MomentumRule`), on the reversal
run's universe and daily snapshots, configured in config/momentum_forward.toml.
Each path is stepped by the reversal run's own job (`statarb.paper.daily.run_job`)
with a ledger, run log, notes and backup folder of its own, so the two runs
differ only in the strategy.

- **Backtest.** Each path once over development, on tables built from the
  snapshot pinned in `[source]` of config/data.toml and cut at the day before
  the first session, starting flat on the first date with a book. Logged as
  "momentum forward path" entries in reports/phase-08/experiments.jsonl, which
  count as trials. Refused from a tree with uncommitted changes or a config
  overlay, and for a path already logged, so no result is seen before it is
  logged.
- **Frozen record.** Each path's configuration as the backtest logs it, less
  its dates, with the price source; every config file the reversal run's
  record holds (`statarb.paper.frozen.file_contents`); and this run's config
  file less the hashes. Written once to reports/phase-08/forward/frozen-<name>.json,
  after the path is logged; its hash goes in the path's `config_hash`.
- **Daily job.** Never downloads. Each due session is read from the snapshot
  the reversal run's ledger records for it, with tables built here, so the two
  runs read the same bars for every session, late ones included, and one run
  catches up every past session. A session the reversal run has not recorded is
  waited for once, up to `WAIT`, and then stops the run as `incomplete`; the
  next run retries it. Before any session it checks the frozen records and
  rebuilds each path's backtest on reference tables, requiring its logged
  metrics exactly. It refuses a data folder that overlaps the reversal run's or
  the reversal run's backup remote.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from statarb.backtest import experiments
from statarb.backtest.config import _build
from statarb.config import (
    OVERLAY_ENV,
    load_config,
    overlay,
    raw_store,
    repo_root,
    resolve_path,
)
from statarb.data import cache
from statarb.data.schema import exchange_today
from statarb.io import read_parquet
from statarb.models.run import Settings, build_period_lab, load_settings
from statarb.paper import backup as backup_
from statarb.paper import daily, frozen, ledger, reproduce
from statarb.paper.config import DECILE
from statarb.paper.day import (
    MomentumRule,
    Strategy,
    backtest_path,
    forecast_signal,
    momentum_strategy,
    panels_on,
)

NAME = "momentum_forward"                          # config/momentum_forward.toml
KIND = "momentum forward path"                     # `config.kind` of a path's log entry
LOG = Path("phase-08") / "experiments.jsonl"       # under [paths] reports
NOTES = daily.MOMENTUM_NOTES                        # under [paths] reports, one folder per path
REMOTE_ENV = "STATARB_MOMENTUM_BACKUP_REMOTE"
LEDGER, RUNS, LOCK, BACKUP, PROCESSED, REFERENCE = "ledger", "runs.jsonl", "daily.lock", "backup", "processed", "reference"
OMIT = ("kind", "first_date", "last_date", "start")   # in a path's log entry, not in its frozen record: the start is its first book
NO_DATE = pd.Timestamp("1970-01-01")
WAIT = 3600.0                                      # seconds the job waits for the reversal job's snapshot
POLL = 30.0
SLUG = re.compile(r"^[a-z][a-z0-9-]*$")


# Config ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunSettings:
    first_session: dt.date
    calendar: str
    run_time: dt.time              # New York time, as `[run] run_time` of config/paper.toml
    book_size: float
    window_days: int
    skip_days: int
    decile: float
    holding_days: int


@dataclass(frozen=True)
class Paths:
    paper: str


@dataclass(frozen=True)
class PathSpec:
    name: str                      # names the path's folders
    signal: str                    # "momentum" or "residual_momentum"
    config_hash: str               # its frozen record's hash; empty until written


@dataclass(frozen=True)
class MomentumConfig:
    run: RunSettings
    paths: Paths
    runs: tuple[PathSpec, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MomentumConfig:
        cfg = _build(cls, data, NAME)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        r = self.run
        if not isinstance(r.first_session, dt.date) or isinstance(r.first_session, dt.datetime):
            raise TypeError("run: first_session must be a TOML date such as 2026-11-16")
        if not isinstance(r.run_time, dt.time) or r.run_time.tzinfo is not None:
            raise TypeError("run: run_time must be a TOML local time such as 06:00:00, read as New York time")
        if not r.book_size > 0:
            raise ValueError("run: book_size must be positive")
        if r.window_days < 2 or r.skip_days < 0:
            raise ValueError("run: window_days must be at least 2 and skip_days at least 0")
        names, signals = [p.name for p in self.runs], [p.signal for p in self.runs]
        if not self.runs or len(set(names)) != len(names) or len(set(signals)) != len(signals):
            raise ValueError("runs: at least one, with names and signals that do not repeat")
        for p in self.runs:
            if not SLUG.match(p.name):
                raise ValueError(f"runs: {p.name!r} must be lower case letters, digits and hyphens, as it names folders")
            self.rule(p).validate()

    @property
    def first(self) -> pd.Timestamp:
        return pd.Timestamp(self.run.first_session)

    @property
    def last_before(self) -> pd.Timestamp:
        """The backtest's last date: the day before the first session, so it reads no forward day."""
        return self.first - pd.Timedelta(days=1)

    def rule(self, spec: PathSpec) -> MomentumRule:
        r = self.run
        return MomentumRule(spec.signal, r.window_days, r.skip_days, r.decile, r.holding_days)

    def strategy(self, s: Settings, spec: PathSpec) -> Strategy:
        return momentum_strategy(s, self.rule(spec), self.run.book_size)


def load_momentum_config(root: Path | None = None) -> MomentumConfig:
    return MomentumConfig.from_dict(load_config(NAME, root))


def paper_dir(root: Path, cfg: MomentumConfig) -> Path:
    return resolve_path(cfg.paths.paper, root)


def record_path(root: Path, spec: PathSpec) -> Path:
    return frozen.reports_dir(root) / daily.FORWARD / f"frozen-{spec.name}.json"


# Backtest ----------------------------------------------------------------------------------------------


def path_config(s: Settings, cfg: MomentumConfig, spec: PathSpec, first: pd.Timestamp, last: pd.Timestamp) -> dict[str, Any]:
    """The configuration part of a path's log entry, which its config_id hashes, with the keys a phase 5 path has.

    `lookback_days` is the window and `skip_days` the days left out before the
    decision (`statarb.backtest.trials.PATH_KEYS`); `start` is the first date
    with a book, from which the path runs.
    """
    rule = cfg.rule(spec)
    c = s.ccfg
    return {
        "kind": KIND,
        "signal": rule.signal,
        "source": rule.make().source,
        "lookback_days": rule.window_days,
        "skip_days": rule.skip_days,
        "vol_scaled": None,
        "holding_days": rule.holding_days,
        "name": f"{rule.signal}, {DECILE}",
        "forecast": rule.signal,
        "rule": DECILE,
        "fill": s.pc.run.fill,
        "book_size": float(cfg.run.book_size),
        "no_trade_zone": False,
        "spread": c.spread.headline_half_spread_bps,
        "half_tick_floor": c.spread.half_tick_floor,
        "impact_coefficient": c.impact.headline_coefficient,
        "commission": asdict(c.schedule(c.commission.headline)),
        "borrow": asdict(c.borrow),
        "decile": rule.decile,
        "start": str(first.date()),
        "residuals": None,
        "first_date": str(first.date()),
        "last_date": str(last.date()),
    }


def first_book(plab, strategy: Strategy) -> int:
    """Date position of the first close at which the decile sort holds a name in each leg."""
    tables = plab.lab.tables
    scored = (tables.members & np.isfinite(forecast_signal(plab, strategy))).sum(axis=1)
    has = np.flatnonzero(np.floor(scored * strategy.momentum.decile) >= 1)
    if len(has) == 0:
        raise ValueError(f"{strategy.forecast}: no date before {tables.dates[-1].date()} has a book")
    return int(has[0])


def development_paths(long: Mapping[str, pd.DataFrame], s: Settings, cfg: MomentumConfig) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(config, metrics) of each path over development: the tables cut at the day before the first session."""
    plab = build_period_lab(long, s, cfg.last_before)
    dates = plab.lab.tables.dates
    out = []
    for spec in cfg.runs:
        strategy = cfg.strategy(s, spec)
        start = first_book(plab, strategy)
        outcome = backtest_path(panels_on(plab, start, strategy), strategy)
        out.append((path_config(s, cfg, spec, dates[start], dates[-1]), outcome.metrics))
    return out


def log_backtest(root: Path, long: Mapping[str, pd.DataFrame], now: dt.datetime) -> list[dict[str, Any]]:
    """Run and log each path's development backtest, once, from a clean tree."""
    if overlay() is not None:
        raise RuntimeError(f"config overlay {overlay()} is set ({OVERLAY_ENV}): the logged backtest runs on the base config")
    state = experiments.run_state(root)
    if state["git_dirty"] is not False:
        raise RuntimeError("the tree has uncommitted changes: the logged backtest runs from a clean tree")
    cfg, s = load_momentum_config(root), load_settings(root)
    path = frozen.reports_dir(root) / LOG
    logged = {e["config"]["signal"] for e in experiments.read(path) if e["config"].get("kind") == KIND}
    already = [spec.name for spec in cfg.runs if spec.signal in logged]        # by signal, before any run: dates may move
    if already:
        raise RuntimeError(f"already logged in {LOG}: {', '.join(already)}; decision record 0010 logs each path once")
    entries = [experiments.entry(c, m, s.cfg.run.seed, state, now) for c, m in development_paths(long, s, cfg)]
    experiments.append(path, entries)
    return entries


# Frozen record -----------------------------------------------------------------------------------------


def own_file(root: Path) -> dict[str, Any]:
    """config/momentum_forward.toml without the hashes, which the record cannot hold."""
    data = load_config(NAME, root)
    return frozen.plain({**data, "runs": [{k: v for k, v in r.items() if k != "config_hash"} for r in data["runs"]]})


def strategy_part(s: Settings, cfg: MomentumConfig, spec: PathSpec, price_source: str) -> dict[str, Any]:
    config = path_config(s, cfg, spec, NO_DATE, NO_DATE)
    return frozen.plain({**{k: v for k, v in config.items() if k not in OMIT}, "price_source": price_source})


def build_record(root: Path, cfg: MomentumConfig, spec: PathSpec) -> dict[str, Any]:
    files = frozen.file_contents(root)
    return {
        "strategy": strategy_part(load_settings(root), cfg, spec, files["data"]["source"]["name"]),
        "path": spec.name,
        "files": files,
        "momentum": own_file(root),
    }


def logged_entry(log: list[dict[str, Any]], strategy: Mapping[str, Any]) -> dict[str, Any]:
    """The backtest entry of a frozen record's strategy. Repeats of it must agree."""
    config = {k: v for k, v in strategy.items() if k != "price_source"}
    hits = [
        e for e in log
        if e["config"].get("kind") == KIND and e.get("price_source") == strategy["price_source"]
        and {k: v for k, v in e["config"].items() if k not in OMIT} == config
    ]
    if not hits:
        raise ValueError(f"no {KIND} in {LOG} has the strategy of {strategy.get('signal')!r}: run the backtest first")
    if any((e["config_id"], e["metrics"]) != (hits[0]["config_id"], hits[0]["metrics"]) for e in hits[1:]):
        raise ValueError(f"the {KIND} entries of {strategy.get('signal')!r} in {LOG} disagree")
    return hits[0]


def check(root: Path) -> list[str]:
    """Why the config does not match each path's frozen record, or nothing if every one does."""
    if (named := overlay()) is not None:
        return [f"config overlay {named} is set ({OVERLAY_ENV}); the frozen records are checked against the base config only"]
    cfg = load_momentum_config(root)
    problems = []
    for spec in cfg.runs:
        if not spec.config_hash:
            problems.append(f"{spec.name}: config_hash is not set in config/{NAME}.toml")
            continue
        path = record_path(root, spec)
        stored = json.loads(path.read_text()) if path.exists() else None
        if stored is None:
            problems.append(f"{spec.name}: no frozen record at {path.relative_to(root)}")
            continue
        if experiments.config_id(stored) != spec.config_hash:
            problems.append(f"{spec.name}: the record hashes to {experiments.config_id(stored)}, not its config_hash {spec.config_hash}")
        problems += [f"{spec.name}: changed since the freeze: {key}" for key in frozen.differences(stored, build_record(root, cfg, spec))]
    return problems


def require(root: Path) -> None:
    problems = check(root)
    if problems:
        raise frozen.FrozenConfigError("the config differs from the momentum frozen records:\n  " + "\n  ".join(problems))


def write(root: Path) -> dict[str, str]:
    """Write each path's record for the config as it is, after its backtest is logged; its hash by path name."""
    if (named := overlay()) is not None:
        raise frozen.FrozenConfigError(f"config overlay {named} is set ({OVERLAY_ENV}); the frozen records are written from the base config only")
    cfg = load_momentum_config(root)
    log = experiments.read(frozen.reports_dir(root) / LOG)
    records = {spec: build_record(root, cfg, spec) for spec in cfg.runs}
    for spec, built in records.items():          # every path is checked before any record is written
        logged_entry(log, built["strategy"])
        if spec.config_hash and spec.config_hash != experiments.config_id(built):
            raise frozen.FrozenConfigError(f"{spec.name}: config_hash is already {spec.config_hash}; changing it is a new decision record")
    out = {}
    for spec, built in records.items():
        digest = experiments.config_id(built)
        path = record_path(root, spec)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(built, sort_keys=True, indent=2) + "\n")
        os.replace(tmp, path)
        out[spec.name] = digest
    return out


def frozen_entry(root: Path, spec: PathSpec) -> dict[str, Any]:
    """The backtest entry of the strategy in a path's frozen record: call `require` first."""
    stored = json.loads(record_path(root, spec).read_text())
    return logged_entry(experiments.read(frozen.reports_dir(root) / LOG), stored["strategy"])


# Daily job ---------------------------------------------------------------------------------------------


def once[T](make: Callable[[], T]) -> Callable[[], T]:
    """`make`, called at most once: the paths share one snapshot and one set of reference tables."""
    box: list[T] = []

    def call() -> T:
        if not box:
            box.append(make())
        return box[0]

    return call


def reference_tables(root: Path, cfg: MomentumConfig, log: daily.Log = daily.quiet) -> dict[str, pd.DataFrame]:
    """Tables rebuilt from the pinned snapshot with the code as it is, as the reversal run's reproduction check builds them."""
    _, digest = reproduce.reference(root)
    snapshot = load_config("data", root)["source"]["snapshot"]
    out = paper_dir(root, cfg) / REFERENCE / snapshot
    out.parent.mkdir(parents=True, exist_ok=True)
    with daily.stage(log, f"reference tables from snapshot {snapshot}"):
        daily.build_tables(root, snapshot, digest, out)
    return daily.read_tables(out)


def wait_for(ready: Callable[[], bool], wait: float, poll: float, clock: Callable[[], float] = time.monotonic,
             sleep: Callable[[float], None] = time.sleep) -> bool:
    """Whether `ready` became true within `wait` seconds, checking every `poll`."""
    deadline = clock() + wait
    while not ready():
        if clock() >= deadline:
            return False
        sleep(poll)
    return True


def reversal_ledger(root: Path) -> Path:
    """The reversal run's ledger (`[paths] paper` of config/data.toml), whose days name the snapshot each was built from."""
    return resolve_path(load_config("data", root)["paths"]["paper"], root) / daily.LEDGER


def recorded_snapshot(reversal: Path, date: pd.Timestamp) -> str | None:
    """The snapshot the reversal ledger records for a session, or None before the reversal run has processed it."""
    path = ledger.path_for(reversal, date)
    return str(read_parquet(path)["snapshot"].iloc[0]) if path.exists() else None


def session_snapshots(root: Path, cfg: MomentumConfig, log: daily.Log, wait: float = WAIT, poll: float = POLL) -> Callable[[pd.Timestamp], daily.Snapshot | str]:
    """Each session's snapshot: the one the reversal ledger records for it, with tables built here; never a download.

    A session the reversal run has not recorded is waited for once, up to `wait`
    seconds, in case its job is still running; after that, and for every path,
    it stops the run, and the next run retries it. The tables of the snapshot in
    use are kept, so the paths share them; a catch-up across several snapshots
    builds each again for the second path.
    """
    data_cfg, reversal = load_config("data", root), reversal_ledger(root)
    raw = raw_store(data_cfg["paths"]["raw"], root)
    built: dict[str, daily.Snapshot] = {}
    waited: set[pd.Timestamp] = set()

    def for_session(date: pd.Timestamp) -> daily.Snapshot | str:
        if recorded_snapshot(reversal, date) is None and date not in waited:
            waited.add(date)
            with daily.stage(log, f"waiting for the reversal run to record {date:%Y-%m-%d}"):
                wait_for(lambda: ledger.path_for(reversal, date).exists(), wait, poll)
        name = recorded_snapshot(reversal, date)
        if name is None:
            return "the reversal run has not recorded it"
        if name not in built:
            if not cache.is_complete(cache.snapshot_dir(raw, data_cfg["source"]["name"], dt.date.fromisoformat(name))):
                return f"the reversal run read snapshot {name}, which the raw store does not hold complete"
            built.clear()
            built[name] = daily.daily_snapshot(root, dt.date.fromisoformat(name), False, log, paper_dir(root, cfg) / PROCESSED)
        return built[name]

    return for_session


def no_run_day_snapshot() -> daily.Snapshot:
    raise AssertionError("the momentum job reads each session's snapshot through `snapshot_for`")


def check_separate(root: Path, cfg: MomentumConfig, remote: str) -> None:
    """Refuse settings that would let this job touch the reversal run's files or backup."""
    ours, theirs = paper_dir(root, cfg).resolve(), resolve_path(load_config("data", root)["paths"]["paper"], root).resolve()
    if ours == theirs or ours.is_relative_to(theirs) or theirs.is_relative_to(ours):
        raise ValueError(f"[paths] paper of config/{NAME}.toml overlaps the reversal run's {theirs}: its lock and tables must be apart")
    if remote and remote == backup_.remote():
        raise ValueError(f"{REMOTE_ENV} is the reversal run's backup remote ({backup_.REMOTE_ENV}): each run backs up to its own repository")


def build_jobs(root: Path, now: dt.datetime, started: float, log: daily.Log = daily.stderr_log) -> list[tuple[PathSpec, daily.Job]]:
    """One job per path, refusing first if a frozen record does not match."""
    with daily.stage(log, "frozen check"):
        require(root)
    cfg, s = load_momentum_config(root), load_settings(root)
    base, reports = paper_dir(root, cfg), frozen.reports_dir(root)
    sessions = daily.calendar_for(cfg.run.calendar, cfg.first, exchange_today(now))
    snapshot_for = session_snapshots(root, cfg, log)
    reference = once(lambda: reference_tables(root, cfg, log))
    remote = backup_.remote(name=REMOTE_ENV)
    check_separate(root, cfg, remote)
    git = daily.job_git_state(root, reports)
    jobs = []
    for spec in cfg.runs:
        strategy, entry, folder = cfg.strategy(s, spec), frozen_entry(root, spec), base / spec.name

        def reproduction(strategy: Strategy = strategy, entry: dict[str, Any] = entry) -> daily.Reproduction:
            return daily.Reproduction(entry["config_id"], tuple(reproduce.check(reference(), strategy, entry)))

        def backup(spec: PathSpec = spec, folder: Path = folder) -> backup_.BackupResult:
            return backup_.sync(folder / LEDGER, base / BACKUP, remote, spec.name, REMOTE_ENV)

        jobs.append((spec, daily.Job(
            now=now, first=cfg.first, sessions=sessions, run_time=cfg.run.run_time, strategy=strategy,
            ledger_root=folder / LEDGER, notes_root=reports / NOTES / spec.name, runs_log=folder / RUNS,
            config_hash=spec.config_hash, git=git, reproduce=reproduction, snapshot=no_run_day_snapshot, backup=backup, log=log,
            started=started, snapshot_for=snapshot_for,
        )))
    return jobs


def run_daily(root: Path, now: dt.datetime, started: float) -> list[tuple[str, daily.RunResult]]:
    cfg = load_momentum_config(root)
    base = paper_dir(root, cfg)
    with daily.locked(base / LOCK):
        try:
            jobs = build_jobs(root, now, started)
        except Exception as err:                     # before any path ran: recorded for every path, then raised
            for spec in cfg.runs:
                experiments.append(base / spec.name / RUNS, [daily.run_record(now, "failed", f"{type(err).__name__}: {err}", started)])
            raise
        results, failure = [], None
        for spec, job in jobs:                       # a path that fails is recorded on its own, and the next still runs
            try:
                results.append((spec.name, daily.run_job(job)))
            except Exception as err:  # noqa: BLE001 - re-raised after the other path has run
                experiments.append(job.runs_log, [daily.run_record(now, "failed", f"{type(err).__name__}: {err}", started)])
                failure = failure or err
        if failure is not None:
            raise failure
        return results


# Entry point -------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backtest", help="log each path's development backtest, once, from a clean tree")
    fz = sub.add_parser("frozen", help="check each path's frozen record")
    fz.add_argument("--write", action="store_true", help="write each record and print its hash for config/momentum_forward.toml")
    sub.add_parser("reproduce", help="rebuild each path's backtest and compare it with its log entry")
    dy = sub.add_parser("daily", help="process every due session of each path")
    dy.add_argument("--now", help="run as of this time (ISO 8601 with an offset), for catch-up and checks")
    args = parser.parse_args(argv)
    started = time.monotonic()
    root = repo_root()
    if args.command == "backtest":
        cfg = load_momentum_config(root)
        for e in log_backtest(root, reference_tables(root, cfg, daily.stderr_log), dt.datetime.now(dt.UTC)):
            print(f"{e['config_id']}  {e['config']['name']}  from {e['config']['first_date']} to {e['config']['last_date']}")
        return 0
    if args.command == "frozen":
        if args.write:
            for name, digest in write(root).items():
                print(f"{name}: {digest}")
            return 0
        problems = check(root)
        print("\n".join(problems) if problems else "every path matches its frozen record")
        return 1 if problems else 0
    if args.command == "reproduce":
        require(root)
        cfg, s = load_momentum_config(root), load_settings(root)
        tables = reference_tables(root, cfg, daily.stderr_log)
        problems = []
        for spec in cfg.runs:
            entry = frozen_entry(root, spec)
            found = reproduce.check(tables, cfg.strategy(s, spec), entry)
            problems += [f"{spec.name}: {p}" for p in found]
            print(f"{spec.name}: " + ("differs" if found else f"reproduces log entry {entry['config_id']}"))
        print("\n".join(problems), file=sys.stderr)
        return 1 if problems else 0
    now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(dt.UTC)
    results = run_daily(root, now, started)
    for name, r in results:
        print(json.dumps({"path": name, "status": r.status, "message": r.message, "processed": [f"{d:%Y-%m-%d}" for d in r.processed], "backup": r.backup}))
        for p in r.problems:
            print(f"  {name}: {p}", file=sys.stderr)
    return 0 if all(r.status in ("done", "nothing due") for _, r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
