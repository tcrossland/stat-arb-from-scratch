"""Phase 4 portfolio construction: the optimiser and the decile sort behind one interface.

Both are engine policies (`statarb.backtest.engine.Policy`): at each grid time
s the engine passes the holdings filled at s-1 (`held`), the same drifted to s,
and the targets due at s, and the policy returns the targets for the fill at s
(NaN meaning "do not trade this name") with a note for the day. Weights are
fractions of capital. `tests/contract/test_portfolio.py` runs both through the
same checks.

The optimiser decides at the close of t = s - delay. It sees the book as it
stood then: the previous fill's holdings drifted to the close of t
(`decision_drift`), not to the fill price at s, which is not yet known. Each
day it solves

    maximise  mu'w - lambda * h * w' Sigma w - kappa * cost(w - w0)

    cost(d) = sum_i (half_spread_i + commission_rate_i) |d_i| + a_i |d_i|^1.5
    a_i     = impact_coefficient * sigma_i * sqrt(book / ADV_i)

subject to dollar neutrality, each factor's exposure within a tolerance,
per-name caps (a fraction of capital and of average dollar volume), gross at
most the capital, and optionally a turnover budget sum |w - w0| <= tau. Names
that may not be held (not members on t, or missing an input) are left out of
the problem and go to zero: these forced exits sit outside the budget. The
impact term is the square-root model times the traded amount, which is convex;
it is written as two rotated second-order cones, which Clarabel solves
reliably where a power cone often stops at reduced accuracy. Cost inputs are
the phase 3 panels, known before the fill.

After solving, targets smaller than the minimum trade size are set to zero, so
small positions close rather than linger, and other trades smaller than it are
dropped (the name keeps its holding). With `re_solve`, every name the filter
changed is then held where the filter left it (its holding, or zero) and the
problem is solved again over the rest, so the other names restore neutrality,
until the filter changes nothing more or `re_solve_rounds` is reached. If a solve does not return an optimal
solution, every name keeps its holding (or, in a re-solve, the last filtered
book stands) and the day is noted. Constraints are never relaxed.
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass

import cvxpy as cp
import numpy as np

from statarb.backtest.costs import TradingCost
from statarb.portfolio.risk import RiskModel

PROBLEM_INPUTS = ("mu", "G", "spec", "X", "w0", "lin", "imp", "cap")
IDLE = frozenset({"too_few_names", "no_risk_model"})    # days with nothing to optimise, not solver failures


@dataclass(frozen=True)
class Settings:
    risk_aversion: float
    cost_multiplier: float
    turnover_budget: float | None
    min_trade_dollars: float
    re_solve: bool
    re_solve_rounds: int
    horizon_days: int
    position_cap: float
    adv_cap: float
    gross_cap: float
    dollar_tolerance: float
    factor_tolerance: float
    solver: str
    solver_options: dict


@dataclass(frozen=True)
class DayNote:
    """What the optimiser did on one decision day."""

    date_index: int
    status: str
    seconds: float
    gross: float = float("nan")
    names: int = 0
    trades: int = 0
    dropped: int = 0
    ex_ante_vol: float = float("nan")    # daily, of the book after the filter
    expected: float = float("nan")       # mu'w over the horizon
    dollar_breach: float = 0.0           # beyond the tolerance, as a fraction of capital
    factor_breach: float = 0.0
    rounds: int = 0                      # re-solves
    re_solve_status: str = ""            # the status of a re-solve that failed, if one did


def rotated_cone(x, y, z) -> cp.Constraint:
    """x_i^2 <= y_i z_i with y_i, z_i >= 0, elementwise, as second-order cones."""
    return cp.SOC(y + z, cp.vstack([2 * x, y - z]), axis=0)


def problem(v: dict[str, np.ndarray], st: Settings, fixed: np.ndarray | None = None) -> tuple[cp.Problem, cp.Variable]:
    """The day's problem over the eligible names, and its weight variable.

    `v` holds the PROBLEM_INPUTS rows for the eligible names; `fixed`, if
    given, holds a weight for each name the re-solve keeps where it is and NaN
    for the others.
    """
    m = len(v["mu"])
    x = cp.Variable(m)
    d = x - v["w0"]
    # cost: a >= |d| and t >= a^1.5, as a^2 <= t r and r^2 <= a.
    a, t, r = cp.Variable(m), cp.Variable(m), cp.Variable(m)
    risk = cp.sum_squares(v["G"].T @ x) + cp.sum_squares(cp.multiply(v["spec"], x))
    cost = v["lin"] @ a + v["imp"] @ t
    objective = cp.Maximize(v["mu"] @ x - st.risk_aversion * st.horizon_days * risk - cost)
    cons = [
        cp.abs(x) <= v["cap"],
        cp.norm1(x) <= st.gross_cap,
        cp.sum(x) == 0 if st.dollar_tolerance == 0 else cp.abs(cp.sum(x)) <= st.dollar_tolerance,
        cp.abs(v["X"].T @ x) <= st.factor_tolerance,
        a >= d,
        a >= -d,
        rotated_cone(a, t, r),
        rotated_cone(r, a, np.ones(m)),
    ]
    if st.turnover_budget is not None:
        cons.append(cp.sum(a) <= st.turnover_budget)
    if fixed is not None and np.isfinite(fixed).any():
        idx = np.flatnonzero(np.isfinite(fixed))
        cons.append(x[idx] == fixed[idx])
    return cp.Problem(objective, cons), x


@dataclass(frozen=True)
class Filtered:
    """A solution after the minimum trade size."""

    targets: np.ndarray      # the filtered target where a name trades, NaN where it keeps its holding
    book: np.ndarray         # the book after the fill, at decision prices
    changed: np.ndarray      # names whose book the filter moved by at least $1 from the solution
    note: DayNote


@dataclass(frozen=True)
class Optimiser:
    """Engine policy that solves the phase 4 problem each day for the stock columns; other columns stay untraded."""

    settings: Settings
    expected_move: np.ndarray        # (dates, stocks), decision-date rows, over the horizon
    members: np.ndarray              # (dates, stocks) universe membership on decision dates
    risk: RiskModel
    cost: TradingCost                # grid-aligned, all engine columns
    decision_drift: np.ndarray       # grid-aligned (dates, columns): the close before s over the price of the fill at s-1
    decision_price: np.ndarray       # grid-aligned: the close before s
    delay: int
    start: int                       # first decision date that may trade

    @property
    def n(self) -> int:
        return self.expected_move.shape[1]

    def day_inputs(self, s: int, held: np.ndarray) -> dict[str, np.ndarray] | None:
        """Problem data for the decision of t = s - delay, over all stocks, or None if the risk model has nothing that day.

        `ok` marks the names the optimiser may hold: members with an expected
        move, loadings, specific risk and cost inputs. The rest go to zero.
        """
        t = s - self.delay
        n, st, c = self.n, self.settings, self.cost
        r = self.risk.day(t)
        if r is None:
            return None
        X = r.loadings
        mu = self.expected_move[t]
        price = self.decision_price[s, :n]
        adv = c.dollar_volume[s, :n]
        ok = (
            self.members[t]
            & np.isfinite(mu)
            & np.isfinite(X).all(axis=1)
            & np.isfinite(r.specific_var)
            & np.isfinite(c.half_spread[s, :n])
            & np.isfinite(c.volatility[s, :n])
            & (adv > 0)
            & (price > 0)
        )
        X = np.where(ok[:, None], X, 0.0)
        # Sigma = X F X' + D = G G' + D with G = X F^(1/2); F may be singular
        # (a sector ETF with no history yet has zero variance).
        ev, vec = np.linalg.eigh(r.factor_cov)
        root = vec * np.sqrt(np.maximum(ev, 0.0))
        with np.errstate(divide="ignore", invalid="ignore"):
            commission_rate = c.commission.per_share / price
            impact = c.impact_coefficient * c.volatility[s, :n] * np.sqrt(c.book_size / adv)
            adv_cap = st.adv_cap * adv / c.book_size
        drift = self.decision_drift[s, :n]
        kappa = st.cost_multiplier
        zero = np.zeros(n)
        return {
            "ok": ok,
            "mu": np.where(ok, mu, 0.0),
            "G": X @ root,
            "spec": np.where(ok, np.sqrt(np.maximum(r.specific_var, 0.0)), 0.0),
            "X": X,
            "w0": held[:n] * np.where(np.isfinite(drift), drift, 1.0),
            "lin": kappa * np.where(ok, c.half_spread[s, :n] + commission_rate, zero),
            "imp": kappa * np.where(ok, impact, zero),
            "cap": np.where(ok, np.minimum(st.position_cap, adv_cap), zero),
        }

    def solve(self, values: dict[str, np.ndarray], fixed: np.ndarray | None = None) -> tuple[str, np.ndarray | None]:
        """Solve over the eligible names, the rest at zero, with `fixed` names held (NaN: free).

        Statuses are cvxpy's; anything but optimal returns None. An inaccurate
        solution is a failure, so cvxpy's warning about one is not shown.

        The problem is built afresh each day over the eligible names only:
        capping ineligible names at |w_i| <= 0 would leave an interior-point
        solver no interior.
        """
        st = self.settings
        ok = values["ok"]
        w = np.zeros(self.n)
        if int(ok.sum()) < 2:
            return "too_few_names", w
        prob, x = problem({k: values[k][ok] for k in PROBLEM_INPUTS}, st, None if fixed is None else fixed[ok])
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                prob.solve(solver=st.solver, **st.solver_options)
        except cp.error.SolverError:
            return "solver_error", None
        if prob.status != cp.OPTIMAL:
            return str(prob.status), None
        w[ok] = x.value
        return prob.status, w

    def filter_trades(self, w: np.ndarray, values: dict[str, np.ndarray]) -> Filtered:
        """The solution after the minimum trade size, and its neutrality and risk at decision prices."""
        st, book = self.settings, self.cost.book_size
        floor = max(st.min_trade_dollars, 1.0) / book
        raw = w
        w = np.where(np.abs(w) < floor, 0.0, w)
        w0 = values["w0"]
        delta = np.abs(w - w0)
        closes = (w == 0.0) & (w0 != 0.0)
        trade = (delta >= floor) | closes
        final = np.where(trade, w, w0)
        dropped = (delta * book >= 1.0) & ~trade
        risk = np.sum((values["G"].T @ final) ** 2) + np.sum((values["spec"] * final) ** 2)
        note = DayNote(
            date_index=-1,
            status="",
            seconds=0.0,
            gross=float(np.abs(final).sum()),
            names=int(np.count_nonzero(final)),
            trades=int(trade.sum()),
            dropped=int(dropped.sum()),
            ex_ante_vol=float(np.sqrt(risk)),
            expected=float(values["mu"] @ final),
            dollar_breach=float(max(0.0, abs(final.sum()) - st.dollar_tolerance)),
            factor_breach=float(max(0.0, np.abs(values["X"].T @ final).max() - st.factor_tolerance)),
        )
        changed = np.abs(final - raw) * book >= 1.0
        return Filtered(np.where(trade, w, np.nan), final, changed, note)

    def decide(self, s: int, held: np.ndarray) -> tuple[np.ndarray | None, DayNote]:
        """Stock targets for the fill at s (None: hold the book), and the day's note."""
        t = s - self.delay
        began = time.perf_counter()
        values = self.day_inputs(s, held)
        if values is None:
            return None, DayNote(t, "no_risk_model", time.perf_counter() - began)
        status, w = self.solve(values)
        if w is None:
            return None, DayNote(t, status, time.perf_counter() - began)
        out = self.filter_trades(w, values)
        rounds, re_status = 0, ""
        if self.settings.re_solve:
            fixed = np.full(self.n, np.nan)
            while out.changed.any() and rounds < self.settings.re_solve_rounds:
                rounds += 1
                fixed = np.where(out.changed, out.book, fixed)
                re_status, w = self.solve(values, fixed)
                if w is None:
                    break
                re_status = ""
                out = self.filter_trades(w, values)
        note = DayNote(**{**vars(out.note), "date_index": t, "status": status, "seconds": time.perf_counter() - began, "rounds": rounds, "re_solve_status": re_status})
        return out.targets, note

    def __call__(self, s: int, held: np.ndarray, drifted: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, DayNote | None]:
        keep = np.full(drifted.shape, np.nan)
        if s - self.delay < self.start:
            return keep, None
        stocks, note = self.decide(s, held)
        if stocks is not None:
            keep[: self.n] = stocks
        return keep, note


@dataclass(frozen=True)
class DecileSort:
    """The decile book as a policy: trade to the targets decided at the close of t = s - delay, as phases 2 and 3 do."""

    targets: np.ndarray              # (dates, columns), decision-date rows
    delay: int

    def __call__(self, s: int, held: np.ndarray, drifted: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, None]:
        t = s - self.delay
        if t < 0:
            return np.full(drifted.shape, np.nan), None
        return self.targets[t], None
