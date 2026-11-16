"""The phase 2 configurations: each a signal and a portfolio rule, run at every fill timing and cost level.

A variant names one position path's signal and holding rule; the fill timing
and the cost level are applied on top. Signals come from the registry by name
(`statarb.signals.registry`) and rules from `statarb.backtest.rules`, so a new
signal or rule enters through those seams with no change here beyond its
variant.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from statarb.backtest.config import BacktestConfig
from statarb.backtest.costs import FlatCost
from statarb.backtest.engine import (
    FILL_TIMINGS,
    EngineResult,
    Grid,
    close_grid,
    daily_returns,
    open_grid,
    run,
)
from statarb.backtest.rules import DecileRule, PortfolioRule, ThresholdRule
from statarb.signals.base import Scores, Signal
from statarb.signals.registry import make_signal
from statarb.signals.tables import Tables

SSCORE = "sscore"


@dataclass(frozen=True)
class Variant:
    """One position path: a signal and holding rule. Fill timing and cost are applied on top."""

    signal: str
    source: str
    lookback_days: int | None
    vol_scaled: bool | None
    holding_days: int | None

    def label(self) -> str:
        if self.signal == SSCORE:
            return "s-score"
        scaled = ", vol-scaled" if self.vol_scaled else ""
        return f"{self.signal} n={self.lookback_days}{scaled}, k={self.holding_days}"


SSCORE_VARIANT = Variant(SSCORE, SSCORE, None, None, None)


def signal_of(variant: Variant, cfg: BacktestConfig, sector_etfs: dict[str, str]) -> Signal:
    """The registered signal a variant names, with its parameters from config."""
    if variant.signal == SSCORE:
        s = cfg.sscore
        return make_signal(
            SSCORE,
            window_days=s.window_days,
            max_reversion_days=s.max_reversion_days,
            centre_means=s.centre_means,
            sector_etfs=sector_etfs,
        )
    return make_signal(
        variant.signal,
        lookback_days=variant.lookback_days,
        vol_scaled=variant.vol_scaled,
        vol_window_days=cfg.portfolio.vol_window_days,
        vol_min_observations=cfg.portfolio.vol_min_observations,
    )


def rule_of(variant: Variant, cfg: BacktestConfig) -> PortfolioRule:
    if variant.signal == SSCORE:
        s = cfg.sscore
        return ThresholdRule(s.open, s.close_long, s.close_short, s.position_weight)
    return DecileRule(cfg.portfolio.decile, variant.holding_days)


def decile_variants(cfg: BacktestConfig) -> list[Variant]:
    out = []
    for spec in cfg.signals:
        for n, scaled, k in itertools.product(spec.lookbacks, spec.vol_scaled, cfg.sweep.holding_days):
            p = cfg.portfolio
            signal = make_signal(spec.name, lookback_days=n, vol_scaled=scaled, vol_window_days=p.vol_window_days, vol_min_observations=p.vol_min_observations)
            out.append(Variant(spec.name, signal.source, n, scaled, k))
    return out


def all_variants(cfg: BacktestConfig) -> list[Variant]:
    return [*decile_variants(cfg), SSCORE_VARIANT]


def headline_variant(cfg: BacktestConfig) -> Variant:
    h = cfg.headline
    return next(
        v
        for v in decile_variants(cfg)
        if (v.signal, v.lookback_days, v.vol_scaled, v.holding_days) == (h.signal, h.lookback_days, h.vol_scaled, h.holding_days)
    )


def start_index(tables: Tables, cfg: BacktestConfig) -> int:
    """Index of the first signal date, `[period] start`, in the trading calendar."""
    return int(tables.dates.searchsorted(pd.Timestamp(cfg.period.start)))


def targets(variant: Variant, scores: Scores, tables: Tables, cfg: BacktestConfig) -> np.ndarray:
    """The variant's target weights, decided at each close, flat before the first signal date."""
    return rule_of(variant, cfg).targets(scores, tables.members, start_index(tables, cfg), len(tables.hedges))


@dataclass(frozen=True)
class Grids:
    close: Grid
    open: Grid


def build_grids(tables: Tables) -> Grids:
    args = (tables.returns, tables.prices, tables.dates, tables.tickers)
    return Grids(close_grid(*args), open_grid(*args))


def fill(targets: np.ndarray, grids: Grids, timing: str, cfg: BacktestConfig) -> EngineResult:
    kind, delay = FILL_TIMINGS[timing]
    return run(targets, getattr(grids, kind), delay, cfg.costs.borrow_annual)


def cost_bps(cfg: BacktestConfig, timing: str, level: float) -> float:
    """Total one-way cost: the level plus the stated slippage for a same-close fill."""
    return level + (cfg.fills.close_t_slippage_bps if timing == "close_t" else 0.0)


def daily(result: EngineResult, cfg: BacktestConfig, timing: str, level: float) -> pd.DataFrame:
    return daily_returns(result, FlatCost(cost_bps(cfg, timing, level)))


def record(variant: Variant, timing: str, level: float, cfg: BacktestConfig) -> dict:
    """The configuration part of an experiment log entry, which its config_id hashes."""
    return {
        **asdict(variant),
        "fill": timing,
        "cost_bps": level,
        "slippage_bps": cost_bps(cfg, timing, level) - level,
        "borrow_annual": cfg.costs.borrow_annual,
        "decile": cfg.portfolio.decile if variant.signal != SSCORE else None,
        "start": cfg.period.start.isoformat(),
        **({"sscore": asdict(cfg.sscore)} if variant.signal == SSCORE else {}),
    }
