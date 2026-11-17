"""Phase 5: the walk-forward model forecast against the baseline and the three-day lookback, through the same rules.

    uv run python -m statarb.models.run [--no-log] [--workers N]

Development only. Every table is cut at `[period] development_end` of
config/models.toml before anything is computed, so nothing in this run can read
the holdout: targets that would reach past the development end are missing,
and so are fills after it.

Reads config/models.toml (features, walk-forward, model, what to run) and the
phase 2 to 4 configs unchanged: the variants and cost model of
config/costs.toml and the headline optimiser of config/portfolio.toml, with
Model A's residuals and risk. Writes one model per block and horizon to
`[paths] models` of config/data.toml, appends one walk-forward entry per
horizon and one entry per position path and book size to
reports/phase-05/experiments.jsonl, and writes reports/phase-05/ml.md with its
charts.

Every forecast, the model's at each horizon and each variant in `[runs]`, is
calibrated to the optimiser's expected move by phase 3's trailing calibration
and run through each rule in `[runs]` at both phase 4 book sizes. All paths
start flat on the first date every forecast has a calibrated move, so they are
compared over the same dates. Optimiser paths are independent and run in worker
processes; results do not depend on how many.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import pandas as pd

from statarb.backtest import experiments
from statarb.backtest.config import (
    BacktestConfig,
    CostConfig,
    load_backtest_config,
    load_cost_config,
)
from statarb.backtest.cost_run import (
    build_lab,
    evaluate,
    no_trade,
    run_path,
    scores_of,
    variants,
)
from statarb.backtest.engine import TRADING_DAYS, EngineResult
from statarb.backtest.metrics import deflated_sharpe
from statarb.backtest.sweep import Variant, targets
from statarb.backtest.trials import path_id, repository_trials
from statarb.config import load_config, repo_root, resolve_path
from statarb.factors.model import wide
from statarb.models.backend import Model
from statarb.models.config import RULES, ModelsConfig, Period, load_models_config
from statarb.models.features import (
    FeatureSet,
    build_features,
    dispersion,
    known_on,
    ranked_target,
)
from statarb.models.forecast import ForecastRun, ForecastSignal
from statarb.models.ic import daily_rank_ic, ic_summary
from statarb.models.training import model_name
from statarb.portfolio.config import PortfolioConfig, load_portfolio_config
from statarb.portfolio.paths import PathSpec, optimiser_specs
from statarb.portfolio.risk import etf_risk
from statarb.portfolio.run import PortfolioLab, exposures, solver_stats
from statarb.signals.base import Scores
from statarb.signals.calibration import calibration_slope, expected_move, forward_sum
from statarb.signals.tables import (
    Tables,
    build_tables,
    cut_after,
    load_long,
    sector_inputs,
)

PHASE = "phase-05"
PRIOR = "phase-04"
DECILE, ZONE, OPTIMISER = RULES
MODEL_SIGNAL = "model"
IC_HORIZONS = (1, 3, 5)
DECAY_DAYS = 5
EVENT_BUCKETS = 5

Progress = Callable[[str], None]


def model_forecast(horizon: int) -> str:
    return f"model H={horizon}"


def rule_label(rule: str, kappa: float | None) -> str:
    return f"{OPTIMISER} κ = {kappa:g}" if rule == OPTIMISER else rule


# Development data ------------------------------------------------------------------------


def development_tables(long: Mapping[str, pd.DataFrame], period: Period) -> dict[str, pd.DataFrame]:
    """Every long table cut at the development end, as a run on that day would load it."""
    return cut_after(long, pd.Timestamp(period.development_end))


def check_development(tables: Tables, period: Period) -> None:
    """Refuse tables that reach past the development end: the holdout is read only by `statarb.models.holdout`."""
    if tables.dates[-1] > pd.Timestamp(period.development_end):
        raise ValueError(f"the tables reach {tables.dates[-1].date()}, past the development end {period.development_end}: the holdout is read once, by its own runner")


@dataclass(frozen=True)
class Settings:
    """Every config the runner reads, loaded once."""

    mc: ModelsConfig
    cfg: BacktestConfig
    ccfg: CostConfig
    pc: PortfolioConfig
    market: str
    sector_etfs: dict[str, str]
    event_ratio: float

    def validate(self) -> None:
        known = dict(variants(self.cfg, self.ccfg))
        if self.pc.run.variant not in self.mc.runs.variants:
            raise ValueError(f"runs: variants must include the phase 4 headline variant {self.pc.run.variant!r}, the baseline")
        for v in self.mc.runs.variants:
            if v not in known:
                raise ValueError(f"runs: variant {v!r} is not a [[variants]] name in config/costs.toml")
            if known[v].source != "residual" or known[v].holding_days != self.pc.optimiser.horizon_days:
                raise ValueError(f"runs: variant {v!r} must read residuals and hold for the optimiser's horizon, which the calibration uses")
        if self.mc.runs.cost_multipliers[0] != self.pc.headline.cost_multiplier:
            raise ValueError("runs: the first cost multiplier must be the phase 4 headline")
        if self.pc.risk.model != "etf":
            raise ValueError("phase 5 runs Model A's residuals and risk: config/portfolio.toml [risk] model must be etf")
        if self.pc.run.fill != self.ccfg.run.fill:
            raise ValueError("the optimiser and the no-trade zone must fill alike: [run] fill differs between portfolio.toml and costs.toml")


def load_settings(root: Path) -> Settings:
    data_cfg = load_config("data", root)
    factors_cfg = load_config("factors", root)
    cfg = load_backtest_config(root)
    ccfg = load_cost_config(cfg, root)
    s = Settings(
        load_models_config(root), cfg, ccfg, load_portfolio_config(ccfg, root), data_cfg["factors"]["market"],
        factors_cfg["sector_etfs"], float(factors_cfg["events"]["volume_ratio"]),
    )
    s.validate()
    return s


def build_development_lab(long: Mapping[str, pd.DataFrame], s: Settings) -> PortfolioLab:
    """The phase 3 lab and phase 4's Model A risk on the development tables; expected moves are added per forecast."""
    cut = development_tables(long, s.mc.period)
    tables = build_tables(*(cut[k] for k in ("returns", "prices", "residuals", "universe", "sectors")), s.market, s.sector_etfs)
    check_development(tables, s.mc.period)
    lab = build_lab(tables, s.cfg, s.ccfg, s.sector_etfs)
    r = s.pc.risk
    beta_sector = wide(cut["residuals"], "beta_sector", tables.dates, tables.stocks).to_numpy()
    risk = etf_risk(tables, s.sector_etfs, beta_sector, r.factor_window_days, r.factor_min_observations, r.specific_window_days, r.specific_min_observations)
    _, _, _, etf_index = sector_inputs(tables, s.sector_etfs)
    return PortfolioLab({"etf": lab}, s.pc, dict(variants(s.cfg, s.ccfg)), {"etf": risk}, {}, beta_sector, etf_index)


def starting_at(plab: PortfolioLab, start: int, moves: Mapping[str, np.ndarray]) -> PortfolioLab:
    """The lab whose paths start flat on date `start`, with each forecast's expected move for the optimiser."""
    lab = plab.lab
    cfg = replace(lab.cfg, period=replace(lab.cfg.period, start=lab.tables.dates[start].date()))
    return replace(plab, labs={"etf": replace(lab, cfg=cfg, start=start)}, moves={(f, "etf"): m for f, m in moves.items()})


# Forecasts -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Forecasts:
    features: FeatureSet
    signal: dict[str, np.ndarray]     # forecast -> (dates x stocks) score: a variant's signal or the model's forecast
    slope: dict[str, np.ndarray]      # forecast -> (dates,) calibration slope
    move: dict[str, np.ndarray]       # forecast -> (dates x stocks) expected move over the optimiser's horizon
    runs: dict[int, ForecastRun]      # horizon -> the walk-forward
    start: int                        # first date every forecast has a calibrated move

    @property
    def names(self) -> list[str]:
        return list(self.signal)


def build_forecasts(plab: PortfolioLab, mc: ModelsConfig, progress: Progress | None = None) -> Forecasts:
    lab = plab.lab
    tables = lab.tables
    shape = (len(tables.dates), len(tables.stocks))
    signal = {v: scores_of(lab, plab.variants[v]).score for v in mc.runs.variants}
    fs = build_features(tables, mc.features)
    runs = {}
    for H in mc.target.horizons:
        if progress is not None:
            progress(f"walk-forward, H = {H}")
        runs[H] = ForecastSignal(mc, H, progress).run(tables, fs)
        signal[model_forecast(H)] = runs[H].panel(shape)
    h = plab.pc.optimiser.horizon_days
    nt = lab.ccfg.no_trade
    outcome = forward_sum(tables.residual.to_numpy(), h)
    slope = {f: calibration_slope(x, outcome, tables.members, h, nt.calibration_window_days, nt.calibration_min_days) for f, x in signal.items()}
    move = {f: expected_move(signal[f], tables.members, slope[f]) for f in signal}
    has = [np.flatnonzero(np.isfinite(m).any(axis=1)) for m in move.values()]
    if any(len(x) == 0 for x in has):
        raise ValueError("a forecast has no calibrated move before the development end")
    return Forecasts(fs, signal, slope, move, runs, max(int(x[0]) for x in has))


def save_models(fc: Forecasts, model_dir: Path) -> dict[tuple[int, int], tuple[str, str]]:
    """Each block's model in LightGBM's text format: (horizon, block) -> (file name, SHA-256)."""
    out = {}
    for H, run in fc.runs.items():
        for k, fit in enumerate(run.walk.fits):
            name = model_name(fit)
            out[(H, k)] = (name, fit.model.save(model_dir / name))
    return out


# Position paths --------------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    forecast: str
    rule: str
    kappa: float | None
    book: float
    daily: pd.DataFrame
    metrics: dict

    @property
    def label(self) -> str:
        return rule_label(self.rule, self.kappa)

    @property
    def name(self) -> str:
        return f"{self.forecast}, {self.label}"


def _outcome(plab: PortfolioLab, forecast: str, rule: str, kappa: float | None, book: float, result: EngineResult) -> Outcome:
    d, m = evaluate(plab.lab, result, plab.head_setting(), book, plab.kind)
    m.update(exposures(plab, result))
    m.update(solver_stats(result.notes))
    return Outcome(forecast, rule, kappa, book, d, m)


def rule_variant(plab: PortfolioLab, forecast: str) -> Variant:
    """The holding rule a forecast's decile sort uses: its own variant's, or the headline variant's for the model."""
    return plab.variants.get(forecast, plab.variants[plab.pc.run.variant])


def rule_paths(plab: PortfolioLab, fc: Forecasts, forecast: str, rules: tuple[str, ...]) -> list[Outcome]:
    """The decile sort and the no-trade zone at every book size, in this process: each takes seconds."""
    lab = plab.lab
    fill = plab.pc.run.fill
    book_targets = targets(rule_variant(plab, forecast), Scores(fc.signal[forecast]), lab.tables, lab.cfg)
    out = []
    if DECILE in rules:
        result = run_path(lab, book_targets, fill)
        out += [_outcome(plab, forecast, DECILE, None, book, result) for book in plab.pc.run.book_sizes]
    if ZONE in rules:
        move = fc.move[forecast]
        padded = np.hstack([move, np.zeros((move.shape[0], len(lab.tables.hedges)))])
        for book in plab.pc.run.book_sizes:
            out.append(_outcome(plab, forecast, ZONE, None, book, run_path(lab, book_targets, fill, no_trade(lab, book, padded))))
    return out


def optimiser_spec(pc: PortfolioConfig, forecast: str, kappa: float) -> PathSpec:
    """Phase 4's headline optimiser on a forecast's expected move, at a cost multiplier."""
    head = optimiser_specs(pc)[0]
    return replace(head, name=f"{forecast}, {rule_label(OPTIMISER, kappa)}", variant=forecast, cost_multiplier=kappa)


_PLAB: PortfolioLab | None = None


def _init_worker(root: str, moves: dict[str, np.ndarray], start: int) -> None:
    global _PLAB
    root_path = Path(root)
    s = load_settings(root_path)
    processed = resolve_path(load_config("data", root_path)["paths"]["processed"], root_path)
    _PLAB = starting_at(build_development_lab(load_long(processed), s), start, moves)


def _run_optimiser(job: tuple[str, float, float]) -> tuple[Outcome, float]:
    forecast, kappa, book = job
    assert _PLAB is not None
    began = time.perf_counter()
    result = _PLAB.run_path(optimiser_spec(_PLAB.pc, forecast, kappa), book)
    return _outcome(_PLAB, forecast, OPTIMISER, kappa, book, result), time.perf_counter() - began


def run_paths(plab: PortfolioLab, fc: Forecasts, mc: ModelsConfig, root: Path | None, workers: int, progress: Progress | None = None) -> list[Outcome]:
    """Every forecast through every rule at every book size, from `fc.start`, in a fixed order.

    With `workers` above 1 and a `root`, each worker process rebuilds the
    development lab from the processed tables under `root`.
    """
    global _PLAB
    say = progress or (lambda line: None)
    plab = starting_at(plab, fc.start, fc.move)
    rules = mc.runs.rules
    outcomes = [o for f in fc.names for o in rule_paths(plab, fc, f, rules)]
    jobs = [(f, k, b) for f in fc.names for k in mc.runs.cost_multipliers for b in plab.pc.run.book_sizes] if OPTIMISER in rules else []
    say(f"optimiser paths: {len(jobs)} on {max(1, min(workers, len(jobs)))} worker(s)")
    if workers <= 1 or root is None:
        _PLAB = plab
        for i, job in enumerate(jobs):
            out, seconds = _run_optimiser(job)
            outcomes.append(out)
            say(f"  [{i + 1}/{len(jobs)}] {out.name}, ${job[2]:,.0f}: {seconds:.0f}s")
    elif jobs:
        init = (str(root), fc.move, fc.start)
        with ProcessPoolExecutor(min(workers, len(jobs)), mp_context=get_context("spawn"), initializer=_init_worker, initargs=init) as ex:
            for i, (out, seconds) in enumerate(ex.map(_run_optimiser, jobs)):
                outcomes.append(out)
                say(f"  [{i + 1}/{len(jobs)}] {out.name}, ${jobs[i][2]:,.0f}: {seconds:.0f}s")
    order = {f: k for k, f in enumerate(fc.names)}
    rank = {r: k for k, r in enumerate(RULES)}
    return sorted(outcomes, key=lambda o: (o.book, order[o.forecast], rank[o.rule], o.kappa or 0.0))


# IC, importance and events ---------------------------------------------------------------


def evaluation_rows(fc: Forecasts) -> np.ndarray:
    """Feature rows where every forecast has a value: inside the test blocks."""
    ok = np.ones(len(fc.features.day), dtype=bool)
    for panel in fc.signal.values():
        ok &= np.isfinite(fc.features.values_of(panel))
    return ok


def ic_analysis(tables: Tables, fc: Forecasts) -> dict[str, pd.DataFrame]:
    """Daily rank IC of each forecast against ranked residual moves: by target horizon, by year (1-day), and against single later days.

    Outcomes past the development end are missing from the cut tables, so they never count.
    """
    residual = tables.residual.to_numpy()
    fs = fc.features
    rows = evaluation_rows(fc)
    day = fs.day[rows]
    summary, by_year, decay = [], [], []
    for name, panel in fc.signal.items():
        f = fs.values_of(panel)[rows]
        for H in IC_HORIZONS:
            ic = daily_rank_ic(day, f, fs.values_of(ranked_target(residual, tables.members, H))[rows])
            summary.append({"forecast": name, "target": f"{H}-day", **ic_summary(ic)})
            if H == 1:
                year = pd.Series(tables.dates[ic.index.to_numpy()].year, index=ic.index)
                by_year += [{"forecast": name, "year": int(y), **ic_summary(g)} for y, g in ic.groupby(year)]
        for lag in range(1, DECAY_DAYS + 1):
            later = np.full(residual.shape, np.nan)
            later[:-lag] = residual[lag:]
            ic = daily_rank_ic(day, f, fs.values_of(np.where(tables.members, later, np.nan))[rows])
            decay.append({"forecast": name, "day": lag, **ic_summary(ic)})
    return {"summary": pd.DataFrame(summary), "by_year": pd.DataFrame(by_year), "decay": pd.DataFrame(decay)}


def importance(fc: Forecasts, horizon: int) -> pd.DataFrame:
    """Gain summed over the blocks' models, and out-of-sample SHAP: each block's model on its own test rows."""
    fs = fc.features
    x = fs.matrix()
    gain = pd.Series(0.0, index=fs.names)
    abs_shap = np.zeros(len(fs.names))
    signed = np.zeros(len(fs.names))
    n = 0
    for fit in fc.runs[horizon].walk.fits:
        model: Model = fit.model
        gain = gain.add(model.gain().reindex(fs.names).fillna(0.0))
        test = (fs.day >= fit.fold.test_start) & (fs.day < fit.fold.test_stop)
        contrib = model.contributions(x[test])[:, :-1]          # the last column is the bias
        abs_shap += np.abs(contrib).sum(axis=0)
        signed += contrib.sum(axis=0)
        n += int(test.sum())
    total = gain.sum()
    out = pd.DataFrame(
        {
            "feature": fs.names,
            "gain_share": (gain / total).to_numpy() if total > 0 else np.nan,
            "mean_abs_shap": abs_shap / max(n, 1),
            "mean_shap": signed / max(n, 1),
        }
    )
    return out.sort_values(["mean_abs_shap", "feature"], ascending=[False, True], ignore_index=True)


def event_response(tables: Tables, fc: Forecasts, horizon: int, baseline: str, event_ratio: float) -> pd.DataFrame:
    """Mean forecast and realised ranked target by quintile of the day's residual, split by the phase 1 event flag."""
    fs = fc.features
    rows = evaluation_rows(fc)
    target = fs.values_of(ranked_target(tables.residual.to_numpy(), tables.members, horizon))
    d = pd.DataFrame(
        {
            "day": fs.day[rows],
            "move": fs.frame["res_sum_1"].to_numpy()[rows],
            "event": fs.frame["volume_ratio"].to_numpy()[rows] >= event_ratio,
            "forecast": fs.values_of(fc.signal[model_forecast(horizon)])[rows],
            "baseline": fs.values_of(fc.signal[baseline])[rows],
            "realised": target[rows],
        }
    )
    pct = d.groupby("day")["move"].rank(pct=True)
    d["quintile"] = np.minimum(np.ceil(pct * EVENT_BUCKETS), EVENT_BUCKETS).astype(int)
    g = d.groupby(["quintile", "event"])
    out = g.agg(rows=("move", "size"), mean_move=("move", "mean"), forecast=("forecast", "mean"), baseline=("baseline", "mean"), realised=("realised", "mean"))
    return out.reset_index()


def dispersion_defect(tables: Tables) -> dict:
    """How far dispersion over the whole stock axis is from dispersion over the stocks known on each day.

    The whole-axis definition counts a member before its first residual, which
    the development tables know of only because it has a residual later. Days
    where both have a value and they differ are measured; days where only the
    whole-axis one has a value (fewer than two stocks known) are counted apart.
    A statistic of a feature, not of a return: no model is trained on it.
    """
    raw = tables.raw.to_numpy()
    right = dispersion(raw, tables.members & known_on(tables.residual.to_numpy()))
    wrong = dispersion(raw, tables.members)
    both = np.isfinite(right) & np.isfinite(wrong)
    diff = np.where(both, np.abs(wrong - right), np.nan)
    differ = both & (diff > 0)
    one = np.isfinite(right) != np.isfinite(wrong)
    days = np.isfinite(right) | np.isfinite(wrong)
    idx = np.flatnonzero(differ)
    rel = diff[differ] / right[differ]
    return {
        "days": int(days.sum()),
        "first_day": str(tables.dates[np.flatnonzero(days)[0]].date()) if days.any() else None,
        "last_day": str(tables.dates[-1].date()),
        "days_differ": int(differ.sum()),
        "days_one_defined": int(one.sum()),
        "first_differ": str(tables.dates[idx[0]].date()) if len(idx) else None,
        "last_differ": str(tables.dates[idx[-1]].date()) if len(idx) else None,
        "median_difference": float(np.median(diff[differ])) if len(idx) else 0.0,
        "largest_difference": float(diff[differ].max()) if len(idx) else 0.0,
        "median_relative": float(np.median(rel)) if len(idx) else 0.0,
        "largest_relative": float(rel.max()) if len(idx) else 0.0,
    }


def calibration(fc: Forecasts, dates: pd.DatetimeIndex, members: np.ndarray) -> pd.DataFrame:
    """Each forecast's calibration over the path dates: the slope, and the size of the expected move it gives."""
    rows = []
    span = slice(fc.start, len(dates))
    for f in fc.names:
        b = fc.slope[f][span]
        move = np.where(members[span], np.abs(fc.move[f][span]), np.nan)
        rows.append(
            {
                "forecast": f,
                "mean_slope": float(np.nanmean(b)),
                "positive_share": float(np.mean(b[np.isfinite(b)] > 0)),
                "mean_abs_move": float(np.nanmean(move)),
            }
        )
    return pd.DataFrame(rows)


# Log, trials and verdicts -----------------------------------------------------------------


def _plain(value):
    """Dates and tuples as JSON values, so a config hashes the way it is written."""
    return json.loads(json.dumps(value, default=str))


def walk_forward_config(mc: ModelsConfig, fs: FeatureSet, horizon: int, last: pd.Timestamp) -> dict:
    """What defines a horizon's walk-forward; `[runs]` is left out, since it changes no model."""
    models = {k: v for k, v in asdict(mc).items() if k != "runs"}
    return {"kind": "walk-forward", "horizon": horizon, "models": _plain(models), "features": list(fs.names), "development_end": str(last.date())}


def walk_forward_metrics(run: ForecastRun, dates: pd.DatetimeIndex, saved: Mapping[tuple[int, int], tuple[str, str]], horizon: int) -> dict:
    blocks = []
    for k, fit in enumerate(run.walk.fits):
        f = fit.fold
        name, sha = saved.get((horizon, k), (None, None))
        blocks.append(
            {
                "test_first": str(dates[f.test_start].date()),
                "test_last": str(dates[f.test_stop - 1].date()),
                "train_first": str(fit.train_first.date()),
                "train_last": str(fit.train_last.date()),
                "train_rows": fit.train_rows,
                "chosen": asdict(fit.chosen),
                "grid": [asdict(g) for g in fit.grid],
                "model_file": name,
                "model_sha256": sha,
            }
        )
    return {"blocks": blocks, "grid_points_tried": sum(len(b["grid"]) for b in blocks)}


def path_record(
    o: Outcome, cfg: BacktestConfig, ccfg: CostConfig, pc: PortfolioConfig, variant: Variant, wf_ids: Mapping[int, str], first: pd.Timestamp, last: pd.Timestamp
) -> dict:
    """The configuration part of a path's log entry, which its config_id hashes.

    A variant's path has the keys its phase 3 or phase 4 entry has, so it is the
    same trial over fewer dates: `start` is the signal start of config/backtest.toml
    as there, and `first_date` and `last_date` give the dates this path ran. A
    model path names its forecast's walk-forward in `model`, so each horizon's
    paths are new trials. Book sizes are not separate trials.
    """
    is_model = o.forecast.startswith(f"{MODEL_SIGNAL} ")
    if is_model:
        horizon = int(o.forecast.split("=")[1])
        signal = {"signal": MODEL_SIGNAL, "source": "features", "lookback_days": None, "vol_scaled": None, "holding_days": variant.holding_days}
        model = {"horizon": horizon, "walk_forward": wf_ids[horizon]}
    else:
        signal, model = asdict(variant), None
    optimiser = None
    if o.rule == OPTIMISER:
        spec = optimiser_spec(pc, o.forecast, o.kappa)
        optimiser = {
            "risk_model": spec.risk,
            "risk_aversion": spec.risk_aversion,
            "cost_multiplier": spec.cost_multiplier,
            "turnover_budget": spec.turnover_budget,
            "min_trade_dollars": spec.min_trade_dollars,
            "re_solve": spec.re_solve,
            **asdict(pc.optimiser),
            "risk": {k: v for k, v in asdict(pc.risk).items() if k != "model"},
        }
    zone = o.rule == ZONE
    return {
        "kind": "path",
        **signal,
        "name": o.name,
        "forecast": o.forecast,
        "rule": o.label,
        "fill": pc.run.fill,
        "book_size": o.book,
        "no_trade_zone": zone,
        "spread": ccfg.spread.headline_half_spread_bps,
        "half_tick_floor": ccfg.spread.half_tick_floor,
        "impact_coefficient": ccfg.impact.headline_coefficient,
        "commission": asdict(ccfg.schedule(ccfg.commission.headline)),
        "borrow": asdict(ccfg.borrow),
        "no_trade": asdict(ccfg.no_trade) if zone else None,
        "decile": cfg.portfolio.decile if o.rule != OPTIMISER else None,
        "start": cfg.period.start.isoformat(),
        "residuals": None,
        "optimiser": optimiser,
        "model": model,
        "calibration_horizon_days": pc.optimiser.horizon_days,
        "first_date": str(first.date()),
        "last_date": str(last.date()),
    }


@dataclass(frozen=True)
class Logged:
    """The run's log entries' configurations: one per walk-forward, then one per outcome, in outcome order."""

    walk_forward: dict[int, tuple[dict, dict]]     # horizon -> (config, metrics)
    paths: list[dict]

    @property
    def walk_forward_ids(self) -> dict[int, str]:
        return {H: experiments.config_id(c) for H, (c, _) in self.walk_forward.items()}


def records(outcomes: list[Outcome], plab: PortfolioLab, fc: Forecasts, mc: ModelsConfig, saved: Mapping[tuple[int, int], tuple[str, str]]) -> Logged:
    lab = plab.lab
    dates = lab.tables.dates
    wf = {H: (walk_forward_config(mc, fc.features, H, dates[-1]), walk_forward_metrics(run, dates, saved, H)) for H, run in fc.runs.items()}
    ids = {H: experiments.config_id(c) for H, (c, _) in wf.items()}
    base_cfg = lab.cfg
    paths = [path_record(o, base_cfg, lab.ccfg, plab.pc, rule_variant(plab, o.forecast), ids, dates[fc.start], dates[-1]) for o in outcomes]
    return Logged(wf, paths)


def trial_sets(earlier: dict[str, float], outcomes: list[Outcome], logged: Logged, books: tuple[float, ...]) -> dict[float, dict[str, float]]:
    """Daily gross Sharpe of every position path by path id, at each book size: earlier phases' paths plus this run's.

    A variant's path replaces its earlier entry, as a later phase reading this
    log would; a model path is new.
    """
    out = {}
    for book in books:
        paths = dict(earlier)
        for o, rec in zip(outcomes, logged.paths, strict=True):
            if o.book == book:
                paths[path_id(rec)] = o.metrics["gross_sharpe"] / math.sqrt(TRADING_DAYS)
        out[book] = paths
    return out


def verdicts(outcomes: list[Outcome], trials: dict[float, dict[str, float]]) -> pd.DataFrame:
    """The bar from the phase 3 brief: t of at least 2 and a deflated-Sharpe probability of at least 0.95."""
    rows = []
    for o in outcomes:
        sharpes = np.array(list(trials[o.book].values()))
        ds = deflated_sharpe(o.daily["net"], len(sharpes), sharpes)
        rows.append(
            {
                "forecast": o.forecast,
                "rule": o.label,
                "book": o.book,
                "net_sharpe": o.metrics["sharpe"],
                "t_stat": o.metrics["t_stat"],
                "benchmark_sharpe": ds["benchmark_sharpe"],
                "deflated_probability": ds["deflated_sharpe_probability"],
                "trials": len(sharpes),
                "clears": bool(o.metrics["t_stat"] >= 2 and ds["deflated_sharpe_probability"] >= 0.95),
            }
        )
    return pd.DataFrame(rows)


def log_entries(outcomes: list[Outcome], logged: Logged, mc: ModelsConfig, cfg: BacktestConfig, state: dict, now: dt.datetime) -> list[dict]:
    entries = [experiments.entry(c, m, mc.lightgbm.seed, state, now) for c, m in logged.walk_forward.values()]
    entries += [experiments.entry(rec, o.metrics, cfg.run.seed, state, now) for o, rec in zip(outcomes, logged.paths, strict=True)]
    return entries


# Main ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Results:
    """Everything the report reads."""

    plab: PortfolioLab
    mc: ModelsConfig
    fc: Forecasts
    outcomes: list[Outcome]
    ic: dict[str, pd.DataFrame]
    importance: dict[int, pd.DataFrame]
    events: pd.DataFrame
    defect: dict
    calibration: pd.DataFrame
    verdict: pd.DataFrame
    logged: Logged
    event_ratio: float


def run_development(
    s: Settings, long: Mapping[str, pd.DataFrame], model_dir: Path, earlier: dict[str, float],
    root: Path | None = None, workers: int = 1, progress: Progress | None = None,
) -> Results:
    """The whole development run from the long tables, which may reach the holdout: they are cut first.

    `earlier` holds the trials of the earlier phases' logs. With `root` and
    `workers` above 1, optimiser paths run in worker processes that load the
    tables under `root`.
    """
    say = progress or (lambda line: None)
    say(f"cutting the tables at the development end, {s.mc.period.development_end}")
    plab = build_development_lab(long, s)
    tables = plab.lab.tables
    fc = build_forecasts(plab, s.mc, say)
    saved = save_models(fc, model_dir)
    say(f"paths from {tables.dates[fc.start].date()} to {tables.dates[-1].date()}")
    outcomes = run_paths(plab, fc, s.mc, root, workers, say)
    say("IC, importance, events")
    ic = ic_analysis(tables, fc)
    imp = {H: importance(fc, H) for H in s.mc.target.horizons}
    events = event_response(tables, fc, s.mc.target.headline_horizon, s.pc.run.variant, s.event_ratio)
    logged = records(outcomes, plab, fc, s.mc, saved)
    trials = trial_sets(earlier, outcomes, logged, s.pc.run.book_sizes)
    return Results(
        plab, s.mc, fc, outcomes, ic, imp, events, dispersion_defect(tables), calibration(fc, tables.dates, tables.members),
        verdicts(outcomes, trials), logged, s.event_ratio,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-log", action="store_true", help="do not append to experiments.jsonl")
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1), help="worker processes for the optimiser paths")
    args = parser.parse_args(argv)

    from statarb.models import report

    root = repo_root()
    began = time.perf_counter()

    def say(line: str) -> None:
        print(f"[{time.perf_counter() - began:6.0f}s] {line}", file=sys.stderr, flush=True)

    paths = load_config("data", root)["paths"]
    reports = resolve_path(paths["reports"], root)
    long = load_long(resolve_path(paths["processed"], root))
    earlier = repository_trials(reports, through=PRIOR)
    res = run_development(load_settings(root), long, resolve_path(paths["models"], root), earlier, root, args.workers, say)
    out_dir = reports / PHASE
    log_path = out_dir / "experiments.jsonl"
    if not args.no_log:
        state = experiments.run_state(root)
        experiments.append(log_path, log_entries(res.outcomes, res.logged, res.mc, res.plab.lab.cfg, state, dt.datetime.now(dt.UTC)))
    text = report.write_report(res, out_dir)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
