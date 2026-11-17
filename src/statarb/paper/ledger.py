"""Phase 6 ledger: one immutable parquet file per trading day.

    data/paper/ledger/date=YYYY-MM-DD.parquet

Each file is one engine step on the open grid (`statarb.backtest.engine.step`)
plus the decision made at that day's close:

- the holdings filled at the previous open (`held`), their return to this
  open, P&L and borrow, the drifted holdings, the trade at this open and the
  holdings after it;
- the decision at this day's close, filled at the next open: the target
  weights of the decile rule and the expected move the no-trade zone checks
  them against or the optimiser solves on;
- the day's trading costs by component, the calibration slope behind the
  decision, and the portfolio rule's status: the optimiser's solver status,
  so a day on which it failed and the book was held is on record.

The next day fills the decision stored here rather than recomputing it, so a
revision the source makes overnight cannot change an order after the fact.
Weights are per unit of capital, as in the engine; dollars are weight times
`book_size`. Every ticker on the day's grid has a row, so a zero and a missing
name are never confused. Files are written to a temporary name and renamed into
place (`statarb.io.write_parquet`), so a crash leaves no partial day.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np
import pandas as pd

from statarb.backtest.engine import Step
from statarb.data.schema import DATE, TICKER
from statarb.io import read_parquet, write_parquet

FILE = re.compile(r"^date=(\d{4}-\d{2}-\d{2})\.parquet$")

# Per-name columns, in file order after date and ticker.
NAME_COLUMNS = ("held", "ret", "pnl", "borrow", "drifted", "trade", "holding", "target", "expected_move")


@dataclass(frozen=True)
class DayMeta:
    """What every row of a day's file carries: how the day was produced."""

    book_size: float
    config_hash: str
    git_commit: str | None
    git_dirty: bool | None
    snapshot: str              # download date of the price snapshot the day was built from


@dataclass(frozen=True)
class Carry:
    """What a ledger day hands to the next: its holdings and its decision, by ticker."""

    tickers: tuple[str, ...]
    holdings: np.ndarray
    target: np.ndarray
    expected_move: np.ndarray

    @classmethod
    def flat(cls, tickers: tuple[str, ...]) -> Carry:
        """Before the first day: no holdings and no decision."""
        n = len(tickers)
        return cls(tickers, np.zeros(n), np.full(n, np.nan), np.full(n, np.nan))

    def on(self, tickers: tuple[str, ...]) -> Carry:
        """The same carry on another day's grid.

        A ticker new to the grid starts flat with no decision. A ticker that
        has left it while held cannot be carried: that is a data problem to
        fix, not a position to drop.
        """
        if tickers == self.tickers:
            return self
        index = {t: i for i, t in enumerate(self.tickers)}
        lost = sorted(t for t, h in zip(self.tickers, self.holdings, strict=True) if h != 0 and t not in set(tickers))
        if lost:
            raise ValueError(f"held names missing from the day's grid: {lost}")
        pick = np.array([index.get(t, -1) for t in tickers], dtype="int64")   # -1: new to the grid

        def take(values: np.ndarray, fill: float) -> np.ndarray:
            return np.append(values, fill)[pick]

        return Carry(tickers, take(self.holdings, 0.0), take(self.target, np.nan), take(self.expected_move, np.nan))


@dataclass(frozen=True)
class DayTotals:
    """Day-level values the per-name rows do not carry: trading costs by component, per unit of capital, the slope
    and the rule's status."""

    cost_spread: float = 0.0
    cost_impact: float = 0.0
    cost_commission: float = 0.0
    slope: float = float("nan")    # calibration slope behind the decision at this day's close
    status: str = ""               # the optimiser's status for this day's fill ("optimal", or why it held the book); empty for other rules


def day_frame(
    date: pd.Timestamp,
    tickers: tuple[str, ...],
    held: np.ndarray,
    step: Step,
    target: np.ndarray,
    expected_move: np.ndarray,
    meta: DayMeta,
    totals: DayTotals = DayTotals(),
) -> pd.DataFrame:
    """The ledger rows for one day, sorted by ticker."""
    n = len(tickers)
    columns = {
        DATE: pd.Series(pd.Timestamp(date), index=range(n)).astype("datetime64[ns]"),
        TICKER: list(tickers),
        "held": held,
        "ret": step.returns,
        "pnl": step.pnl,
        "borrow": step.borrow,
        "drifted": step.drifted,
        "trade": step.trades,
        "holding": step.holdings,
        "target": target,
        "expected_move": expected_move,
        "missing_returns": np.full(n, step.missing, dtype="int64"),
    }
    columns |= {f.name: np.full(n, getattr(totals, f.name), dtype="float64") for f in fields(DayTotals) if f.name != "status"}
    columns["status"] = [totals.status] * n
    columns |= {f.name: [getattr(meta, f.name)] * n for f in fields(DayMeta)}
    return pd.DataFrame(columns).sort_values(TICKER, kind="mergesort").reset_index(drop=True)


def carry_of(frame: pd.DataFrame) -> Carry:
    return Carry(
        tuple(frame[TICKER]),
        frame["holding"].to_numpy(dtype="float64"),
        frame["target"].to_numpy(dtype="float64"),
        frame["expected_move"].to_numpy(dtype="float64"),
    )


def path_for(root: Path, date: pd.Timestamp) -> Path:
    return root / f"date={pd.Timestamp(date):%Y-%m-%d}.parquet"


def dates(root: Path) -> list[pd.Timestamp]:
    """Days in the ledger, in order. Temporary files from an interrupted write are not days."""
    if not root.exists():
        return []
    return sorted(pd.Timestamp(m.group(1)) for p in root.iterdir() if (m := FILE.match(p.name)))


def write_day(root: Path, frame: pd.DataFrame) -> Path:
    days = frame[DATE].unique()
    if len(days) != 1:
        raise ValueError(f"a ledger file holds one day, got {len(days)}")
    path = path_for(root, days[0])
    write_parquet(frame, path, sort_by=[TICKER])
    return path


def read_day(root: Path, date: pd.Timestamp) -> pd.DataFrame:
    return read_parquet(path_for(root, date))


def check_day(frame: pd.DataFrame, previous: pd.DataFrame | None) -> list[str]:
    """Integrity problems in one day's file, given the day before it (None for the first day).

    The chain must be exact: every holding carried in is the previous day's
    holding after its fill, bit for bit, and the P&L is the holding times the
    return. Floats round-trip through parquet unchanged, so any difference is
    an error, not noise.
    """
    problems = []
    if frame[DATE].nunique() != 1:
        problems.append("more than one date in the file")
    if frame[TICKER].duplicated().any():
        problems.append("duplicate tickers")
    for name in ("missing_returns", *(f.name for f in fields(DayTotals)), *(f.name for f in fields(DayMeta))):
        if frame[name].nunique(dropna=False) != 1:
            problems.append(f"{name} differs between rows")
    if not np.array_equal(frame["pnl"].to_numpy(), (frame["held"] * frame["ret"]).to_numpy()):
        problems.append("pnl is not held times ret")
    if not np.array_equal(frame["drifted"].to_numpy(), (frame["held"] * (1.0 + frame["ret"])).to_numpy()):
        problems.append("drifted is not held times (1 + ret)")
    if previous is None:
        if (frame["held"] != 0).any():
            problems.append("the first day carries holdings in")
        return problems
    if previous[DATE].iloc[0] >= frame[DATE].iloc[0]:
        problems.append("the previous day is not earlier")
    carried = carry_of(previous)
    try:
        expected = carried.on(tuple(frame[TICKER]))
    except ValueError as err:
        return [*problems, str(err)]
    if not np.array_equal(frame["held"].to_numpy(), expected.holdings):
        problems.append("held is not the previous day's holding")
    return problems


def check(root: Path) -> list[str]:
    """Integrity problems across the whole ledger, each prefixed with its date."""
    problems, previous = [], None
    for day in dates(root):
        frame = read_day(root, day)
        problems += [f"{day:%Y-%m-%d}: {p}" for p in check_day(frame, previous)]
        previous = frame
    return problems
