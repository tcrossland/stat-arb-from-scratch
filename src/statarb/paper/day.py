"""One ledger day of the frozen strategy, from the tables cut at its session.

The strategy is a forecast (a phase 3 variant or a phase 5 model forecast)
through a rule (the decile sort, the no-trade zone or the optimiser at a cost
multiplier) with a slope rule, at a book size: the paths `statarb.paper.choice`
logs. Partial adjustment is left out: it kept less than the optimiser for every
forecast.

Everything is built from the tables cut at the session with the backtest's own
code (`statarb.models.run.build_period_lab`, `statarb.backtest.sweep.targets`,
`statarb.backtest.cost_run.no_trade`, `PortfolioLab.optimiser`), so the step on
a session is the backtest's step on that grid time (`backtest_path` builds the
whole path the same way, for the reproduction check and the drift report). A
model forecast comes from the walk-forward's saved model files
(`statarb.models.forecast.saved_forecast`), never retrained. The step itself
fills the decision the ledger recorded the day before
(`statarb.paper.loop.live_step`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from statarb.backtest.cost_run import cost, headline, no_trade, scores_of
from statarb.backtest.costs import TradingCost
from statarb.backtest.engine import (
    FILL_TIMINGS,
    EngineResult,
    Policy,
    Step,
    daily_rates,
    run,
)
from statarb.backtest.rules import DecileRule
from statarb.backtest.sweep import start_index, targets
from statarb.models.backend import Model
from statarb.models.features import build_features
from statarb.models.forecast import saved_forecast
from statarb.models.run import (
    Outcome,
    Settings,
    build_period_lab,
    optimiser_spec,
    path_outcome,
    rule_variant,
    starting_at,
)
from statarb.paper.choice import slope_of
from statarb.paper.config import (
    DECILE,
    OPTIMISER,
    SLOPE_RULES,
    ZONE,
    model_horizon,
    parse_rule,
)
from statarb.paper.ledger import Carry, DayMeta, DayTotals, day_frame
from statarb.paper.loop import live_step
from statarb.portfolio.optimiser import DayNote
from statarb.portfolio.run import PortfolioLab
from statarb.signals.base import Scores, Signal
from statarb.signals.calibration import expected_move
from statarb.signals.registry import make_signal

MOMENTUM_SIGNALS = ("momentum", "residual_momentum")    # decision record 0010


class MissingSession(RuntimeError):
    """The tables have no bar for a session the calendar has: retry with a later snapshot."""


@dataclass(frozen=True)
class MomentumRule:
    """A momentum signal through the decile sort, held in overlapping slices: a path of decision record 0010.

    It reads no calibration: the decile sort ranks the signal itself, so the
    ledger's expected move and slope are NaN on its days.
    """

    signal: str                       # "momentum" or "residual_momentum" in statarb.signals.registry
    window_days: int
    skip_days: int
    decile: float                     # share of ranked members in each leg
    holding_days: int                 # slices the book is averaged over

    def validate(self) -> None:
        if self.signal not in MOMENTUM_SIGNALS:
            raise ValueError(f"a momentum rule runs one of {MOMENTUM_SIGNALS}, not {self.signal!r}")
        if not 0 < self.decile <= 0.5:
            raise ValueError("the decile must be above 0 and at most 0.5")
        if self.holding_days < 1:
            raise ValueError("the holding period must be at least one day")

    def make(self) -> Signal:
        return make_signal(self.signal, window_days=self.window_days, skip_days=self.skip_days)


@dataclass(frozen=True)
class Strategy:
    """The frozen strategy: what `strategy_panels` needs besides the tables."""

    settings: Settings
    forecast: str                     # a [[variants]] name of config/costs.toml, "model H=<horizon>", or a momentum rule's signal
    rule: str                         # DECILE, ZONE or OPTIMISER
    kappa: float | None               # the optimiser's cost multiplier
    slope_rule: str                   # empty for a momentum rule, which reads no slope
    book_size: float
    models: tuple[tuple[pd.Timestamp, Model], ...] = ()   # a model forecast's block models, by first test date
    momentum: MomentumRule | None = None                  # set for the momentum run of decision record 0010

    @property
    def horizon(self) -> int | None:
        return model_horizon(self.forecast)

    def validate(self) -> None:
        s = self.settings
        if FILL_TIMINGS[s.pc.run.fill][1] != 1:
            raise ValueError(f"the daily job fills a decision the next day; fill {s.pc.run.fill!r} fills it the same day")
        if self.rule not in (DECILE, ZONE, OPTIMISER) or (self.rule == OPTIMISER) != (self.kappa is not None):
            raise ValueError(f"the daily job runs the decile sort, the no-trade zone or the optimiser at a multiplier, not {self.rule!r}")
        if not self.book_size > 0:
            raise ValueError("the book size must be positive")
        if self.momentum is not None:
            self.momentum.validate()
            if self.rule != DECILE or self.forecast != self.momentum.signal or self.slope_rule or self.models:
                raise ValueError("a momentum strategy is its signal through the decile sort, with no slope rule and no model files")
            return
        if self.slope_rule not in SLOPE_RULES:
            raise ValueError(f"unknown slope rule {self.slope_rule!r}")
        H = self.horizon
        if H is None:
            if self.forecast not in s.mc.runs.variants:
                raise ValueError(f"{self.forecast!r} is not a forecast phase 5 ran: a model or one of [runs] variants")
            if self.models:
                raise ValueError("a variant's forecast reads no model files")
        else:
            if H not in s.mc.target.horizons:
                raise ValueError(f"{self.forecast!r}: horizon {H} is not in [target] horizons")
            if not self.models:
                raise ValueError(f"{self.forecast!r} needs its saved model files")


def strategy_of(settings: Settings, forecast: str, rule_label: str, slope_rule: str, book_size: float, models=()) -> Strategy:
    """The strategy from a rule as the logs label it (`statarb.paper.config.parse_rule`)."""
    rule, kappa = parse_rule(rule_label)
    s = Strategy(settings, forecast, rule, kappa, slope_rule, float(book_size), tuple(models))
    s.validate()
    return s


def momentum_strategy(settings: Settings, rule: MomentumRule, book_size: float) -> Strategy:
    """A momentum path of decision record 0010 as a strategy the daily job can step."""
    s = Strategy(settings, rule.signal, DECILE, None, "", float(book_size), momentum=rule)
    s.validate()
    return s


@dataclass(frozen=True)
class Panels:
    """The strategy's panels on tables cut at their last date, one row per date of the tables.

    Every row uses only data up to its date, so row d is what the job builds on
    the tables cut at d. The drift report rebuilds every ledger day's decision
    from one set of panels on a later snapshot.
    """

    plab: PortfolioLab          # starting flat at `start`, with the strategy's expected move
    start: int                  # date position of the path's first day
    signal: np.ndarray          # dates x stocks
    slopes: np.ndarray          # dates
    move: np.ndarray            # dates x grid tickers: the expected move, zero for the hedges
    targets: np.ndarray         # dates x grid tickers: the decile rule's decision at each close; NaN for the optimiser

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.plab.lab.tables.dates


def forecast_signal(plab: PortfolioLab, strategy: Strategy) -> np.ndarray:
    """The strategy's forecast on every date of the lab: the variant's signal or the saved models' forecast."""
    lab = plab.lab
    if strategy.momentum is not None:
        return strategy.momentum.make().scores(lab.tables).score
    if strategy.horizon is None:
        return scores_of(lab, plab.variants[strategy.forecast]).score
    tables = lab.tables
    fs = build_features(tables, strategy.settings.mc.features)
    return saved_forecast(fs, tables.dates, strategy.models, (len(tables.dates), len(tables.stocks)))


def panels_on(plab: PortfolioLab, start: int, strategy: Strategy) -> Panels:
    """The strategy on a lab already cut, starting flat on date position `start`."""
    tables = plab.lab.tables
    signal = forecast_signal(plab, strategy)
    if strategy.momentum is not None:
        return momentum_panels(plab, start, strategy.momentum, signal)
    slopes = slope_of(plab, signal, strategy.slope_rule)
    move = expected_move(signal, tables.members, slopes)
    started = starting_at(plab, start, {strategy.forecast: move})
    lab = started.lab
    padded = np.hstack([move, np.zeros((move.shape[0], len(tables.hedges)))])
    if strategy.rule == OPTIMISER:
        decided = np.full(padded.shape, np.nan)
    else:
        decided = targets(rule_variant(started, strategy.forecast), Scores(signal), lab.tables, lab.cfg)
    return Panels(started, start, signal, slopes, padded, decided)


def momentum_panels(plab: PortfolioLab, start: int, rule: MomentumRule, signal: np.ndarray) -> Panels:
    """A momentum rule's panels: the decile sort on the signal itself, with no calibration, so no slope and no expected move."""
    started = starting_at(plab, start, {})
    tables = started.lab.tables
    T = len(tables.dates)
    move = np.hstack([np.full(signal.shape, np.nan), np.zeros((T, len(tables.hedges)))])
    decided = DecileRule(rule.decile, rule.holding_days).targets(Scores(signal), tables.members, start_index(tables, started.lab.cfg), len(tables.hedges))
    return Panels(started, start, signal, np.full(T, np.nan), move, decided)


def strategy_panels(long: Mapping[str, pd.DataFrame], last: pd.Timestamp, first: pd.Timestamp, strategy: Strategy) -> Panels:
    """The strategy on the tables cut at `last`, whose last row must be `last`, starting flat on `first`."""
    last, first = pd.Timestamp(last), pd.Timestamp(first)
    plab = build_period_lab(long, strategy.settings, last)
    dates = plab.lab.tables.dates
    if len(dates) == 0 or dates[-1] != last:
        have = dates[-1].date() if len(dates) else None
        raise MissingSession(f"no {strategy.settings.market} bar for {last.date()} in the tables (last bar {have})")
    start = int(dates.searchsorted(first))
    if start >= len(dates):
        raise ValueError(f"{last.date()} is before the run's first session {first.date()}")
    return panels_on(plab, start, strategy)


def policy_of(p: Panels, strategy: Strategy) -> Policy | None:
    """The backtest's policy for the strategy's rule: none for the decile sort."""
    plab = p.plab
    if strategy.rule == ZONE:
        return no_trade(plab.lab, strategy.book_size, p.move)
    if strategy.rule == OPTIMISER:
        return plab.optimiser(optimiser_spec(plab.pc, strategy.forecast, strategy.kappa), strategy.book_size)
    return None


def backtest_result(p: Panels, strategy: Strategy) -> EngineResult:
    """The strategy's backtest over every date of the panels: the engine's whole path, holdings included."""
    plab = p.plab
    grid = getattr(plab.lab.grids, plab.kind)
    return run(p.targets, grid, plab.delay, plab.lab.borrow_rate, policy_of(p, strategy))


def backtest_path(p: Panels, strategy: Strategy) -> Outcome:
    """The backtest's daily returns and metrics, as `statarb.models.run` runs and logs a path."""
    return path_outcome(p.plab, strategy.forecast, strategy.rule, strategy.kappa, strategy.book_size, backtest_result(p, strategy))


@dataclass(frozen=True)
class SessionInputs:
    """What one session's step and decision need, taken at grid time s = the session."""

    date: pd.Timestamp
    s: int
    tickers: tuple[str, ...]
    returns: np.ndarray
    tradable: np.ndarray
    rate: np.ndarray
    policy: Policy | None
    cost: TradingCost
    target: np.ndarray          # the decision at the close of the session
    expected_move: np.ndarray
    slope: float


def session_inputs(long: Mapping[str, pd.DataFrame], date: pd.Timestamp, first: pd.Timestamp, strategy: Strategy) -> SessionInputs:
    """The strategy on the tables cut at `date`, whose last row must be `date`.

    The path starts flat on `first`, the run's first session, as a backtest path
    starts flat on its first date.
    """
    p = strategy_panels(long, date, first, strategy)
    plab = p.plab
    s = len(p.dates) - 1
    grid = getattr(plab.lab.grids, plab.kind)
    rates = daily_rates(plab.lab.borrow_rate, grid.returns.shape)
    return SessionInputs(
        date=pd.Timestamp(date),
        s=s,
        tickers=grid.tickers,
        returns=grid.returns[s],
        tradable=grid.tradable[s],
        rate=rates[s],
        policy=policy_of(p, strategy),
        cost=cost(plab.lab, headline(plab.lab.ccfg), strategy.book_size, plab.kind),
        target=p.targets[s],
        expected_move=p.move[s],
        slope=float(p.slopes[s]),
    )


def day_costs(c: TradingCost, s: int, trades: np.ndarray) -> dict[str, float]:
    """The cost model's components for one grid time's trades, per unit of capital."""
    row = replace(
        c,
        half_spread=c.half_spread[s : s + 1],
        volatility=c.volatility[s : s + 1],
        dollar_volume=c.dollar_volume[s : s + 1],
        fill_price=c.fill_price[s : s + 1],
    )
    return {k: float(v[0]) for k, v in row.components(trades[None, :], np.zeros(1)).items()}


def ledger_day(inputs: SessionInputs, carry: Carry, meta: DayMeta) -> tuple[pd.DataFrame, Step]:
    """The ledger rows for the session: the step from the previous day's carry, then this day's decision."""
    carried = carry.on(inputs.tickers)
    st = live_step(inputs.s, carried, inputs.returns, inputs.tradable, inputs.rate, inputs.policy)
    costs = day_costs(inputs.cost, inputs.s, st.trades)
    status = st.note.status if isinstance(st.note, DayNote) else ""
    totals = DayTotals(costs["spread"], costs["impact"], costs["commission"], inputs.slope, status)
    frame = day_frame(inputs.date, inputs.tickers, carried.holdings, st, inputs.target, inputs.expected_move, meta, totals)
    return frame, st
