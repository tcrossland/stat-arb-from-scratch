"""Partial adjustment towards an aim portfolio (decision record 0006), an engine policy like the optimiser.

Each decision day the aim w* is the phase 4 optimiser's solution with no cost
term (kappa = 0): the same risk aversion, horizon, constraints and risk model,
on the forecast's expected move. The policy trades a fixed fraction theta of the
way to it from the book as known at the decision,

    w = w0 + theta (w* - w0),

for the names the optimiser may hold; the rest go to zero at once, as the
optimiser's forced exits do. The optimiser's minimum-trade filter follows. If
the aim has no solution that day, the book is held.

With no cost term the aim does not depend on the book held, so `aims` solves
it once per path and every theta reuses it. A convex combination of two books
that meet the optimiser's linear constraints meets them too, so the traded book
stays within them up to the drift of the book held and the filter, as the
optimiser's does after its filter.

`choose_rate` is the rule that sets theta before any return is seen: the grid
value whose turnover is closest to a target, the one-period optimiser's.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from statarb.portfolio.optimiser import DayNote, Optimiser


@dataclass(frozen=True)
class Aims:
    """The aim portfolio for the fill at each grid time; NaN rows where there is none."""

    weights: np.ndarray                  # (grid times, stocks)
    notes: dict[int, DayNote]            # grid time -> the aim's solve on that day


def aims(opt: Optimiser, rows: int) -> Aims:
    """Solve the optimiser with no cost term for every decision day from `opt.start`, over `rows` grid times."""
    if opt.settings.cost_multiplier != 0 or opt.settings.turnover_budget is not None:
        raise ValueError("the aim portfolio has no cost term and no turnover budget")
    n = opt.n
    weights = np.full((rows, n), np.nan)
    notes = {}
    flat = np.zeros(n)
    for s in range(rows):
        t = s - opt.delay
        if t < opt.start:
            continue
        began = time.perf_counter()
        values = opt.day_inputs(s, flat)
        if values is None:
            notes[s] = DayNote(t, "no_risk_model", time.perf_counter() - began)
            continue
        status, w = opt.solve(values)
        if w is not None:
            weights[s] = w
        notes[s] = DayNote(t, status, time.perf_counter() - began)
    return Aims(weights, notes)


@dataclass(frozen=True)
class PartialAdjustment:
    """Engine policy: trade `rate` of the way from the book held to the aim, then the minimum-trade filter."""

    optimiser: Optimiser                 # kappa = 0: its inputs and its filter
    aim: Aims
    rate: float

    def __post_init__(self) -> None:
        if not 0 < self.rate <= 1:
            raise ValueError("the trade rate must be in (0, 1]")

    def __call__(self, s: int, held: np.ndarray, drifted: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, DayNote | None]:
        opt = self.optimiser
        keep = np.full(drifted.shape, np.nan)
        t = s - opt.delay
        if t < opt.start:
            return keep, None
        aim = self.aim.weights[s]
        solved = self.aim.notes.get(s, DayNote(t, "no_aim", 0.0))
        if not np.isfinite(aim).all():
            return keep, solved
        values = opt.day_inputs(s, held)
        if values is None:
            return keep, DayNote(t, "no_risk_model", solved.seconds)
        w0 = values["w0"]
        w = np.where(values["ok"], w0 + self.rate * (aim - w0), 0.0)
        out = opt.filter_trades(w, values)
        keep[: opt.n] = out.targets
        return keep, DayNote(**{**vars(out.note), "date_index": t, "status": solved.status, "seconds": solved.seconds})


@dataclass(frozen=True)
class RateChoice:
    rate: float
    target: float                        # the turnover matched
    turnover: float                      # the chosen rate's turnover
    tried: dict[float, float]            # every rate evaluated -> its turnover


def rate_grid(step: float) -> tuple[float, ...]:
    """step, 2 step, ..., 1."""
    k = round(1 / step)
    if not np.isclose(k * step, 1.0):
        raise ValueError("the rate grid's step must divide 1")
    return tuple(round((i + 1) * step, 10) for i in range(k))


def choose_rate(turnover_at: Callable[[float], float], target: float, grid: Sequence[float]) -> RateChoice:
    """The grid rate whose turnover is closest to `target`, the smaller rate on a tie.

    Every rate on the grid is evaluated and returned. `turnover_at` must read
    positions only, never a return.
    """
    tried = {float(r): float(turnover_at(r)) for r in sorted(grid)}
    rate = min(tried, key=lambda r: (abs(tried[r] - target), r))
    return RateChoice(rate, float(target), tried[rate], tried)
