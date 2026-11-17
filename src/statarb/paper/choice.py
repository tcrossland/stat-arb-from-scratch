"""Phase 6: the evidence before the forward run's strategy is chosen (brief, "Evidence for the choice").

    uv run python -m statarb.paper.choice [--no-log] [--workers N]

Development only, every table cut at `[period] development_end` of
config/models.toml, except the slope chart's paths:

- **Slope over time.** Each phase 5 forecast's trailing calibration slope from
  its first calibrated date to the holdout's last day, above the cumulative
  gross P&L of its decile sort and no-trade zone. These "diagnostic paths" run
  through the holdout, which phase 5 has read; nothing is chosen from them, so
  they are not trials.
- **Realised move by forecast decile**: whether a forecast with a higher IC
  shows larger moves in the outer deciles, where a decile book or a calibrated
  forecast earns.
- **IC by fill timing**: IC against total returns from the close of t, where
  phase 5 measures it, and from the open of t+1, where the book fills.
- **Slope rules** (`[choice] slope_rules` of config/paper.toml): every forecast
  through every rule of `[runs] rules` of config/models.toml that uses the
  expected move, except partial adjustment, which the daily job cannot run,
  at each book size, with the slope as phase 3 has it (trailing), floored at zero, or
  estimated over every pair since the start (expanding). The decile sort does
  not read the slope, so it runs once. The trailing paths repeat phase 5's and
  must reproduce every metric of its log. A path whose daily results equal its
  trailing version's is marked `identical_to` and is not a trial
  (`statarb.backtest.trials`); the others are.

The phase 5 models are retrained, development and holdout, and each must have
the SHA-256 phase 5 logged; the files are written to a temporary directory and
compared, never over the saved models. Appends "choice path" and "diagnostic
path" entries to reports/phase-06/experiments.jsonl and writes
reports/phase-06/choice.md with its charts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from statarb.backtest import experiments
from statarb.backtest.engine import FILL_TIMINGS, TRADING_DAYS, open_to_open_returns
from statarb.backtest.trials import HOLDOUT_KINDS, path_id, repository_trials
from statarb.config import load_config, repo_root, resolve_path
from statarb.factors.model import wide
from statarb.models.config import ModelsConfig
from statarb.models.holdout import PATH, WALK, latest_run
from statarb.models.ic import daily_rank_ic, ic_summary
from statarb.models.run import (
    DECILE,
    PARTIAL,
    ZONE,
    Forecasts,
    Outcome,
    Settings,
    build_forecasts,
    build_period_lab,
    evaluation_rows,
    load_settings,
    path_record,
    rule_paths,
    rule_variant,
    run_paths,
    save_models,
    starting_at,
    verdicts,
)
from statarb.paper.config import SLOPE_RULES, TRAILING, load_paper_config
from statarb.portfolio.run import PortfolioLab
from statarb.signals.calibration import calibration_slope, expected_move, forward_sum
from statarb.signals.tables import load_long

PHASE = "phase-06"
PRIOR = "phase-05"
CHOICE, DIAGNOSTIC = "choice path", "diagnostic path"
IGNORED = ("solver_seconds_mean",)       # wall-clock, not a result

Progress = Callable[[str], None]


def label(forecast: str, rule: str) -> str:
    """The trailing rule keeps the phase 5 forecast name, so its paths compare with the phase 5 log."""
    return forecast if rule == TRAILING else f"{forecast}, {rule} slope"


def parse_label(name: str) -> tuple[str, str]:
    if name.endswith(" slope"):
        forecast, rule = name[: -len(" slope")].rsplit(", ", 1)
        return forecast, rule
    return name, TRAILING


# Slopes ------------------------------------------------------------------------------------------


def slope(signal: np.ndarray, residual: np.ndarray, members: np.ndarray, rule: str, horizon: int, window: int, min_days: int) -> np.ndarray:
    """The calibration slope on each decision date under `rule`, from pairs whose outcome is known by then."""
    if rule not in SLOPE_RULES:
        raise ValueError(f"unknown slope rule {rule!r}")
    outcome = forward_sum(residual, horizon)
    s = calibration_slope(signal, outcome, members, horizon, signal.shape[0] if rule == "expanding" else window, min_days)
    return np.maximum(s, 0.0) if rule == "floored" else s       # NaN stays NaN


def slope_of(plab: PortfolioLab, signal: np.ndarray, rule: str) -> np.ndarray:
    tables, nt = plab.lab.tables, plab.lab.ccfg.no_trade
    return slope(
        signal, tables.residual.to_numpy(), tables.members, rule, plab.pc.optimiser.horizon_days,
        nt.calibration_window_days, nt.calibration_min_days,
    )


def rule_forecasts(plab: PortfolioLab, fc: Forecasts, rules: tuple[str, ...]) -> tuple[PortfolioLab, Forecasts]:
    """Every forecast under every slope rule, labelled, as forecasts the phase 5 path runners take, from `fc.start`.

    The trailing rule keeps phase 5's slope and move as they are. The lab gains
    each labelled variant forecast's holding rule, which the zone reads.
    """
    members = plab.lab.tables.members
    signal, slopes, move = {}, {}, {}
    for name, sig in fc.signal.items():
        for rule in rules:
            k = label(name, rule)
            signal[k] = sig
            slopes[k] = fc.slope[name] if rule == TRAILING else slope_of(plab, sig, rule)
            move[k] = fc.move[name] if rule == TRAILING else expected_move(sig, members, slopes[k])
            if not np.isfinite(move[k][fc.start]).any():
                raise ValueError(f"{k}: no calibrated move on the first date of phase 5's paths")
    variants = {**plab.variants, **{label(n, r): plab.variants[n] for n in fc.signal if n in plab.variants for r in rules}}
    return replace(plab, variants=variants), Forecasts(fc.features, signal, slopes, move, {}, fc.start)


# Evidence ----------------------------------------------------------------------------------------


def decile_profile(plab: PortfolioLab, fc: Forecasts, horizon: int, buckets: int = 10) -> pd.DataFrame:
    """Mean realised residual move over the next `horizon` days, by decile of each forecast within each day.

    Rows are the member-days every forecast covers whose outcome is known by the
    last date of the tables; decile 10 holds the highest forecasts.
    """
    tables = plab.lab.tables
    fs = fc.features
    outcome = fs.values_of(np.where(tables.members, forward_sum(tables.residual.to_numpy(), horizon), np.nan))
    rows = evaluation_rows(fc) & np.isfinite(outcome)
    out = []
    for name, panel in fc.signal.items():
        d = pd.DataFrame({"day": fs.day[rows], "f": fs.values_of(panel)[rows], "y": outcome[rows]})
        pct = d.groupby("day")["f"].rank(pct=True, method="first")
        d["decile"] = np.minimum(np.ceil(pct * buckets), buckets).astype(int)
        g = d.groupby("decile")["y"].agg(["mean", "size"]).reset_index()
        out.append(g.assign(forecast=name))
    return pd.concat(out, ignore_index=True)[["forecast", "decile", "mean", "size"]]


def forward(r: np.ndarray, start: int, span: int) -> np.ndarray:
    """On row t, the compounded return over rows t+start to t+start+span-1 of `r`; NaN if any is missing."""
    T = r.shape[0]
    out = np.ones(r.shape)
    for j in range(start, start + span):
        step = np.full(r.shape, np.nan)
        if j < T:
            step[: T - j] = r[j:]
        out = out * (1.0 + step)
    return out - 1.0


def session_returns(plab: PortfolioLab) -> dict[str, np.ndarray]:
    """Total returns on (dates x stocks) panels, each on the row of the day it ends.

    close: close t-1 to close t; open: open t-1 to open t, with splits and
    dividends at the open as in the backtest's open grid; overnight: close t-1
    to open t, so that (1 + close) = (1 + overnight)(1 + open t to close t).
    """
    t = plab.lab.tables
    dates, stocks = t.dates, t.stocks
    close = t.raw.to_numpy()
    opens = wide(open_to_open_returns(t.prices, t.returns), "ret", dates, stocks).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        intraday = wide(t.prices, "close", dates, stocks).to_numpy() / wide(t.prices, "open", dates, stocks).to_numpy() - 1.0
        overnight = (1.0 + close) / (1.0 + intraday) - 1.0
    return {"close": close, "open": opens, "overnight": overnight}


def fill_timing_ic(plab: PortfolioLab, fc: Forecasts, horizon: int) -> pd.DataFrame:
    """Rank IC of each forecast on t against total returns from the close of t, where phase 5 measures IC, and from
    the open of t+1, where the book fills, on the rows every forecast covers.

    Total returns, because residuals exist only close to close. Ranking within
    the day removes a move common to every stock, but not the part of the
    market move that differs by beta.
    """
    members = plab.lab.tables.members
    r = session_returns(plab)
    windows = [
        ("close t to open t+1", forward(r["overnight"], 1, 1)),
        ("close t to close t+1", forward(r["close"], 1, 1)),
        ("open t+1 to open t+2", forward(r["open"], 2, 1)),
        (f"close t to close t+{horizon}", forward(r["close"], 1, horizon)),
        (f"open t+1 to open t+{horizon + 1}", forward(r["open"], 2, horizon)),
    ]
    fs = fc.features
    rows = evaluation_rows(fc)
    day = fs.day[rows]
    out = []
    for name, panel in fc.signal.items():
        f = fs.values_of(panel)[rows]
        for window, target in windows:
            ic = daily_rank_ic(day, f, fs.values_of(np.where(members, target, np.nan))[rows])
            out.append({"forecast": name, "window": window, **ic_summary(ic)})
    return pd.DataFrame(out)


def holdout_days(index: pd.DatetimeIndex, dates: pd.DatetimeIndex, boundary: int) -> np.ndarray:
    """Whether each of `index` falls in the holdout, which starts on `dates[boundary]`; none does when `boundary` is past the end."""
    if boundary >= len(dates):
        return np.zeros(len(index), dtype=bool)
    return np.asarray(index >= dates[boundary])


def gross_by_slope_sign(outcomes: list[Outcome], slopes: Mapping[str, np.ndarray], dates: pd.DatetimeIndex, boundary: int, fill: str) -> pd.DataFrame:
    """Gross return a year on days whose decision slope was negative or not, by period.

    A decision on t is filled at grid time t + delay and earns the return to the
    next grid time, so the P&L of date d comes from the decision on d - delay - 1:
    d - 2 for fills at the open of t+1.
    """
    lag = FILL_TIMINGS[fill][1] + 1
    periods = ("development", "holdout") if boundary < len(dates) else ("development",)
    rows = []
    for o in outcomes:
        s = pd.Series(slopes[o.forecast], index=dates).shift(lag).reindex(o.daily.index)
        period = np.where(holdout_days(o.daily.index, dates, boundary), "holdout", "development")
        for p in periods:
            sel = period == p
            neg, pos = sel & (s < 0).to_numpy(), sel & (s >= 0).to_numpy()
            rows.append(
                {
                    "forecast": o.forecast, "rule": o.label, "book": o.book, "period": p,
                    "negative_days": int(neg.sum()),
                    "gross_negative": float(o.daily["gross"][neg].mean() * TRADING_DAYS) if neg.any() else float("nan"),
                    "gross_positive": float(o.daily["gross"][pos].mean() * TRADING_DAYS) if pos.any() else float("nan"),
                    "capital_negative": float(o.daily["exposure"][neg].mean()) if neg.any() else float("nan"),
                    "capital_positive": float(o.daily["exposure"][pos].mean()) if pos.any() else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def negative_share_by_year(slopes: Mapping[str, np.ndarray], dates: pd.DatetimeIndex, start: int, boundary: int) -> pd.DataFrame:
    """The share of days with a negative slope in each calendar year, the holdout as one period."""
    rows = []
    for name, s in slopes.items():
        x = pd.Series(s[start:], index=dates[start:])
        key = np.where(holdout_days(x.index, dates, boundary), "holdout", x.index.year.astype(str))
        for k, g in x.groupby(key):
            rows.append({"forecast": name, "year": k, "negative": float((g < 0).mean())})
    return pd.DataFrame(rows)


def identical_paths(outcomes: list[Outcome]) -> dict[str, str]:
    """Each non-trailing path whose daily results equal its trailing version's, keyed by name and book, mapped to that path's name."""
    trailing = {(o.forecast, o.label, o.book): o for o in outcomes if parse_label(o.forecast)[1] == TRAILING}
    same = {}
    for o in outcomes:
        base, rule = parse_label(o.forecast)
        if rule != TRAILING:
            t = trailing[(base, o.label, o.book)]
            if o.daily.equals(t.daily):
                same[key(o)] = t.name
    return same


def key(o: Outcome) -> str:
    return f"{o.name}, {o.book:g}"


# Checks against phase 5 ---------------------------------------------------------------------------


def logged_models(log: list[dict]) -> dict[tuple[int, str], str]:
    """(horizon, first test date) -> SHA-256 of each block's model, from phase 5's last development run and its holdout read."""
    out: dict[tuple[int, str], str] = {}
    for kinds in ((WALK, PATH), HOLDOUT_KINDS):
        for e in latest_run(log, kinds):
            if e["config"]["kind"] in (WALK, HOLDOUT_KINDS[0]):
                out.update({(e["config"]["horizon"], b["test_first"]): b["model_sha256"] for b in e["metrics"]["blocks"]})
    return out


def check_models(fc: Forecasts, logged: Mapping[tuple[int, str], str], dates: pd.DatetimeIndex) -> int:
    """Every retrained model must have the SHA-256 phase 5 logged for its block. Returns the number checked.

    The files are written to a temporary directory, so a model that differs
    never replaces a saved one.
    """
    with tempfile.TemporaryDirectory() as tmp:
        saved = save_models(fc, Path(tmp))
    checked = 0
    for H, run in fc.runs.items():
        for k, fit in enumerate(run.walk.fits):
            first = str(dates[fit.fold.test_start].date())
            if logged.get((H, first)) != saved[(H, k)][1]:
                raise ValueError(f"H = {H}: the model for the block from {first} differs from phase 5's")
            checked += 1
    return checked


def stored(metrics: Mapping) -> dict:
    """Metrics as the experiment log stores them, less wall-clock and fields about other paths."""
    written = json.loads(json.dumps(experiments.entry({}, dict(metrics), 0, {}, dt.datetime.now(dt.UTC))["metrics"], sort_keys=True))
    return {k: v for k, v in written.items() if k not in (*IGNORED, "identical_to")}


def check_reproduces_phase5(choice: list[tuple[Outcome, dict]], log: list[dict]) -> int:
    """The trailing paths repeat phase 5's last development run: each configuration, less its kind and slope rule, and every
    metric must equal its log's. Returns the number checked."""
    p5 = {e["config_id"]: e for e in latest_run(log, (WALK, PATH)) if e["config"]["kind"] == PATH}
    checked = 0
    for o, rec in choice:
        if rec["slope_rule"] != TRAILING:
            continue
        cfg = {k: v for k, v in rec.items() if k != "slope_rule"} | {"kind": PATH}
        e = p5.get(experiments.config_id(cfg))
        if e is None:
            raise ValueError(f"{o.name} at {o.book:g}: no phase 5 path has its configuration")
        if (a := stored(e["metrics"])) != (b := stored(o.metrics)):
            differ = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
            raise ValueError(f"{o.name} at {o.book:g} does not reproduce phase 5's metrics: {', '.join(differ)}")
        checked += 1
    return checked


# Log ------------------------------------------------------------------------------------------------


def record(o: Outcome, plab: PortfolioLab, s: Settings, wf_ids: Mapping[int, str], first: pd.Timestamp, last: pd.Timestamp, kind: str) -> dict:
    """A path's log configuration: phase 5's, with its kind and slope rule. The slope rule is part of the path's
    trial id unless it is trailing (`statarb.backtest.trials.path_id`)."""
    base, rule = parse_label(o.forecast)
    rec = path_record(
        replace(o, forecast=base), plab.lab.cfg, plab.lab.ccfg, plab.pc, s.mc, rule_variant(plab, base), wf_ids, first, last,
    )
    return {**rec, "kind": kind, "slope_rule": rule}


def trial_sets(earlier: Mapping[str, float], new: list[tuple[Outcome, dict]], books: tuple[float, ...]) -> dict[float, dict[str, float]]:
    """Daily gross Sharpe by path id at each book size: the earlier phases' trials plus this run's paths that are trials."""
    out = {}
    for book in books:
        paths = dict(earlier)
        for o, rec in new:
            if o.book == book:
                paths[path_id(rec)] = o.metrics["gross_sharpe"] / math.sqrt(TRADING_DAYS)
        out[book] = paths
    return out


# Run ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Choice:
    """Everything the report and the log need."""

    dev: PortfolioLab
    full: PortfolioLab
    full_fc: Forecasts
    full_slopes: dict[str, np.ndarray]
    diagnostic: list[Outcome]
    boundary: int                       # date position of the holdout's first day in the full tables
    profile: pd.DataFrame
    fill_ic: pd.DataFrame
    rf: Forecasts                       # the forecasts under every slope rule, development
    outcomes: list[Outcome]
    same: dict[str, str]
    verdict: pd.DataFrame
    trials_new: int                     # distinct new position paths: book sizes are not separate trials
    by_sign: pd.DataFrame
    negative_share: pd.DataFrame
    checked: int
    reproduced: int
    records: list[tuple[Outcome, dict]]  # choice paths, then diagnostic paths, with their log configs


def run_choice(
    s: Settings, long: Mapping[str, pd.DataFrame], slope_rules: tuple[str, ...], p5_log: list[dict], earlier: Mapping[str, float],
    root: Path | None = None, workers: int = 1, progress: Progress | None = None,
) -> Choice:
    say = progress or (lambda line: None)
    mc: ModelsConfig = s.mc
    period = mc.period

    logged = logged_models(p5_log)
    say(f"tables through the holdout's last day, {period.holdout_end}")
    full = build_period_lab(long, s, pd.Timestamp(period.holdout_end))
    full_fc = build_forecasts(full, mc, say)
    dates = full.lab.tables.dates
    checked = check_models(full_fc, logged, dates)
    boundary = int(dates.searchsorted(pd.Timestamp(period.holdout_start)))
    full_slopes = {name: slope_of(full, sig, TRAILING) for name, sig in full_fc.signal.items()}
    started = starting_at(full, full_fc.start, full_fc.move)
    diagnostic = [o for name in full_fc.names for o in rule_paths(started, full_fc, name, (DECILE, ZONE))]

    say(f"development tables, through {period.development_end}")
    dev = build_period_lab(long, s, pd.Timestamp(period.development_end))
    dev_fc = build_forecasts(dev, mc, say)                    # as phase 5 built them, from development tables only
    ddates = dev.lab.tables.dates
    checked += check_models(dev_fc, logged, ddates)
    say(f"{checked} models match phase 5's")
    h = dev.pc.optimiser.horizon_days
    profile = decile_profile(dev, dev_fc, h)
    fill_ic = fill_timing_ic(dev, dev_fc, h)
    ruled, rf = rule_forecasts(dev, dev_fc, slope_rules)
    runs = replace(mc, runs=replace(mc.runs, rules=tuple(r for r in mc.runs.rules if r != PARTIAL)))
    outcomes = [o for o in run_paths(ruled, rf, runs, root, workers, say) if not (o.rule == DECILE and parse_label(o.forecast)[1] != TRAILING)]
    same = identical_paths(outcomes)

    wf_ids = {e["config"]["horizon"]: e["config_id"] for e in latest_run(p5_log, (WALK, PATH)) if e["config"]["kind"] == WALK}
    choice = [(o, record(o, dev, s, wf_ids, ddates[rf.start], ddates[-1], CHOICE)) for o in outcomes]
    diag = [(o, record(o, full, s, wf_ids, dates[full_fc.start], dates[-1], DIAGNOSTIC)) for o in diagnostic]
    reproduced = check_reproduces_phase5(choice, p5_log)
    say(f"{reproduced} trailing paths reproduce phase 5's")
    new = [(o, rec) for o, rec in choice if rec["slope_rule"] != TRAILING and key(o) not in same]
    trials = trial_sets(earlier, new, dev.pc.run.book_sizes)
    verdict = verdicts([o for o in outcomes if o.rule != DECILE], trials)
    return Choice(
        dev, full, full_fc, full_slopes, diagnostic, boundary, profile, fill_ic, rf, outcomes, same, verdict, len({path_id(rec) for _, rec in new}),
        gross_by_slope_sign(diagnostic, full_slopes, dates, boundary, full.pc.run.fill),
        negative_share_by_year(full_slopes, dates, full_fc.start, boundary),
        checked, reproduced, choice + diag,
    )


def log_entries(c: Choice, state: dict, now: dt.datetime) -> list[dict]:
    seed = c.dev.lab.cfg.run.seed
    return [experiments.entry(rec, {**o.metrics, "identical_to": c.same.get(key(o))}, seed, state, now) for o, rec in c.records]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-log", action="store_true", help="do not append to experiments.jsonl")
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1), help="worker processes for the optimiser paths")
    args = parser.parse_args(argv)

    from statarb.paper import report

    root = repo_root()
    began = time.perf_counter()

    def say(line: str) -> None:
        print(f"[{time.perf_counter() - began:6.0f}s] {line}", file=sys.stderr, flush=True)

    paths = load_config("data", root)["paths"]
    reports = resolve_path(paths["reports"], root)
    p5_log = experiments.read(reports / PRIOR / "experiments.jsonl")
    c = run_choice(
        load_settings(root), load_long(resolve_path(paths["processed"], root)), load_paper_config(root).choice.slope_rules,
        p5_log, repository_trials(reports, through=PRIOR), root, args.workers, say,
    )
    out_dir = reports / PHASE
    log_path = out_dir / "experiments.jsonl"
    if not args.no_log:
        experiments.append(log_path, log_entries(c, experiments.run_state(root), dt.datetime.now(dt.UTC)))
    text = report.write_choice_report(c, experiments.read(log_path), out_dir)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
