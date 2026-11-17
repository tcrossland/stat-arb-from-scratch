"""The phase 4 position paths: each a signal on one model's residuals, through the decile sort or an optimiser setting.

Shared by the runner and the report, so the report never imports the runner
(run as `python -m`, the runner is `__main__`, and a second copy of its classes
would never compare equal).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from statarb.portfolio.config import PortfolioConfig

DECILE = "decile sort"
HEADLINE = "optimiser"
MODEL_NAMES = {"etf": "Model A", "pca": "Model B"}


@dataclass(frozen=True)
class PathSpec:
    """One position path: a signal on one model's residuals, through the decile sort or an optimiser setting."""

    name: str
    group: str
    variant: str                     # a variant name in config/costs.toml
    residuals: str                   # the residuals the signal reads: "etf" (Model A) or "pca" (Model B)
    risk: str | None = None          # the optimiser's risk model; None for the decile sort
    risk_aversion: float | None = None
    cost_multiplier: float | None = None
    turnover_budget: float | None = None
    min_trade_dollars: float | None = None
    re_solve: bool | None = None

    @property
    def is_decile(self) -> bool:
        return self.risk is None


def decile_specs(pc: PortfolioConfig) -> list[PathSpec]:
    """The decile sorts: the baseline on each model's residuals, and the comparison on Model A's."""
    v, c = pc.run.variant, pc.run.comparison
    return [
        PathSpec(DECILE, "decile", v, "etf"),
        PathSpec(f"{DECILE}, Model B", "decile", v, "pca"),
        PathSpec(f"{DECILE}, {c}", "decile", c, "etf"),
    ]


def optimiser_specs(pc: PortfolioConfig) -> list[PathSpec]:
    """The headline optimiser and every setting that differs from it in one respect (phase 4 brief, "Runs")."""
    h, sw, m = pc.headline, pc.sweep, pc.risk.model
    head = PathSpec(HEADLINE, "headline", pc.run.variant, m, m, h.risk_aversion, h.cost_multiplier, None, h.min_trade_dollars, h.re_solve)
    out = [head]
    out += [replace(head, name=f"λ = {x:g}", group="risk aversion", risk_aversion=x) for x in sw.risk_aversions if x != h.risk_aversion]
    out += [replace(head, name=f"κ = {x:g}", group="cost multiplier", cost_multiplier=x) for x in sw.cost_multipliers if x != h.cost_multiplier]
    out += [replace(head, name=f"τ = {x:.0%}", group="turnover budget", cost_multiplier=1.0, turnover_budget=x) for x in sw.turnover_budgets]
    out += [replace(head, name=f"minimum trade ${x:,.0f}", group="minimum trade", min_trade_dollars=x) for x in sw.min_trade_dollars if x != h.min_trade_dollars]
    out += [replace(head, name=f"re-solve, minimum trade ${x:,.0f}", group="re-solve", min_trade_dollars=x, re_solve=True) for x in sw.re_solve_min_trade_dollars]
    other = {"etf": "pca", "pca": "etf"}[m]
    out += [
        replace(head, name=f"{MODEL_NAMES[m]} signal, {MODEL_NAMES[other]} risk", group="models", risk=other),
        replace(head, name=f"{MODEL_NAMES[other]} signal, {MODEL_NAMES[m]} risk", group="models", residuals=other),
        replace(head, name=MODEL_NAMES[other], group="models", residuals=other, risk=other),
        replace(head, name=f"{HEADLINE}, {pc.run.comparison}", group="comparison", variant=pc.run.comparison),
    ]
    return out


def bracketed(spec: PathSpec) -> bool:
    """Paths re-costed at each half-spread of the phase 3 bracket."""
    return spec.group in ("decile", "headline", "comparison") or spec.name == MODEL_NAMES["pca"]
