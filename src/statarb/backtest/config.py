"""Typed backtest configuration from config/backtest.toml.

Every table must have exactly the documented keys: a misspelt or missing
parameter raises instead of falling back to a default.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from statarb.config import load_config
from statarb.signals.registry import DECILE_SIGNALS

FILLS = ("close_t", "open_t1", "close_t1")


def _build(cls: type, data: dict[str, Any], where: str) -> Any:
    hints = typing.get_type_hints(cls)
    expected = {f.name for f in dataclasses.fields(cls)}
    if not isinstance(data, dict):
        raise TypeError(f"[{where}] must be a table")
    if set(data) != expected:
        raise ValueError(f"[{where}] keys: missing {sorted(expected - set(data))}, unknown {sorted(set(data) - expected)}")
    values = {}
    for name in expected:
        hint, value = hints[name], data[name]
        if dataclasses.is_dataclass(hint):
            value = _build(hint, value, f"{where}.{name}")
        elif typing.get_origin(hint) is tuple and dataclasses.is_dataclass(typing.get_args(hint)[0]):
            inner = typing.get_args(hint)[0]
            value = tuple(_build(inner, v, f"{where}.{name}[{i}]") for i, v in enumerate(value))
        elif typing.get_origin(hint) is tuple:
            value = tuple(value)
        values[name] = value
    return cls(**values)


@dataclass(frozen=True)
class Period:
    start: dt.date


@dataclass(frozen=True)
class Run:
    seed: int
    placebo_runs: int


@dataclass(frozen=True)
class Portfolio:
    decile: float
    vol_window_days: int
    vol_min_observations: int


@dataclass(frozen=True)
class Costs:
    levels_bps: tuple[float, ...]
    headline_bps: float
    retail_bps: float
    borrow_annual: float


@dataclass(frozen=True)
class Fills:
    timings: tuple[str, ...]
    headline: str
    close_t_slippage_bps: float


@dataclass(frozen=True)
class Sweep:
    holding_days: tuple[int, ...]


@dataclass(frozen=True)
class Headline:
    signal: str
    lookback_days: int
    vol_scaled: bool
    holding_days: int


@dataclass(frozen=True)
class SignalSpec:
    name: str                    # a decile signal in statarb.signals.registry
    lookbacks: tuple[int, ...]
    vol_scaled: tuple[bool, ...]


@dataclass(frozen=True)
class SScore:
    window_days: int
    max_reversion_days: float
    open: float
    close_long: float
    close_short: float
    centre_means: bool
    position_weight: float


@dataclass(frozen=True)
class BacktestConfig:
    period: Period
    run: Run
    portfolio: Portfolio
    costs: Costs
    fills: Fills
    sweep: Sweep
    headline: Headline
    signals: tuple[SignalSpec, ...]
    sscore: SScore

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BacktestConfig:
        cfg = _build(cls, data, "backtest")
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not 0 < self.portfolio.decile <= 0.5:
            raise ValueError("portfolio.decile must be in (0, 0.5]")
        if not set(self.fills.timings) <= set(FILLS) or self.fills.headline not in self.fills.timings:
            raise ValueError(f"fills must be among {FILLS}, with the headline one of them")
        if self.costs.headline_bps not in self.costs.levels_bps:
            raise ValueError("costs.headline_bps must be one of costs.levels_bps")
        if any(k < 1 for k in self.sweep.holding_days) or self.headline.holding_days not in self.sweep.holding_days:
            raise ValueError("holding days must be positive, with the headline among them")
        names = [s.name for s in self.signals]
        if len(set(names)) != len(names) or self.headline.signal not in names:
            raise ValueError("signal names must be unique, with the headline among them")
        for s in self.signals:
            if s.name not in DECILE_SIGNALS:
                raise ValueError(f"signal {s.name!r} is not a decile signal; registered: {DECILE_SIGNALS}")
            if any(n < 1 for n in s.lookbacks):
                raise ValueError("lookbacks must be positive")
        if not 0 < self.sscore.close_long < self.sscore.open or not 0 < self.sscore.close_short < self.sscore.open:
            raise ValueError("s-score closing thresholds must lie between 0 and the opening threshold")


def load_backtest_config(root: Path | None = None) -> BacktestConfig:
    return BacktestConfig.from_dict(load_config("backtest", root))


# Phase 3: config/costs.toml ----------------------------------------------------


@dataclass(frozen=True)
class CostRun:
    fill: str
    book_sizes: tuple[float, ...]
    headline_book: float


@dataclass(frozen=True)
class CostVariant:
    name: str
    signal: str
    lookback_days: int
    vol_scaled: bool
    holding_days: int


@dataclass(frozen=True)
class CostSScore:
    include: bool


@dataclass(frozen=True)
class SpreadSettings:
    headline_half_spread_bps: float
    bracket_half_spread_bps: tuple[float, ...]
    half_tick_floor: bool
    estimators: tuple[str, ...]
    window_days: int
    min_observations: int
    size_groups: int


@dataclass(frozen=True)
class ImpactSettings:
    coefficients: tuple[float, ...]
    headline_coefficient: float
    volatility_window_days: int
    volatility_min_observations: int
    volume_window_days: int
    volume_min_observations: int


@dataclass(frozen=True)
class Schedule:
    name: str
    per_share: float
    min_per_order: float
    max_fraction: float


@dataclass(frozen=True)
class CommissionSettings:
    headline: str
    read_on: dt.date
    source: str
    schedules: tuple[Schedule, ...]


@dataclass(frozen=True)
class BorrowSettings:
    general_annual: float
    hard_annual: float
    hard_quantile: float


@dataclass(frozen=True)
class NoTradeSettings:
    calibration_window_days: int
    calibration_min_days: int


@dataclass(frozen=True)
class CostConfig:
    run: CostRun
    variants: tuple[CostVariant, ...]
    sscore: CostSScore
    spread: SpreadSettings
    impact: ImpactSettings
    commission: CommissionSettings
    borrow: BorrowSettings
    no_trade: NoTradeSettings

    @classmethod
    def from_dict(cls, data: dict[str, Any], backtest: BacktestConfig) -> CostConfig:
        cfg = _build(cls, data, "costs")
        cfg.validate(backtest)
        return cfg

    def validate(self, backtest: BacktestConfig) -> None:
        from statarb.backtest.spreads import ESTIMATORS

        if self.run.fill not in FILLS:
            raise ValueError(f"run.fill must be one of {FILLS}")
        if self.run.headline_book not in self.run.book_sizes or any(b <= 0 for b in self.run.book_sizes):
            raise ValueError("book sizes must be positive, with the headline among them")
        signals = {s.name: s for s in backtest.signals}
        names = [v.name for v in self.variants]
        if len(set(names)) != len(names) or "s-score" in names:
            raise ValueError("variant names must be unique and not 's-score', which names the s-score rule")
        for v in self.variants:
            spec = signals.get(v.signal)
            if spec is None or v.lookback_days not in spec.lookbacks or v.vol_scaled not in spec.vol_scaled:
                raise ValueError(f"variant {v.name!r} must be a phase 2 signal configuration")
            if v.holding_days < 1:
                raise ValueError("holding days must be positive")
        if not set(self.spread.estimators) <= set(ESTIMATORS):
            raise ValueError(f"spread estimators must be among {ESTIMATORS}")
        if self.spread.headline_half_spread_bps < 0 or any(x < 0 for x in self.spread.bracket_half_spread_bps):
            raise ValueError("half-spreads must not be negative")
        if self.impact.headline_coefficient not in self.impact.coefficients:
            raise ValueError("impact.headline_coefficient must be one of impact.coefficients")
        schedules = [s.name for s in self.commission.schedules]
        if len(set(schedules)) != len(schedules) or self.commission.headline not in schedules:
            raise ValueError("commission schedule names must be unique, with the headline among them")
        if not 0 < self.borrow.hard_quantile < 1:
            raise ValueError("borrow.hard_quantile must be in (0, 1)")

    def schedule(self, name: str) -> Schedule:
        return next(s for s in self.commission.schedules if s.name == name)


def load_cost_config(backtest: BacktestConfig, root: Path | None = None) -> CostConfig:
    return CostConfig.from_dict(load_config("costs", root), backtest)
