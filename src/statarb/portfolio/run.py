"""Phase 4: the baseline signal through the optimiser, against the decile sort, under the phase 3 cost model.

    uv run python -m statarb.portfolio.run [--no-log] [--workers N]
    uv run python -m statarb.portfolio.run --choose-risk-aversion

Reads config/portfolio.toml (optimiser, risk models, sweep), config/costs.toml
(the configurations and the phase 3 cost model, unchanged), config/backtest.toml
(signals), the phase 0 and 1 tables and Model B's `residuals_pca.parquet`.
Appends one entry per path, book size and cost setting to
reports/phase-04/experiments.jsonl and writes reports/phase-04/portfolio.md with
its charts. Each optimiser path is independent, so paths run in worker
processes; results do not depend on how many.

`--choose-risk-aversion` applies `[risk_aversion_rule]`: it runs the headline
optimiser over the first days with an expected move at each candidate λ and
prints the capital each deploys. It reads no return of any path.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import pandas as pd

from statarb.backtest import experiments
from statarb.backtest.config import load_backtest_config, load_cost_config
from statarb.backtest.cost_run import (
    CostSetting,
    Lab,
    build_lab,
    cost,
    earlier_phase,
    evaluate,
    expected_move_of,
    headline,
    scores_of,
    variants,
)
from statarb.backtest.costs import before
from statarb.backtest.engine import FILL_TIMINGS, TRADING_DAYS, EngineResult, run
from statarb.backtest.metrics import deflated_sharpe
from statarb.backtest.sweep import Variant, targets
from statarb.backtest.trials import path_id, repository_trials
from statarb.config import load_config, repo_root, resolve_path
from statarb.factors.model import wide
from statarb.factors.pca import PcaModelConfig
from statarb.io import read_parquet
from statarb.portfolio.config import PortfolioConfig, load_portfolio_config
from statarb.portfolio.optimiser import IDLE, DayNote, DecileSort, Optimiser, Settings
from statarb.portfolio.paths import PathSpec, bracketed, decile_specs, optimiser_specs
from statarb.portfolio.risk import RiskModel, etf_risk, pca_risk
from statarb.signals.tables import load_tables, sector_inputs

PHASE = "phase-04"
MATERIAL_BREACH = 1e-3            # 0.1% of capital


@dataclass(frozen=True)
class PortfolioLab:
    """The phase 3 lab on each model's residuals, the risk models and the expected moves the paths need."""

    labs: dict[str, Lab]                       # residuals model -> lab whose tables carry those residuals
    pc: PortfolioConfig
    variants: dict[str, Variant]
    risks: dict[str, RiskModel]
    moves: dict[tuple[str, str], np.ndarray]   # (variant, residuals) -> expected move, (dates, stocks)
    beta_sector: np.ndarray                    # Model A's sector betas, for realised exposure
    etf_index: np.ndarray

    @property
    def lab(self) -> Lab:
        return self.labs["etf"]

    @property
    def kind(self) -> str:
        return FILL_TIMINGS[self.pc.run.fill][0]

    @property
    def delay(self) -> int:
        return FILL_TIMINGS[self.pc.run.fill][1]

    def head_setting(self) -> CostSetting:
        return headline(self.lab.ccfg)

    def bracket(self) -> list[CostSetting]:
        h = self.head_setting()
        return [CostSetting(x, h.impact, h.commission) for x in self.lab.ccfg.spread.bracket_half_spread_bps if x != h.spread]

    def settings(self, spec: PathSpec) -> Settings:
        o = self.pc.optimiser
        return Settings(
            risk_aversion=spec.risk_aversion,
            cost_multiplier=spec.cost_multiplier,
            turnover_budget=spec.turnover_budget,
            min_trade_dollars=spec.min_trade_dollars,
            re_solve=spec.re_solve,
            re_solve_rounds=o.re_solve_rounds,
            horizon_days=o.horizon_days,
            position_cap=o.position_cap,
            adv_cap=o.adv_cap,
            gross_cap=o.gross_cap,
            dollar_tolerance=o.dollar_tolerance,
            factor_tolerance=o.factor_tolerance,
            solver=o.solver,
            solver_options=dict(o.solver_options),
        )

    def optimiser(self, spec: PathSpec, book: float) -> Optimiser:
        lab = self.lab
        trading = cost(lab, self.head_setting(), book, self.kind)
        return Optimiser(
            settings=self.settings(spec),
            expected_move=self.moves[(spec.variant, spec.residuals)],
            members=lab.tables.members,
            risk=self.risks[spec.risk],
            cost=trading,
            decision_drift=before(lab.costs.close / trading.fill_price),
            decision_price=lab.decision_price,
            delay=self.delay,
            start=lab.start,
        )

    def policy(self, spec: PathSpec, book: float) -> Optimiser | DecileSort:
        if spec.is_decile:
            lab = self.labs[spec.residuals]
            variant = self.variants[spec.variant]
            return DecileSort(targets(variant, scores_of(lab, variant), lab.tables, lab.cfg), self.delay)
        return self.optimiser(spec, book)

    def run_path(self, spec: PathSpec, book: float, rows: int | None = None) -> EngineResult:
        """The path at a book size, over the first `rows` grid times if given."""
        grid = getattr(self.lab.grids, self.kind)
        if rows is not None:
            grid = replace(grid, dates=grid.dates[:rows], returns=grid.returns[:rows], tradable=grid.tradable[:rows])
        policy = self.policy(spec, book)
        return run(np.full(grid.returns.shape, np.nan), grid, self.delay, self.lab.borrow_rate[: len(grid.dates)], policy)


def with_residuals(lab: Lab, residuals: pd.DataFrame) -> Lab:
    """The lab with another model's residuals in its tables: signals and calibration read them; costs and fills do not change."""
    t = lab.tables
    return replace(lab, tables=replace(t, residual=wide(residuals, "residual", t.dates, t.stocks)))


def build_portfolio_lab(lab: Lab, pc: PortfolioConfig, residuals_a: pd.DataFrame, residuals_b: pd.DataFrame, sector_etfs: dict[str, str], k: int) -> PortfolioLab:
    """Everything the paths share, from the phase 3 lab and both residual tables."""
    tables = lab.tables
    labs = {"etf": lab, "pca": with_residuals(lab, residuals_b)}
    names = dict(variants(lab.cfg, lab.ccfg))
    for v in (pc.run.variant, pc.run.comparison):
        if names[v].holding_days != pc.optimiser.horizon_days:
            raise ValueError(f"variant {v!r}: the expected move's horizon must equal its holding period, which the calibration uses")
    r = pc.risk
    beta_sector = wide(residuals_a, "beta_sector", tables.dates, tables.stocks).to_numpy()
    risks = {
        "etf": etf_risk(tables, sector_etfs, beta_sector, r.factor_window_days, r.factor_min_observations, r.specific_window_days, r.specific_min_observations),
        "pca": pca_risk(residuals_b, tables.dates, tables.stocks, k, r.specific_window_days, r.specific_min_observations),
    }
    n = len(tables.stocks)
    moves = {}
    for v, res in ((pc.run.variant, "etf"), (pc.run.variant, "pca"), (pc.run.comparison, "etf")):
        lab_r = labs[res]
        moves[(v, res)] = expected_move_of(lab_r, names[v], scores_of(lab_r, names[v]))[:, :n]
    _, _, _, etf_index = sector_inputs(tables, sector_etfs)
    return PortfolioLab(labs, pc, names, risks, moves, beta_sector, etf_index)


def load_portfolio_lab(root: Path) -> PortfolioLab:
    data_cfg = load_config("data", root)
    factors_cfg = load_config("factors", root)
    sector_etfs = factors_cfg["sector_etfs"]
    processed = resolve_path(data_cfg["paths"]["processed"], root)
    cfg = load_backtest_config(root)
    ccfg = load_cost_config(cfg, root)
    pc = load_portfolio_config(ccfg, root)
    tables = load_tables(processed, data_cfg["factors"]["market"], sector_etfs)
    lab = build_lab(tables, cfg, ccfg, sector_etfs)
    residuals_a = read_parquet(processed / "residuals.parquet")
    residuals_b = read_parquet(processed / "residuals_pca.parquet")
    k = PcaModelConfig.from_config(factors_cfg["pca"]).factors
    return build_portfolio_lab(lab, pc, residuals_a, residuals_b, sector_etfs, k)


# Evaluation ------------------------------------------------------------------------


def exposures(plab: PortfolioLab, result: EngineResult) -> dict[str, float]:
    """Realised factor exposure per dollar of capital, against Model A for every path.

    The book's net market beta and its net exposure to each sector factor (Model
    A betas of the holdings carried into each day), and the P&L of the fitted
    part of each stock's close-to-close return, which a factor-neutral book
    should neither earn nor lose. P&L on an open grid runs open to open, so the
    split is approximate there, as in phase 2.
    """
    lab = plab.lab
    tables = lab.tables
    n = len(tables.stocks)
    prev = np.vstack([np.zeros((1, result.holdings.shape[1])), result.holdings[:-1]])[:, :n]
    keep = np.arange(len(tables.dates)) >= lab.start
    resid = tables.residual.to_numpy()
    raw = np.nan_to_num(tables.raw.to_numpy())
    fitted_ret = np.where(np.isfinite(resid), raw - np.nan_to_num(resid), 0.0)
    fitted = (prev * fitted_ret).sum(axis=1)[keep]
    beta = np.nansum(prev * tables.beta_market.to_numpy(), axis=1)[keep]
    loading = np.nan_to_num(prev * plab.beta_sector)
    sectors = np.stack([np.where(plab.etf_index == j, loading, 0.0).sum(axis=1) for j in range(len(tables.hedges) - 1)], axis=1)[keep]
    sector_abs = np.abs(sectors).sum(axis=1)
    return {
        "beta_mean": float(beta.mean()),
        "beta_sd": float(beta.std()),
        "sector_abs_mean": float(sector_abs.mean()),
        "sector_abs_sd": float(sector_abs.std()),
        "fitted_ann": float(fitted.mean() * TRADING_DAYS),
        "fitted_vol": float(fitted.std() * math.sqrt(TRADING_DAYS)),
    }


def solver_stats(notes: tuple[DayNote, ...]) -> dict[str, float]:
    """Solver outcomes: idle days (nothing to optimise), failed days (book held), trades and breaches.

    Solve times are wall-clock and differ between runs, so they stay out of the
    metrics and the report, which must rebuild byte for byte; `solve_seconds`
    gives them to the runner's progress lines instead.
    """
    if not notes:
        return {}
    d = pd.DataFrame([vars(x) for x in notes])
    ok = d["status"] == "optimal"
    idle = d["status"].isin(IDLE)
    return {
        "solver_days": len(d),
        "idle_days": int(idle.sum()),
        "failed_days": int((~ok & ~idle).sum()),
        "trades_per_day": float(d.loc[ok, "trades"].mean()),
        "dropped_per_day": float(d.loc[ok, "dropped"].mean()),
        "dollar_breach_max": float(d.loc[ok, "dollar_breach"].max()),
        "factor_breach_max": float(d.loc[ok, "factor_breach"].max()),
        "dollar_breach_material_days": int((d.loc[ok, "dollar_breach"] > MATERIAL_BREACH).sum()),
        "factor_breach_material_days": int((d.loc[ok, "factor_breach"] > MATERIAL_BREACH).sum()),
        "re_solve_rounds_mean": float(d.loc[ok, "rounds"].mean()),
        "re_solve_failed_days": int((d.loc[ok, "re_solve_status"] != "").sum()),
        "ex_ante_vol": float(d.loc[ok, "ex_ante_vol"].mean() * math.sqrt(TRADING_DAYS)),
        "ex_ante_move": float(d.loc[ok, "expected"].mean()),
    }


@dataclass(frozen=True)
class Outcome:
    spec: PathSpec
    book: float
    setting: CostSetting
    daily: pd.DataFrame
    metrics: dict
    result: EngineResult | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return self.spec.name


def outcomes_for(plab: PortfolioLab, spec: PathSpec, book: float, result: EngineResult) -> list[Outcome]:
    """A path at the headline cost, with its exposures and solver statistics, and at the bracket if it is re-costed."""
    head = plab.head_setting()
    out = []
    for setting in [head, *(plab.bracket() if bracketed(spec) else [])]:
        d, m = evaluate(plab.lab, result, setting, book, plab.kind)
        if setting == head:
            m.update(exposures(plab, result))
            m.update(solver_stats(result.notes))
        out.append(Outcome(spec, book, setting, d, m, result if setting == head else None))
    return out


# Worker processes ----------------------------------------------------------------------

_PLAB: PortfolioLab | None = None


def _init_worker(root: str) -> None:
    global _PLAB
    _PLAB = load_portfolio_lab(Path(root))


def solve_seconds(notes: tuple[DayNote, ...]) -> float | None:
    """The mean wall-clock time to decide an optimal day, or None for a path with no solver."""
    times = [n.seconds for n in notes if n.status == "optimal"]
    return sum(times) / len(times) if times else None


def _progress(i: int, n: int, job: tuple[PathSpec, float], seconds: float, per_solve: float | None) -> str:
    solve = f", {per_solve:.3f}s a solve" if per_solve is not None else ""
    return f"[{i + 1}/{n}] {job[0].name} ${job[1]:,.0f}: {seconds:.0f}s{solve}"


def _run_job(job: tuple[PathSpec, float]) -> tuple[list[Outcome], float, float | None]:
    spec, book = job
    assert _PLAB is not None
    began = time.perf_counter()
    result = _PLAB.run_path(spec, book)
    # The engine result stays in the worker except at the headline cost, where the report needs holdings.
    return outcomes_for(_PLAB, spec, book, result), time.perf_counter() - began, solve_seconds(result.notes)


def jobs(pc: PortfolioConfig) -> list[tuple[PathSpec, float]]:
    """Every path at every book size, decile sorts first; results are collected in this order."""
    return [(spec, b) for spec in [*decile_specs(pc), *optimiser_specs(pc)] for b in pc.run.book_sizes]


def run_all(plab: PortfolioLab, root: Path | None, workers: int) -> list[Outcome]:
    """Every path in job order. With `workers` above 1, each worker process loads the lab from `root`."""
    todo = jobs(plab.pc)
    results: list[list[Outcome]] = []
    if workers <= 1:
        global _PLAB
        _PLAB = plab
        for i, job in enumerate(todo):
            out, seconds, per_solve = _run_job(job)
            results.append(out)
            print(_progress(i, len(todo), job, seconds, per_solve), file=sys.stderr)
    else:
        with ProcessPoolExecutor(workers, mp_context=get_context("spawn"), initializer=_init_worker, initargs=(str(root),)) as ex:
            for i, (out, seconds, per_solve) in enumerate(ex.map(_run_job, todo)):
                results.append(out)
                print(_progress(i, len(todo), todo[i], seconds, per_solve), file=sys.stderr)
    return [o for r in results for o in r]


# The headline risk aversion ------------------------------------------------------------


def choose_risk_aversion(plab: PortfolioLab) -> tuple[float, pd.DataFrame]:
    """`[risk_aversion_rule]`: mean capital deployed over the first days with an expected move, at each candidate and book.

    Reads only the optimiser's own decisions over those days, never a return.
    The headline is the largest candidate whose deployment reaches the minimum
    at every book size.
    """
    pc = plab.pc
    rule = pc.risk_aversion_rule
    head = optimiser_specs(pc)[0]
    move = plab.moves[(head.variant, head.residuals)]
    has = np.flatnonzero(np.isfinite(move).any(axis=1) & (np.arange(len(move)) >= plab.lab.start))
    first = int(has[0])
    rows = first + rule.days + plab.delay
    table = []
    for lam in rule.candidates:
        spec = replace(head, risk_aversion=lam)
        for book in pc.run.book_sizes:
            notes = [x for x in plab.run_path(spec, book, rows).notes if x.status == "optimal" and x.date_index >= first]
            table.append({"risk_aversion": lam, "book": book, "days": len(notes), "capital": float(np.mean([x.gross for x in notes]))})
    frame = pd.DataFrame(table)
    ok = frame.groupby("risk_aversion")["capital"].min() >= rule.min_capital
    passing = ok[ok].index
    return (float(passing.max()) if len(passing) else float("nan")), frame


# Trials, verdicts and the log ------------------------------------------------------------


def record(o: Outcome, plab: PortfolioLab) -> dict:
    """The configuration part of a log entry, which its config_id hashes.

    A decile path on Model A's residuals has the keys of phase 3's, so it is
    the same trial; a path on Model B's names its residuals, and an optimiser
    path its settings, but not the book size, so book sizes are not separate
    trials (phase 4 brief, "Trials").
    """
    pc, cc, cfg = plab.pc, plab.lab.ccfg, plab.lab.cfg
    spec = o.spec
    optimiser = None
    if not spec.is_decile:
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
    return {
        **asdict(plab.variants[spec.variant]),
        "name": spec.name,
        "fill": pc.run.fill,
        "book_size": o.book,
        "no_trade_zone": False,
        "spread": o.setting.spread,
        "half_tick_floor": cc.spread.half_tick_floor,
        "impact_coefficient": o.setting.impact,
        "commission": asdict(cc.schedule(o.setting.commission)),
        "borrow": asdict(cc.borrow),
        "no_trade": None,
        "decile": cfg.portfolio.decile if spec.is_decile else None,
        "start": cfg.period.start.isoformat(),
        "residuals": None if spec.residuals == "etf" else spec.residuals,
        "optimiser": optimiser,
    }


def trial_sets(earlier: dict[str, float], outcomes: list[Outcome], plab: PortfolioLab) -> dict[float, dict[str, float]]:
    """Daily gross Sharpe of every position path by path id, at each book size: earlier phases' paths plus this run's at that book."""
    head = plab.head_setting()
    out = {}
    for book in plab.pc.run.book_sizes:
        paths = dict(earlier)
        for o in outcomes:
            if o.setting == head and o.book == book:
                paths[path_id(record(o, plab))] = o.metrics["gross_sharpe"] / math.sqrt(TRADING_DAYS)
        out[book] = paths
    return out


def verdicts(outcomes: list[Outcome], trials: dict[float, dict[str, float]], head: CostSetting) -> pd.DataFrame:
    """The bar from the phase 3 brief, for every path at the headline cost."""
    rows = []
    for o in outcomes:
        if o.setting != head:
            continue
        sharpes = np.array(list(trials[o.book].values()))
        ds = deflated_sharpe(o.daily["net"], len(sharpes), sharpes)
        rows.append(
            {
                "configuration": o.name,
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


def log_entries(outcomes: list[Outcome], plab: PortfolioLab, state: dict, now: dt.datetime) -> list[dict]:
    return [experiments.entry(record(o, plab), o.metrics, plab.lab.cfg.run.seed, state, now) for o in outcomes]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-log", action="store_true", help="do not append to experiments.jsonl")
    parser.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 1), help="worker processes for the paths")
    parser.add_argument("--choose-risk-aversion", action="store_true", help="apply [risk_aversion_rule] and print the table")
    args = parser.parse_args(argv)

    from statarb.portfolio import report

    root = repo_root()
    plab = load_portfolio_lab(root)
    if args.choose_risk_aversion:
        chosen, frame = choose_risk_aversion(plab)
        print(frame.to_string(index=False))
        print(f"headline risk aversion by the rule: {chosen:g}")
        return 0
    outcomes = run_all(plab, root, args.workers)
    reports = resolve_path(load_config("data", root)["paths"]["reports"], root)
    out_dir = reports / PHASE
    log_path = out_dir / "experiments.jsonl"
    head = plab.head_setting()
    trials = trial_sets(repository_trials(reports, through=earlier_phase(PHASE)), outcomes, plab)
    verdict = verdicts(outcomes, trials, head)
    if not args.no_log:
        experiments.append(log_path, log_entries(outcomes, plab, experiments.run_state(root), dt.datetime.now(dt.UTC)))
    phase_3 = experiments.read(reports / earlier_phase(PHASE) / "experiments.jsonl")
    text = report.write_report(plab, outcomes, verdict, phase_3, experiments.read(log_path), out_dir)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
