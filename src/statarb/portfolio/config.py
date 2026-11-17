"""Typed phase 4 configuration from config/portfolio.toml.

As for the phase 2 and 3 configs, every table must have exactly the documented
keys: a misspelt or missing parameter raises instead of falling back.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from statarb.backtest.config import CostConfig, _build
from statarb.config import load_config

RISK_MODELS = ("etf", "pca")


@dataclass(frozen=True)
class PortfolioRun:
    fill: str
    book_sizes: tuple[float, ...]
    variant: str
    comparison: str


@dataclass(frozen=True)
class OptimiserLimits:
    horizon_days: int
    position_cap: float
    adv_cap: float
    gross_cap: float
    dollar_tolerance: float
    factor_tolerance: float
    solver: str
    solver_options: dict
    re_solve_rounds: int


@dataclass(frozen=True)
class RiskSettings:
    model: str
    factor_window_days: int
    factor_min_observations: int
    specific_window_days: int
    specific_min_observations: int


@dataclass(frozen=True)
class RiskAversionRule:
    candidates: tuple[float, ...]
    days: int
    min_capital: float


@dataclass(frozen=True)
class Headline:
    risk_aversion: float
    cost_multiplier: float
    min_trade_dollars: float
    re_solve: bool


@dataclass(frozen=True)
class Sweep:
    risk_aversions: tuple[float, ...]
    cost_multipliers: tuple[float, ...]
    turnover_budgets: tuple[float, ...]
    min_trade_dollars: tuple[float, ...]
    re_solve_min_trade_dollars: tuple[float, ...]


@dataclass(frozen=True)
class PortfolioConfig:
    run: PortfolioRun
    optimiser: OptimiserLimits
    risk: RiskSettings
    risk_aversion_rule: RiskAversionRule
    headline: Headline
    sweep: Sweep

    @classmethod
    def from_dict(cls, data: dict[str, Any], costs: CostConfig) -> PortfolioConfig:
        cfg = _build(cls, data, "portfolio")
        cfg.validate(costs)
        return cfg

    def validate(self, costs: CostConfig) -> None:
        r = self.run
        if r.fill not in ("open_t1", "close_t1"):
            raise ValueError("run.fill must be open_t1 or close_t1: the optimiser decides at the close and fills later")
        names = {v.name for v in costs.variants}
        for v in (r.variant, r.comparison):
            if v not in names:
                raise ValueError(f"variant {v!r} is not a [[variants]] name in config/costs.toml")
        if r.variant == r.comparison:
            raise ValueError("run.comparison must differ from run.variant")
        missing = set(r.book_sizes) - set(costs.run.book_sizes)
        if missing:
            raise ValueError(f"book sizes {sorted(missing)} are not phase 3 book sizes")
        o = self.optimiser
        if not (0 < o.position_cap <= o.gross_cap) or o.adv_cap <= 0:
            raise ValueError("position_cap must be in (0, gross_cap] and adv_cap positive")
        if o.dollar_tolerance < 0 or o.factor_tolerance < 0:
            raise ValueError("tolerances cannot be negative")
        if o.solver != "CLARABEL":
            raise ValueError("solver must be CLARABEL, the solver pinned in pyproject.toml")
        if o.re_solve_rounds < 1:
            raise ValueError("re_solve_rounds must be at least 1")
        rk = self.risk
        if rk.model not in RISK_MODELS:
            raise ValueError(f"risk.model must be one of {RISK_MODELS}")
        if not (0 < rk.factor_min_observations <= rk.factor_window_days and 1 < rk.specific_min_observations <= rk.specific_window_days):
            raise ValueError("risk min_observations must be within their windows")
        h, s = self.headline, self.sweep
        if h.risk_aversion not in s.risk_aversions or h.risk_aversion not in self.risk_aversion_rule.candidates:
            raise ValueError("the headline risk_aversion must be a rule candidate and in the sweep")
        if h.cost_multiplier not in s.cost_multipliers or h.min_trade_dollars not in s.min_trade_dollars:
            raise ValueError("the headline cost_multiplier and min_trade_dollars must be in the sweep")
        if any(x <= 0 for x in (*s.risk_aversions, *s.cost_multipliers, *s.turnover_budgets, *self.risk_aversion_rule.candidates)):
            raise ValueError("risk aversions, cost multipliers and turnover budgets must be positive")
        if any(x < 0 for x in (*s.min_trade_dollars, *s.re_solve_min_trade_dollars)) or 0.0 in s.re_solve_min_trade_dollars:
            raise ValueError("minimum trade sizes cannot be negative, and a re-solve needs a minimum above zero")


def load_portfolio_config(costs: CostConfig, root: Path | None = None) -> PortfolioConfig:
    return PortfolioConfig.from_dict(load_config("portfolio", root), costs)
