"""Phase 5 holdout: the configuration fixed in development, read once on the held-out year.

    uv run python -m statarb.models.holdout [--repeat] [--workers N]

Reads every table through `[period] holdout_end` of config/models.toml. The
walk-forward runs as in development and continues into the holdout in blocks
that restart on its first day (`statarb.models.forecast.forecast_folds`), each
model trained at the close of its block's first day on every row whose target
is known by then. The development blocks are retrained too, and each model
must have the SHA-256 the development run logged: a mismatch means the
configuration, the code or the data changed, or that a development model
depended on data from the holdout, and the runner stops before it runs a path.

Every forecast goes through every rule at every book size, as in development,
over the holdout only: each path starts flat on the holdout's first day.
Partial adjustment uses the trade rate the development run chose for each
forecast and book size (`development_rates`), not one matched on the holdout.
Nothing is chosen after the holdout is seen, so it adds no trials, and its
entries never count as trials (`statarb.backtest.trials.HOLDOUT_KINDS`).

Before it loads anything it refuses: a tree with uncommitted changes; a log
whose last development run was not from a clean tree; a configuration, config
overlay or price snapshot that differs from that run's, checked by the
`config_id` of every walk-forward and path the configuration would log; and a
second read. `--repeat` runs it again only to reproduce the logged read, for
example after a dependency upgrade: it requires every result to equal the
logged one and appends nothing. Appends to reports/phase-05/experiments.jsonl
and writes reports/phase-05/holdout.md with its chart.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

from statarb.backtest import experiments
from statarb.backtest.cost_run import variants
from statarb.backtest.engine import TRADING_DAYS
from statarb.backtest.trials import HOLDOUT_KINDS, path_id, repository_trials
from statarb.config import load_config, repo_root, resolve_path
from statarb.models.config import ModelsConfig
from statarb.models.features import feature_names, ranked_target
from statarb.models.ic import daily_rank_ic, ic_summary
from statarb.models.run import (
    OPTIMISER,
    PARTIAL,
    PHASE,
    PRIOR,
    Forecasts,
    Outcome,
    Progress,
    Settings,
    build_forecasts,
    build_period_lab,
    evaluation_rows,
    ic_analysis,
    load_settings,
    model_forecast,
    path_record,
    run_paths,
    save_models,
    verdicts,
    walk_forward_config,
    walk_forward_metrics,
)
from statarb.portfolio.run import PortfolioLab
from statarb.signals.tables import load_long

WALK, PATH = "walk-forward", "path"
HOLDOUT_WALK, HOLDOUT_PATH = HOLDOUT_KINDS


# Checks, from config and the log alone ----------------------------------------------------


def latest_run(log: list[dict], kinds: tuple[str, ...]) -> list[dict]:
    """The entries of the given kinds written by the last run that wrote any: one run's entries share `recorded_at`."""
    found = [e for e in log if e["config"]["kind"] in kinds]
    if not found:
        return []
    last = max(e["recorded_at"] for e in found)
    return [e for e in found if e["recorded_at"] == last]


def expected_development_ids(s: Settings, development_end: str, first: str, last: str) -> set[str]:
    """The `config_id` of every walk-forward and path a development run of this configuration logs."""
    mc = s.mc
    names = feature_names(mc.features)
    walks = {H: walk_forward_config(mc, names, H, development_end) for H in mc.target.horizons}
    wf_ids = {H: experiments.config_id(c) for H, c in walks.items()}
    known = dict(variants(s.cfg, s.ccfg))
    first_date, last_date = pd.Timestamp(first), pd.Timestamp(last)
    ids = set(wf_ids.values())
    for forecast in [*mc.runs.variants, *(model_forecast(H) for H in mc.target.horizons)]:
        variant = known.get(forecast, known[s.pc.run.variant])
        for rule in mc.runs.rules:
            for kappa in (mc.runs.cost_multipliers if rule == OPTIMISER else (None,)):
                for book in s.pc.run.book_sizes:
                    o = Outcome(forecast, rule, kappa, book, pd.DataFrame(), {})
                    ids.add(experiments.config_id(path_record(o, s.cfg, s.ccfg, s.pc, mc, variant, wf_ids, first_date, last_date)))
    return ids


def check_ready(log: list[dict], s: Settings, state: Mapping, repeat: bool) -> dict[int, dict]:
    """Refuse to read the holdout unless this configuration is the last development run's, on committed code, for the first time.

    Returns that run's walk-forward entry for each horizon, whose model hashes
    the retrained development models must match.
    """
    if state.get("git_dirty") is not False:
        raise ValueError("the holdout is read once: commit first, so the log names the code that read it")
    read = [e for e in log if e["config"]["kind"] in HOLDOUT_KINDS]
    if read and not repeat:
        raise ValueError("the holdout has already been read (see the log); pass --repeat only to reproduce that read")
    if repeat and not read:
        raise ValueError("--repeat reproduces a logged read, and the log has none")
    dev = latest_run(log, (WALK, PATH))
    walks = {e["config"]["horizon"]: e for e in dev if e["config"]["kind"] == WALK}
    paths = [e for e in dev if e["config"]["kind"] == PATH]
    if not walks or not paths:
        raise ValueError("no development run in the log: run statarb.models.run first")
    if any(e["git_dirty"] is not False for e in dev):
        raise ValueError("the last development run was logged from a tree with changes: rerun it from a clean tree")
    for key in ("config_overlay", "price_source", "price_snapshot"):
        if any(e.get(key) != state.get(key) for e in dev):
            raise ValueError(f"{key} differs from the last development run's: the holdout reads what development read")
    ends = {e["config"]["development_end"] for e in walks.values()}
    spans = {(e["config"]["first_date"], e["config"]["last_date"]) for e in paths}
    if len(ends) != 1 or len(spans) != 1:
        raise ValueError("the last development run's entries disagree on their dates")
    (end,), ((first, last),) = ends, spans
    if expected_development_ids(s, end, first, last) != {e["config_id"] for e in dev}:
        raise ValueError("the configuration differs from the last development run's: the holdout runs the logged configuration only")
    return walks


def development_rates(log: list[dict]) -> dict[tuple[str, float], float]:
    """The trade rate the last development run chose for each forecast and book size, for partial adjustment."""
    paths = [e for e in latest_run(log, (WALK, PATH)) if e["config"]["kind"] == PATH and e["config"]["rule"] == PARTIAL]
    return {(e["config"]["forecast"], e["config"]["book_size"]): e["metrics"]["trade_rate"] for e in paths}


def development_trials(log: list[dict], earlier: Mapping[str, float]) -> dict[float, dict[str, float]]:
    """The trial set at each book size, as the last development run judged its paths against.

    `earlier` holds the trials of the phases before 5. Each path of the last
    development run adds its daily gross Sharpe at that book size, as
    `statarb.models.run.trial_sets` does, so the holdout's bar at each book is
    the development's.
    """
    paths = [e for e in latest_run(log, (WALK, PATH)) if e["config"]["kind"] == PATH]
    out: dict[float, dict[str, float]] = {}
    for e in paths:
        book = e["config"]["book_size"]
        out.setdefault(book, dict(earlier))[path_id(e["config"])] = e["metrics"]["gross_sharpe"] / math.sqrt(TRADING_DAYS)
    return out


def check_development_models(fc: Forecasts, saved: Mapping[tuple[int, int], tuple[str, str]], walks: Mapping[int, dict], dates: pd.DatetimeIndex, start: int) -> int:
    """Every development block's model must have the hash the development run logged. Returns the number checked."""
    checked = 0
    for H, entry in walks.items():
        logged = {b["test_first"]: (b["model_file"], b["model_sha256"]) for b in entry["metrics"]["blocks"]}
        fits = [(k, f) for k, f in enumerate(fc.runs[H].walk.fits) if f.fold.test_start < start]
        if len(fits) != len(logged):
            raise ValueError(f"H = {H}: {len(fits)} development blocks here, {len(logged)} in the development log")
        for k, fit in fits:
            first = str(dates[fit.fold.test_start].date())
            if logged.get(first) != saved[(H, k)]:
                raise ValueError(f"H = {H}: the model for the block from {first} differs from the development run's")
            checked += 1
    return checked


# The read --------------------------------------------------------------------------------


@dataclass(frozen=True)
class HoldoutResults:
    plab: PortfolioLab
    mc: ModelsConfig
    fc: Forecasts                       # `start` is the holdout's first day
    outcomes: list[Outcome]
    ic: dict[str, pd.DataFrame]
    block_ic: pd.DataFrame
    verdict: pd.DataFrame
    checked: int                        # development models retrained and matched
    entries: list[tuple[dict, dict]]    # (config, metrics) of each log entry, walk-forwards first


def block_ic(tables, fc: Forecasts, horizon: int) -> pd.DataFrame:
    """Mean daily IC of each forecast against the `horizon`-day target in each holdout block."""
    fs = fc.features
    target = fs.values_of(ranked_target(tables.residual.to_numpy(), tables.members, horizon))
    ok = evaluation_rows(fc)
    rows = []
    for fit in fc.runs[horizon].walk.fits:
        fold = fit.fold
        if fold.test_start < fc.start:
            continue
        sel = ok & (fs.day >= fold.test_start) & (fs.day < fold.test_stop)
        for name, panel in fc.signal.items():
            ic = daily_rank_ic(fs.day[sel], fs.values_of(panel)[sel], target[sel])
            rows.append({"block": str(tables.dates[fold.test_start].date()), "forecast": name, **ic_summary(ic)})
    return pd.DataFrame(rows)


def holdout_records(res_fc: Forecasts, outcomes: list[Outcome], plab: PortfolioLab, s: Settings, saved, checked: int) -> list[tuple[dict, dict]]:
    """One walk-forward entry per horizon with the holdout blocks only, then one entry per path."""
    lab = plab.lab
    dates = lab.tables.dates
    first = str(dates[res_fc.start].date())
    development_end = str(dates[res_fc.start - 1].date())
    out, wf_ids = [], {}
    for H, run in res_fc.runs.items():
        config = {
            **walk_forward_config(s.mc, res_fc.features.names, H, development_end),
            "kind": HOLDOUT_WALK, "holdout_start": first, "holdout_end": str(dates[-1].date()),
        }
        metrics = walk_forward_metrics(run, dates, saved, H)
        blocks = [b for b in metrics["blocks"] if b["test_first"] >= first]
        wf_ids[H] = experiments.config_id(config)
        out.append((config, {"blocks": blocks, "grid_points_tried": sum(len(b["grid"]) for b in blocks), "development_models_checked": checked}))
    known = plab.variants
    for o in outcomes:
        variant = known.get(o.forecast, known[s.pc.run.variant])
        rec = path_record(o, lab.cfg, lab.ccfg, s.pc, s.mc, variant, wf_ids, dates[res_fc.start], dates[-1])
        out.append(({**rec, "kind": HOLDOUT_PATH}, o.metrics))
    return out


def run_holdout(
    s: Settings, long: Mapping[str, pd.DataFrame], model_dir: Path, walks: Mapping[int, dict], trials: Mapping[float, dict[str, float]],
    rates: Mapping[tuple[str, float], float], root: Path | None = None, workers: int = 1, progress: Progress | None = None,
) -> HoldoutResults:
    """The read: retrain and check the development models, then run every path over the holdout.

    `trials` holds every trial through the development run at each book size
    (`development_trials`): the holdout adds none. `rates` holds partial
    adjustment's development trade rates.
    """
    say = progress or (lambda line: None)
    mc = s.mc
    end = pd.Timestamp(mc.period.holdout_end)
    say(f"cutting the tables at the holdout's last day, {mc.period.holdout_end}")
    plab = build_period_lab(long, s, end)
    tables = plab.lab.tables
    dates = tables.dates
    if dates[-1] < end:
        raise ValueError(f"the tables end on {dates[-1].date()}, before the holdout's last day {mc.period.holdout_end}")
    start = int(dates.searchsorted(pd.Timestamp(mc.period.holdout_start)))
    fc = build_forecasts(plab, mc, say)
    if fc.start > start:
        raise ValueError("some forecast has no calibrated move on the holdout's first day")
    fc = replace(fc, start=start)
    saved = save_models(fc, model_dir)
    checked = check_development_models(fc, saved, walks, dates, start)
    say(f"{checked} development models retrained, each with its logged SHA-256")
    say(f"paths from {dates[start].date()} to {dates[-1].date()}")
    outcomes = run_paths(plab, fc, mc, root, workers, say, rates=rates if PARTIAL in mc.runs.rules else None)
    rows = evaluation_rows(fc) & (fc.features.day >= start)
    ic = ic_analysis(tables, fc, rows)
    verdict = verdicts(outcomes, {b: trials[b] for b in s.pc.run.book_sizes})
    entries = holdout_records(fc, outcomes, plab, s, saved, checked)
    return HoldoutResults(plab, mc, fc, outcomes, ic, block_ic(tables, fc, mc.target.headline_horizon), verdict, checked, entries)


def check_reproduced(log: list[dict], entries: list[tuple[dict, dict]]) -> None:
    """`--repeat`: every entry must equal one of the logged read's, configuration and metrics."""
    logged = {e["config_id"]: e["metrics"] for e in latest_run(log, HOLDOUT_KINDS)}
    for config, metrics in entries:
        cid = experiments.config_id(config)
        if cid not in logged:
            raise ValueError(f"{config.get('name', config['kind'])}: not in the logged holdout read")
        written = experiments.entry(config, metrics, 0, {}, dt.datetime.now(dt.UTC))["metrics"]
        if json.loads(json.dumps(written, sort_keys=True)) != logged[cid]:
            raise ValueError(f"{config.get('name', config['kind'])}: differs from the logged holdout read")
    if len(entries) != len(logged):
        raise ValueError(f"{len(entries)} entries here, {len(logged)} in the logged holdout read")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeat", action="store_true", help="reproduce the logged read; appends nothing")
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1), help="worker processes for the optimiser paths")
    args = parser.parse_args(argv)

    from statarb.models import report

    root = repo_root()
    paths = load_config("data", root)["paths"]
    reports = resolve_path(paths["reports"], root)
    out_dir = reports / PHASE
    log_path = out_dir / "experiments.jsonl"
    log = experiments.read(log_path)
    s = load_settings(root)
    state = experiments.run_state(root)
    walks = check_ready(log, s, state, args.repeat)
    began = time.perf_counter()

    def say(line: str) -> None:
        print(f"[{time.perf_counter() - began:6.0f}s] {line}", file=sys.stderr, flush=True)

    trials = development_trials(log, repository_trials(reports, through=PRIOR))
    long = load_long(resolve_path(paths["processed"], root))
    res = run_holdout(s, long, resolve_path(paths["models"], root), walks, trials, development_rates(log), root, args.workers, say)
    if args.repeat:
        check_reproduced(log, res.entries)
        say("every result equals the logged read")
    else:
        now = dt.datetime.now(dt.UTC)
        seeds = [s.mc.lightgbm.seed] * len(res.fc.runs) + [s.cfg.run.seed] * len(res.outcomes)
        experiments.append(log_path, [experiments.entry(c, m, seed, state, now) for (c, m), seed in zip(res.entries, seeds, strict=True)])
    print(report.write_holdout_report(res, out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())

