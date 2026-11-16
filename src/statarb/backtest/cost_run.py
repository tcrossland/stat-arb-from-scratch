"""Phase 3: re-run the phase 2 baseline and its comparisons under the cost model.

    uv run python -m statarb.backtest.cost_run [--no-log]

Reads config/backtest.toml (signals, holding rules, s-score), config/costs.toml
(configurations, cost model, book sizes, no-trade zone) and the phase 0 and 1
tables. Appends one entry per configuration, book size and cost setting to
reports/phase-03/experiments.jsonl and writes reports/phase-03/costs.md with
its charts. To try other settings, set a config overlay
(STATARB_CONFIG_OVERLAY); never edit the config files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from dataclasses import asdict, dataclass, field
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
from statarb.backtest.costs import (
    COMPONENTS,
    CommissionSchedule,
    CostInputs,
    NoTradeZone,
    TradingCost,
    before,
    borrow_rates,
    build_cost_inputs,
    trading_cost,
)
from statarb.backtest.engine import (
    FILL_TIMINGS,
    TRADING_DAYS,
    EngineResult,
    Policy,
    daily_returns,
    run,
)
from statarb.backtest.metrics import deflated_sharpe, sharpe, summary
from statarb.backtest.sweep import (
    SSCORE,
    SSCORE_VARIANT,
    Grids,
    Variant,
    build_grids,
    signal_of,
    start_index,
    targets,
)
from statarb.backtest.trials import path_id, repository_trials
from statarb.config import load_config, repo_root, resolve_path
from statarb.signals.base import Scores
from statarb.signals.calibration import calibration_slope, expected_move, forward_sum
from statarb.signals.registry import make_signal
from statarb.signals.tables import Tables, load_tables

PHASE = "phase-03"
SSCORE_NAME = "s-score"


@dataclass(frozen=True)
class CostSetting:
    """One cost model: a spread (estimator name or fixed half-spread in bps), impact coefficient and commission schedule."""

    spread: str | float
    impact: float
    commission: str

    def label(self) -> str:
        spread = f"{self.spread} estimate" if isinstance(self.spread, str) else f"half-spread {self.spread:g} bps"
        return f"{spread}, impact {self.impact:g}, {self.commission}"


def headline(ccfg: CostConfig) -> CostSetting:
    return CostSetting(ccfg.spread.headline_half_spread_bps, ccfg.impact.headline_coefficient, ccfg.commission.headline)


def alternatives(ccfg: CostConfig) -> list[CostSetting]:
    """Every setting that differs from the headline in one respect."""
    h = headline(ccfg)
    out = [CostSetting(x, h.impact, h.commission) for x in ccfg.spread.bracket_half_spread_bps if x != h.spread]
    out += [CostSetting(m, h.impact, h.commission) for m in ccfg.spread.estimators]
    out += [CostSetting(h.spread, x, h.commission) for x in ccfg.impact.coefficients if x != h.impact]
    out += [CostSetting(h.spread, h.impact, s.name) for s in ccfg.commission.schedules if s.name != h.commission]
    return out


def variants(cfg: BacktestConfig, ccfg: CostConfig) -> list[tuple[str, Variant]]:
    """The phase 3 configurations by name, from config alone."""
    p = cfg.portfolio
    out = []
    for v in ccfg.variants:
        signal = make_signal(v.signal, lookback_days=v.lookback_days, vol_scaled=v.vol_scaled, vol_window_days=p.vol_window_days, vol_min_observations=p.vol_min_observations)
        out.append((v.name, Variant(v.signal, signal.source, v.lookback_days, v.vol_scaled, v.holding_days)))
    if ccfg.sscore.include:
        out.append((SSCORE_NAME, SSCORE_VARIANT))
    return out


@dataclass(frozen=True)
class Lab:
    """What every phase 3 run shares: the tables, both configs, the fill grids, the cost inputs and the borrow panel."""

    tables: Tables
    cfg: BacktestConfig
    ccfg: CostConfig
    sector_etfs: dict[str, str]
    grids: Grids
    start: int
    is_stock: np.ndarray
    costs: CostInputs
    borrow_rate: np.ndarray        # annual, row s for the shorts held from s-1 to s
    hard: np.ndarray               # hard-to-borrow flag, same rows
    decision_price: np.ndarray     # row s: the close before s


def build_lab(tables: Tables, cfg: BacktestConfig, ccfg: CostConfig, sector_etfs: dict[str, str]) -> Lab:
    stocks = set(tables.stocks)
    is_stock = np.array([t in stocks for t in tables.tickers])
    sp, im, b = ccfg.spread, ccfg.impact, ccfg.borrow
    costs = build_cost_inputs(
        tables.prices,
        tables.returns,
        tables.dates,
        tables.tickers,
        sp.window_days,
        sp.min_observations,
        im.volatility_window_days,
        im.volatility_min_observations,
        im.volume_window_days,
        im.volume_min_observations,
        is_stock,
        sp.size_groups,
        sp.estimators,
    )
    rate, hard = borrow_rates(before(costs.volatility), is_stock, b.general_annual, b.hard_annual, b.hard_quantile)
    return Lab(tables, cfg, ccfg, sector_etfs, build_grids(tables), start_index(tables, cfg), is_stock, costs, rate, hard, before(costs.close))


def cost(lab: Lab, setting: CostSetting, book: float, kind: str) -> TradingCost:
    s = lab.ccfg.schedule(setting.commission)
    schedule = CommissionSchedule(s.name, s.per_share, s.min_per_order, s.max_fraction)
    return trading_cost(lab.costs, kind, setting.spread, lab.ccfg.spread.half_tick_floor, book, setting.impact, schedule)


def scores_of(lab: Lab, variant: Variant) -> Scores:
    return signal_of(variant, lab.cfg, lab.sector_etfs).scores(lab.tables)


def run_path(lab: Lab, book_targets: np.ndarray, fill: str, policy: Policy | None = None) -> EngineResult:
    kind, delay = FILL_TIMINGS[fill]
    return run(book_targets, getattr(lab.grids, kind), delay, lab.borrow_rate, policy)


def expected_move_of(lab: Lab, variant: Variant, scores: Scores) -> np.ndarray:
    """Calibrated move over the holding period, per stock on each decision date, padded with zeros for the hedges."""
    nt = lab.ccfg.no_trade
    series = (lab.tables.residual if variant.source == "residual" else lab.tables.raw).to_numpy()
    outcome = forward_sum(series, variant.holding_days)
    members = lab.tables.members
    slope = calibration_slope(scores.score, outcome, members, variant.holding_days, nt.calibration_window_days, nt.calibration_min_days)
    move = expected_move(scores.score, members, slope)
    return np.hstack([move, np.zeros((move.shape[0], len(lab.tables.hedges)))])


def no_trade(lab: Lab, book: float, move: np.ndarray) -> NoTradeZone:
    kind, delay = FILL_TIMINGS[lab.ccfg.run.fill]
    return NoTradeZone(move, cost(lab, headline(lab.ccfg), book, kind), lab.decision_price, delay)


# Evaluation ---------------------------------------------------------------------------


CAPITAL_COLUMNS = ("gross", "cost", "borrow", "net", "turnover", "long_pnl", "short_pnl", *(f"cost_{c}" for c in COMPONENTS))


def per_capital(d: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Daily returns per dollar of capital from returns per dollar of gross, with idle days at zero.

    Weights are fractions of capital (`statarb.backtest.costs`), so the gross
    exposure each day is the capital deployed. A trader with that capital earns
    this, not the return on whatever happened to be deployed.
    """
    out = d.loc[:, list(CAPITAL_COLUMNS)].mul(d["exposure"], axis=0).reindex(dates, fill_value=0.0)
    out["exposure"] = d["exposure"].reindex(dates, fill_value=0.0)
    return out


def book_stats(lab: Lab, result: EngineResult, d: pd.DataFrame) -> dict:
    """Net dollar imbalance and the hard-to-borrow share of borrow cost."""
    h = result.holdings
    gross = np.abs(h).sum(axis=1)
    held = gross > 0
    imbalance = np.abs(h.sum(axis=1))[held] / gross[held]
    prev = np.vstack([np.zeros((1, h.shape[1])), h[:-1]])
    shorts = -np.minimum(prev, 0.0)
    general = lab.ccfg.borrow.general_annual
    extra = (shorts * (lab.borrow_rate - general)).sum(axis=1) / TRADING_DAYS
    extra_on_capital = pd.Series(extra, index=result.dates).reindex(d.index).to_numpy()
    return {
        "net_dollar_imbalance": float(imbalance.mean()) if held.any() else float("nan"),
        "ann_borrow_hard_extra": float(extra_on_capital.mean() * TRADING_DAYS),
        "hard_short_share": float((shorts * lab.hard).sum() / shorts.sum()) if shorts.sum() > 0 else float("nan"),
    }


def evaluate(lab: Lab, result: EngineResult, setting: CostSetting, book: float, kind: str) -> tuple[pd.DataFrame, dict]:
    per_gross = daily_returns(result, cost(lab, setting, book, kind))
    d = per_capital(per_gross, result.dates[lab.start :])
    m = summary(d)
    m["gross_basis_sharpe"] = sharpe(per_gross["net"])
    m["mean_exposure"] = float(d["exposure"].mean())
    m["median_names"] = float(np.median((result.holdings[lab.start :] != 0).sum(axis=1)))
    n = len(d)
    sd = d["net"].std()
    m["t_stat"] = float(d["net"].mean() / sd * math.sqrt(n)) if sd > 0 else float("nan")
    traded = d["turnover"].sum()
    for part in COMPONENTS:
        m[f"ann_cost_{part}"] = float(d[f"cost_{part}"].mean() * TRADING_DAYS)
        m[f"{part}_bps_per_dollar"] = float(d[f"cost_{part}"].sum() / traded * 1e4) if traded > 0 else float("nan")
    m.update(book_stats(lab, result, d))
    return d, m


@dataclass(frozen=True)
class Outcome:
    name: str
    variant: Variant
    no_trade: bool
    book: float
    setting: CostSetting
    daily: pd.DataFrame
    metrics: dict
    result: EngineResult | None = field(default=None, repr=False)


def run_all(lab: Lab) -> list[Outcome]:
    """Every configuration at every book size and cost setting, plus the no-trade zone for decile configurations at the headline cost."""
    cc = lab.ccfg
    fill = cc.run.fill
    kind = FILL_TIMINGS[fill][0]
    head = headline(cc)
    outcomes = []
    for name, variant in variants(lab.cfg, cc):
        scores = scores_of(lab, variant)
        book_targets = targets(variant, scores, lab.tables, lab.cfg)
        result = run_path(lab, book_targets, fill)
        for book in cc.run.book_sizes:
            for setting in [head, *alternatives(cc)]:
                d, m = evaluate(lab, result, setting, book, kind)
                outcomes.append(Outcome(name, variant, False, book, setting, d, m, result if setting == head else None))
        if variant.signal == SSCORE:
            continue
        move = expected_move_of(lab, variant, scores)
        for book in cc.run.book_sizes:
            zoned = run_path(lab, book_targets, fill, no_trade(lab, book, move))
            d, m = evaluate(lab, zoned, head, book, kind)
            outcomes.append(Outcome(name, variant, True, book, head, d, m, zoned))
    return outcomes


# Log and judgement ---------------------------------------------------------------------


def record(o: Outcome, lab: Lab) -> dict:
    """The configuration part of an experiment log entry, which its config_id hashes."""
    c = lab.ccfg
    return {
        **asdict(o.variant),
        "name": o.name,
        "fill": c.run.fill,
        "book_size": o.book,
        "no_trade_zone": o.no_trade,
        "spread": o.setting.spread,
        "half_tick_floor": c.spread.half_tick_floor,
        "impact_coefficient": o.setting.impact,
        "commission": asdict(c.schedule(o.setting.commission)),
        "borrow": asdict(c.borrow),
        "no_trade": asdict(c.no_trade) if o.no_trade else None,
        "decile": lab.cfg.portfolio.decile if o.variant.signal != SSCORE else None,
        "start": lab.cfg.period.start.isoformat(),
        **({"sscore": asdict(lab.cfg.sscore)} if o.variant.signal == SSCORE else {}),
    }


def log_entries(outcomes: list[Outcome], lab: Lab, state: dict, now: dt.datetime) -> list[dict]:
    return [experiments.entry(record(o, lab), o.metrics, lab.cfg.run.seed, state, now) for o in outcomes]


def trial_sets(earlier: dict[str, float], outcomes: list[Outcome], lab: Lab) -> dict[float, dict[str, float]]:
    """Daily gross Sharpe of every position path by path id, at each book size.

    `earlier` holds the paths of earlier phases' logs. This run's paths are added,
    or replace an earlier entry for the same path, at the headline cost: a no-trade
    path at the book size in question, the others at any (their positions do not
    depend on it).
    """
    head = headline(lab.ccfg)
    out = {}
    for book in lab.ccfg.run.book_sizes:
        paths = dict(earlier)
        for o in outcomes:
            if o.setting == head and o.book == book:
                paths[path_id(record(o, lab))] = o.metrics["gross_sharpe"] / math.sqrt(TRADING_DAYS)
        out[book] = paths
    return out


def verdicts(outcomes: list[Outcome], trials: dict[float, dict[str, float]], head: CostSetting) -> pd.DataFrame:
    """The bar from the phase 3 brief, for every configuration at the headline cost."""
    rows = []
    for o in outcomes:
        if o.setting != head:
            continue
        sharpes = np.array(list(trials[o.book].values()))
        ds = deflated_sharpe(o.daily["net"], len(sharpes), sharpes)
        rows.append(
            {
                "configuration": o.name + (", no-trade zone" if o.no_trade else ""),
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


def phase_2_break_even(phase_2_log: list[dict], outcomes: list[Outcome], name: str, lab: Lab) -> float | None:
    """A configuration's break-even cost under phase 2's flat cost, from the phase 2 log, if it ran there."""
    o = next(o for o in outcomes if o.name == name and not o.no_trade)
    want = path_id(record(o, lab))
    found = [e["metrics"].get("break_even_bps") for e in phase_2_log if path_id(e["config"]) == want]
    return found[-1] if found else None


def earlier_phase(phase: str) -> str:
    return f"phase-{int(phase.split('-')[1]) - 1:02d}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-log", action="store_true", help="do not append to experiments.jsonl")
    args = parser.parse_args(argv)

    from statarb.backtest import cost_report

    root = repo_root()
    data_cfg = load_config("data", root)
    sector_etfs = load_config("factors", root)["sector_etfs"]
    cfg = load_backtest_config(root)
    ccfg = load_cost_config(cfg, root)
    tables = load_tables(resolve_path(data_cfg["paths"]["processed"], root), data_cfg["factors"]["market"], sector_etfs)
    lab = build_lab(tables, cfg, ccfg, sector_etfs)
    outcomes = run_all(lab)
    reports = resolve_path(data_cfg["paths"]["reports"], root)
    out_dir: Path = reports / PHASE
    log_path = out_dir / "experiments.jsonl"
    trials = trial_sets(repository_trials(reports, through=earlier_phase(PHASE)), outcomes, lab)
    verdict = verdicts(outcomes, trials, headline(ccfg))
    if not args.no_log:
        experiments.append(log_path, log_entries(outcomes, lab, experiments.run_state(root), dt.datetime.now(dt.UTC)))
    configs = variants(cfg, ccfg)
    be = phase_2_break_even(experiments.read(reports / "phase-02" / "experiments.jsonl"), outcomes, configs[0][0], lab)
    settings = [headline(ccfg), *alternatives(ccfg)]
    text = cost_report.write_report(lab, configs, settings, outcomes, verdict, be, experiments.read(log_path), out_dir)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
