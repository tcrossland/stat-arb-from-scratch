"""Phase 2: run the backtest sweep, log every configuration and write the report.

    uv run python -m statarb.backtest.run

Reads config/backtest.toml and the phase 0 and 1 tables. Appends one entry per
configuration and cost level to reports/phase-02/experiments.jsonl and writes
reports/phase-02/backtest.md with its charts. To try other settings, set a
config overlay (STATARB_CONFIG_OVERLAY); never edit the config files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from statarb.backtest import experiments
from statarb.backtest.config import BacktestConfig, load_backtest_config
from statarb.backtest.costs import FlatCost
from statarb.backtest.engine import TRADING_DAYS, EngineResult, daily_returns
from statarb.backtest.metrics import break_even_bps, position_hit_rate, sharpe, summary
from statarb.backtest.rules import DecileRule
from statarb.backtest.sweep import (
    SSCORE,
    Grids,
    Variant,
    all_variants,
    build_grids,
    daily,
    fill,
    headline_variant,
    record,
    signal_of,
    start_index,
    targets,
)
from statarb.config import load_config, repo_root, resolve_path
from statarb.signals.base import Scores
from statarb.signals.tables import Tables, load_tables


@dataclass(frozen=True)
class Outcome:
    variant: Variant
    fill: str
    daily: dict[float, pd.DataFrame]          # by cost level
    metrics: dict[float, dict]
    result: EngineResult | None = field(default=None, repr=False)


def evaluate(cfg: BacktestConfig, variant: Variant, timing: str, result: EngineResult, keep_result: bool) -> Outcome:
    # Break-even is the total one-way cost, so it is measured with no cost or slippage at all.
    be = break_even_bps(daily_returns(result, FlatCost(0.0)))
    hit = position_hit_rate(result)
    by_level, metrics = {}, {}
    for level in cfg.costs.levels_bps:
        d = daily(result, cfg, timing, level)
        by_level[level] = d
        metrics[level] = {**summary(d), "break_even_bps": be, "position_hit_rate": hit, "missing_returns": result.missing_returns}
    return Outcome(variant, timing, by_level, metrics, result if keep_result else None)


def run_sweep(tables: Tables, cfg: BacktestConfig, grids: Grids, sector_etfs: dict[str, str]) -> list[Outcome]:
    """Every variant at every fill timing. Engine results are kept for the headline and the s-score only."""
    head = headline_variant(cfg)
    scores: dict[tuple, Scores] = {}
    outcomes = []
    for variant in all_variants(cfg):
        key = (variant.signal, variant.lookback_days, variant.vol_scaled)
        if key not in scores:
            scores[key] = signal_of(variant, cfg, sector_etfs).scores(tables)
        book = targets(variant, scores[key], tables, cfg)
        for timing in cfg.fills.timings:
            keep = variant == head or variant.signal == SSCORE
            outcomes.append(evaluate(cfg, variant, timing, fill(book, grids, timing, cfg), keep))
    return outcomes


def log_entries(outcomes: list[Outcome], cfg: BacktestConfig, state: dict, now: dt.datetime) -> list[dict]:
    return [
        experiments.entry(record(o.variant, o.fill, level, cfg), m, cfg.run.seed, state, now)
        for o in outcomes
        for level, m in o.metrics.items()
    ]


def shuffle_within_days(signal: np.ndarray, members: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Placebo: permute each day's signal values among the members that have one."""
    out = np.full_like(signal, np.nan)
    for t in range(signal.shape[0]):
        idx = np.flatnonzero(members[t] & np.isfinite(signal[t]))
        out[t, idx] = signal[t, rng.permutation(idx)]
    return out


def placebo(tables: Tables, cfg: BacktestConfig, grids: Grids, sector_etfs: dict[str, str]) -> pd.DataFrame:
    """The headline configuration with its signal shuffled among members each day, gross of costs."""
    head = headline_variant(cfg)
    signal = signal_of(head, cfg, sector_etfs).scores(tables).score
    rule = DecileRule(cfg.portfolio.decile, head.holding_days)
    start, hedges = start_index(tables, cfg), len(tables.hedges)
    rows = []
    for i in range(cfg.run.placebo_runs):
        seed = cfg.run.seed + i
        shuffled = Scores(shuffle_within_days(signal, tables.members, np.random.default_rng(seed)))
        result = fill(rule.targets(shuffled, tables.members, start, hedges), grids, cfg.fills.headline, cfg)
        d = daily(result, cfg, cfg.fills.headline, 0.0)
        rows.append({"seed": seed, "ann_gross_return": d["gross"].mean() * TRADING_DAYS, "gross_sharpe": sharpe(d["gross"])})
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-log", action="store_true", help="do not append to experiments.jsonl")
    args = parser.parse_args(argv)

    from statarb.backtest import report

    root = repo_root()
    data_cfg = load_config("data", root)
    sector_etfs = load_config("factors", root)["sector_etfs"]
    cfg = load_backtest_config(root)
    tables = load_tables(resolve_path(data_cfg["paths"]["processed"], root), data_cfg["factors"]["market"], sector_etfs)
    grids = build_grids(tables)
    outcomes = run_sweep(tables, cfg, grids, sector_etfs)
    reports = resolve_path(data_cfg["paths"]["reports"], root)
    out_dir = reports / "phase-02"
    if not args.no_log:
        state = experiments.run_state(root)
        experiments.append(out_dir / "experiments.jsonl", log_entries(outcomes, cfg, state, dt.datetime.now(dt.UTC)))
    text = report.write_report(tables, cfg, outcomes, placebo(tables, cfg, grids, sector_etfs), reports, out_dir)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
