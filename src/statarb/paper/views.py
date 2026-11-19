"""Phase 6 ledger explorer: tables over the ledger, for the local app in notebooks/ledger.py.

Every function but `load` is a pure function of its arguments: ledger frames,
as `statarb.paper.drift.read_ledger` returns them, and the sectors table.
`load` reads the ledger, the sectors table of the snapshot in use and the
run's sessions in `config/paper.toml`; nothing here writes. The explorer reads forward days by design, so nothing it computes
enters an experiment log, a report or a decision, and it runs only locally:
decision record 0003 forbids redistributing the data the ledger derives from.

Weights are per unit of capital, as in the ledger; a `_usd` column is a weight
times `book_size`. A day's `holding` is the book after the fill at its open,
and its `pnl` and `borrow` were earned by `held`, the book carried in. Trading
costs are day-level, so attribution by name or sector covers P&L and borrow
only. Under the optimiser `target` is NaN: the trades at the next open are
known only once the next day is filled.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from statarb.config import load_config, resolve_path
from statarb.data.schema import DATE, TICKER, exchange_today
from statarb.io import read_parquet
from statarb.paper import ledger
from statarb.paper import sessions as sessions_
from statarb.paper.config import Run, load_paper_config
from statarb.paper.daily import COMPLETE, LEDGER, PROCESSED, calendar_for
from statarb.paper.drift import read_ledger

NO_SECTOR = "no sector"      # names with no sector row on the day: the hedge ETFs
COSTS = ("cost_spread", "cost_impact", "cost_commission")
SIDES = {1.0: "long", -1.0: "short"}


@dataclass(frozen=True)
class Ledger:
    """What the explorer reads: every ledger day, the sectors of the snapshot in use and the ledger's own check."""

    frame: pd.DataFrame
    sectors: pd.DataFrame
    snapshot: str | None           # the processed snapshot the sectors come from; None if there is none
    problems: tuple[str, ...]      # `statarb.paper.ledger.check`: empty when the chain is intact
    run: Run | None = None         # `[run]` of the checkout's config/paper.toml; None if it has no such file


def load(root: Path) -> Ledger:
    """The ledger of the checkout at `root`, with the sectors of its latest complete daily snapshot."""
    paper = resolve_path(load_config("data", root)["paths"]["paper"], root)
    processed = paper / PROCESSED
    done = sorted(p for p in processed.iterdir() if (p / COMPLETE).exists()) if processed.exists() else []
    sectors = read_parquet(done[-1] / "sectors.parquet") if done else pd.DataFrame(columns=[TICKER, "sector", "valid_from", "valid_to"])
    run = load_paper_config(root).run if (root / "config" / "paper.toml").is_file() else None
    return Ledger(read_ledger(paper / LEDGER), sectors, done[-1].name if done else None, tuple(ledger.check(paper / LEDGER)), run)


def due(run: Run | None, last_done: pd.Timestamp | None, now: dt.datetime) -> pd.DatetimeIndex | None:
    """The sessions the daily job would process if it ran at `now`, by its own rule (`statarb.paper.sessions.due`)
    on the run's calendar, first session and run time: none when the ledger is up to date. None where no forward
    run is configured. `now` must be time zone aware."""
    if run is None or run.first is None:
        return None
    sessions = calendar_for(run.calendar, run.first, exchange_today(now))
    return sessions_.due(sessions, now, run.first, last_done, run.run_time)


def days(frame: pd.DataFrame) -> list[pd.Timestamp]:
    return [pd.Timestamp(d) for d in sorted(frame[DATE].unique())] if len(frame) else []


def between(frame: pd.DataFrame, first: pd.Timestamp | None = None, last: pd.Timestamp | None = None) -> pd.DataFrame:
    """The rows from `first` to `last`, both included; None leaves that end open."""
    keep = pd.Series(True, index=frame.index)
    if first is not None:
        keep &= frame[DATE] >= pd.Timestamp(first)
    if last is not None:
        keep &= frame[DATE] <= pd.Timestamp(last)
    return frame.loc[keep]


def with_sector(frame: pd.DataFrame, sectors: pd.DataFrame) -> pd.DataFrame:
    """`frame` with a `sector` column: the row with `valid_from` <= date and `valid_to` null or later, else NO_SECTOR."""
    out = frame.reset_index(drop=True)
    rows = out[[DATE, TICKER]].reset_index(names="row").merge(sectors[[TICKER, "sector", "valid_from", "valid_to"]], on=TICKER)
    valid = (rows["valid_from"] <= rows[DATE]) & (rows["valid_to"].isna() | (rows[DATE] < rows["valid_to"]))
    found = rows.loc[valid].drop_duplicates("row").set_index("row")["sector"]
    return out.assign(sector=found.reindex(out.index).fillna(NO_SECTOR).to_numpy())


def _side(weight: pd.Series) -> pd.Series:
    return np.sign(weight).map(SIDES)


def _usd(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column] * frame["book_size"]


def per_day(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per day of the day-level columns, which every row of a day carries."""
    columns = ["missing_returns", *COSTS, "slope", "status", "book_size", "config_hash", "git_commit", "git_dirty", "snapshot"]
    return frame.sort_values([DATE, TICKER]).groupby(DATE, sort=True)[columns].first()


def book(frame: pd.DataFrame, sectors: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    """The book after the fill at the open of `date`: every name held, largest first. `prior_expected_move` is the
    expected move the fill was decided on, which the previous ledger day recorded at its close; the day's own
    `expected_move` is the decision for the next open and belongs to `next_open`. NaN on the first ledger day and
    for a name the previous day's grid did not have."""
    date = pd.Timestamp(date)
    earlier = frame.loc[frame[DATE] < date]
    decided = earlier.loc[earlier[DATE] == earlier[DATE].max()].set_index(TICKER)["expected_move"]
    day = with_sector(frame.loc[(frame[DATE] == date) & (frame["holding"] != 0)], sectors)
    out = pd.DataFrame({
        TICKER: day[TICKER], "sector": day["sector"], "side": _side(day["holding"]),
        "holding": day["holding"], "holding_usd": _usd(day, "holding"),
        "prior_expected_move": day[TICKER].map(decided).astype("float64"),
    })
    return out.iloc[np.argsort(-out["holding"].abs().to_numpy(), kind="stable")].reset_index(drop=True)


def exposure(frame: pd.DataFrame) -> pd.DataFrame:
    """Per day, the book after the open: long and short weight, gross, net and the names on each side."""
    h = frame["holding"]
    parts = pd.DataFrame({
        DATE: frame[DATE], "long": h.clip(lower=0), "short": h.clip(upper=0),
        "names_long": (h > 0).astype("int64"), "names_short": (h < 0).astype("int64"),
    })
    out = parts.groupby(DATE, sort=True).sum()
    return out.assign(gross=out["long"] - out["short"], net=out["long"] + out["short"])[
        ["long", "short", "gross", "net", "names_long", "names_short"]
    ]


def sector_exposure(held: pd.DataFrame) -> pd.DataFrame:
    """A `book` by sector: long, short, net and gross weight and the names held, largest gross first."""
    w = held["holding"]
    parts = pd.DataFrame({"sector": held["sector"], "long": w.clip(lower=0), "short": w.clip(upper=0), "names": 1})
    out = parts.groupby("sector").sum()
    out = out.assign(net=out["long"] + out["short"], gross=out["long"] - out["short"])
    return out.sort_values("gross", ascending=False, kind="stable")[["long", "short", "net", "gross", "names"]]


def action(drifted: pd.Series, holding: pd.Series) -> pd.Series:
    """What a trade did to a name: open, close, flip, add or reduce."""
    before, after = np.sign(drifted), np.sign(holding)
    labels = np.select(
        [(before == 0) & (after != 0), (before != 0) & (after == 0), before * after < 0, holding.abs() > drifted.abs()],
        ["open", "close", "flip", "add"],
        "reduce",
    )
    return pd.Series(labels, index=holding.index)


def trades(frame: pd.DataFrame) -> pd.DataFrame:
    """Every trade at an open, latest day first and largest first within a day."""
    t = frame.loc[frame["trade"] != 0]
    out = pd.DataFrame({
        DATE: t[DATE], TICKER: t[TICKER], "action": action(t["drifted"], t["holding"]),
        "drifted": t["drifted"], "trade": t["trade"], "holding": t["holding"], "trade_usd": _usd(t, "trade"),
    })
    order = np.lexsort((-out["trade"].abs().to_numpy(), -out[DATE].to_numpy().astype("int64")))
    return out.iloc[order].reset_index(drop=True)


def pnl(frame: pd.DataFrame) -> pd.DataFrame:
    """Per day in dollars: gross P&L, borrow, each cost, net and cumulative net, as the daily note nets them; and
    turnover, the weight traded."""
    sums = frame.groupby(DATE, sort=True)[["pnl", "borrow"]].sum()
    trade = frame["trade"].abs().groupby(frame[DATE], sort=True).sum()
    day = per_day(frame)
    book_size = day["book_size"]
    out = pd.DataFrame({"gross_usd": sums["pnl"] * book_size, "borrow_usd": sums["borrow"] * book_size})
    for name in COSTS:
        out[f"{name}_usd"] = day[name] * book_size
    out["net_usd"] = out["gross_usd"] - out["borrow_usd"] - out[[f"{c}_usd" for c in COSTS]].sum(axis=1)
    out["cumulative_net_usd"] = out["net_usd"].cumsum()
    out["turnover"] = trade
    return out


def attribution(frame: pd.DataFrame, sectors: pd.DataFrame, by: str) -> pd.DataFrame:
    """P&L and borrow in dollars by `by`: "ticker", "sector" or "side" (of the holding that earned them), largest
    absolute net first. Costs are day-level and not attributed."""
    earned = with_sector(frame.loc[frame["held"] != 0], sectors)
    earned = earned.assign(side=_side(earned["held"]), pnl_usd=_usd(earned, "pnl"), borrow_usd=_usd(earned, "borrow"))
    key = {"ticker": TICKER, "sector": "sector", "side": "side"}[by]
    out = earned.groupby(key).agg(pnl_usd=("pnl_usd", "sum"), borrow_usd=("borrow_usd", "sum"), days=(DATE, "nunique"))
    out = out.assign(net_usd=out["pnl_usd"] - out["borrow_usd"])
    order = np.argsort(-out["net_usd"].abs().to_numpy(), kind="stable")
    return out.iloc[order][["pnl_usd", "borrow_usd", "net_usd", "days"]]


def next_open(frame: pd.DataFrame) -> pd.DataFrame:
    """The latest day's decision for the next open: each name's expected move beside its holding, and the target
    (NaN under the optimiser). Names with neither a holding nor a finite move are left out."""
    last = frame.loc[frame[DATE] == frame[DATE].max()]
    last = last.loc[(last["holding"] != 0) | np.isfinite(last["expected_move"])]
    out = last[[TICKER, "holding", "expected_move", "target"]]
    return out.iloc[np.argsort(-out["expected_move"].fillna(0).to_numpy(), kind="stable")].reset_index(drop=True)


def history(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """One name's rows, day by day."""
    columns = [DATE, "held", "ret", "pnl", "borrow", "drifted", "trade", "holding", "target", "expected_move"]
    return frame.loc[frame[TICKER] == ticker, columns].sort_values(DATE).reset_index(drop=True)


def spells(frame: pd.DataFrame) -> pd.DataFrame:
    """Every holding spell: a run of days a name is held on one side. `entry` is the open it was filled at, `exit`
    the open it was closed or flipped at (NaT while open), `days` the opens it was held after, and `pnl_usd` and
    `borrow_usd` what it earned and paid."""
    f = frame.sort_values([TICKER, DATE], kind="mergesort").reset_index(drop=True)
    sign = np.sign(f["holding"])
    by = f[TICKER]
    spell = (sign != sign.groupby(by).shift(fill_value=0.0)).groupby(by).cumsum()
    held = f.assign(spell=spell, sign=sign)
    runs = held.loc[sign != 0].groupby([TICKER, "spell"]).agg(side=("sign", "first"), entry=(DATE, "min"), last=(DATE, "max"), days=(DATE, "size"))
    following = held.assign(next_date=held.groupby(TICKER)[DATE].shift(-1))
    exits = following.groupby([TICKER, "spell"]).tail(1).set_index([TICKER, "spell"])["next_date"]   # NaT while open
    earned = held.assign(prev_spell=spell.groupby(by).shift(), pnl_usd=_usd(f, "pnl"), borrow_usd=_usd(f, "borrow"))
    earned = earned.loc[f["held"] != 0].groupby([TICKER, "prev_spell"])[["pnl_usd", "borrow_usd"]].sum()
    earned.index = earned.index.set_names([TICKER, "spell"])
    out = runs.join(exits.rename("exit")).join(earned).fillna({"pnl_usd": 0.0, "borrow_usd": 0.0})
    out = out.assign(side=out["side"].map(SIDES)).reset_index()
    return out.sort_values(["entry", TICKER], ascending=[False, True], kind="stable")[
        [TICKER, "side", "entry", "exit", "days", "pnl_usd", "borrow_usd"]
    ].reset_index(drop=True)


def health(frame: pd.DataFrame) -> pd.DataFrame:
    """Per day: the grid and the names held, the held names with no return, the optimiser's status, the slope, and
    the code and snapshot the day ran on."""
    grid = frame.groupby(DATE, sort=True).agg(names=(TICKER, "size"), held=("held", lambda h: int((h != 0).sum())))
    day = per_day(frame)
    return grid.join(day[["missing_returns", "status", "slope", "git_commit", "git_dirty", "snapshot", "config_hash"]])
