"""Data quality report for phase 0 (reports/phase-00/data_quality.md).

Statistics only: counts, shares and dates, never a ticker's price, volume or
return on a date (CLAUDE.md, "No data values"). Large moves are counted by year
and by whether an action went ex that day, not listed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd

from statarb.data.schema import DATE, TICKER


@dataclass(frozen=True)
class QualityInputs:
    prices: pd.DataFrame
    returns: pd.DataFrame
    universe: pd.DataFrame
    candidates: pd.DataFrame
    calendar: pd.DatetimeIndex
    drops: pd.DataFrame
    no_data: list[str]
    snapshot: dict[str, str]
    max_abs_return: float
    min_coverage: float
    data_start: pd.Timestamp
    failed: Mapping[str, str] = field(default_factory=dict)   # ticker -> why the snapshot gave no bars for it


def coverage(prices: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Bars present versus trading days in each ticker's live window."""
    spans = prices.groupby(TICKER)[DATE].agg(first="min", last="max", bars="count")
    pos = pd.Series(range(len(calendar)), index=calendar)
    spans["expected"] = pos.loc[spans["last"]].to_numpy() - pos.loc[spans["first"]].to_numpy() + 1
    spans["coverage"] = spans["bars"] / spans["expected"]
    return spans.reset_index()


def monthly_churn(universe: pd.DataFrame) -> pd.DataFrame:
    sets = universe.groupby("rebalanced_on")[TICKER].agg(lambda s: frozenset(s))
    rows = []
    previous = None
    for day, members in sets.items():
        if previous is not None:
            rows.append((day, len(members - previous), len(previous - members)))
        previous = members
    return pd.DataFrame(rows, columns=["rebalanced_on", "entered", "left"])


def large_moves(returns: pd.DataFrame, universe: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Counts of daily returns beyond the threshold, by year: all, on a day with an action, while a member."""
    big = returns.loc[returns["ret"].abs() > threshold, [DATE, TICKER, "split_ratio", "cash"]]
    members = big.merge(universe[[DATE, TICKER]], on=[DATE, TICKER], how="left", indicator=True)["_merge"] == "both"
    action = ((big["split_ratio"] != 1.0) | (big["cash"] != 0.0)).to_numpy()
    frame = pd.DataFrame(
        {"year": big[DATE].dt.year.to_numpy(), "returns": 1, "on_action_days": action.astype(int),
         "while_member": members.to_numpy().astype(int), TICKER: big[TICKER].to_numpy()}
    )
    by_year = frame.groupby("year").agg(
        returns=("returns", "sum"), tickers=(TICKER, "nunique"),
        on_action_days=("on_action_days", "sum"), while_member=("while_member", "sum"),
    )
    return by_year.reset_index()


def _table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "None.\n"
    cols = list(frame.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in frame.itertuples(index=False):
        cells = []
        for value in row:
            if isinstance(value, pd.Timestamp):
                cells.append(value.date().isoformat())
            elif isinstance(value, float):
                cells.append(f"{value:.4f}")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def render_report(q: QualityInputs) -> str:
    cov = coverage(q.prices, q.calendar)
    low = cov.loc[cov["coverage"] < q.min_coverage].sort_values(["coverage", TICKER])
    moves = large_moves(q.returns, q.universe, q.max_abs_return)
    splits = q.returns.loc[q.returns["split_ratio"] != 1.0]
    split_jumps = splits.loc[splits["ret"].abs() > q.max_abs_return, TICKER]
    gaps = q.returns.loc[
        q.returns["prev_date"].notna()
        & (q.calendar.get_indexer(q.returns[DATE]) - q.calendar.get_indexer(q.returns["prev_date"]) > 1)
    ]
    zero_volume = (
        q.prices.loc[q.prices["volume"] == 0].groupby(TICKER).size().rename("zero_volume_days").reset_index()
    )
    if q.drops.empty:
        drop_reasons = drop_tickers = q.drops
    else:
        drop_reasons = q.drops.groupby("reason").size().rename("rows").reset_index()
        drop_tickers = (
            q.drops.groupby([TICKER, "reason"])[DATE].agg(rows="count", first="min", last="max").reset_index()
        )
    churn = monthly_churn(q.universe)
    members = set(q.universe[TICKER])
    never = sorted(set(q.candidates[TICKER]) - members - set(q.no_data) - set(q.failed))
    joined_late = q.candidates.loc[q.candidates["date_added"] > q.data_start]

    out = ["# Phase 0 data quality report", ""]
    out += ["Statistics only: no price, volume or return of any ticker on any date.", ""]
    out += ["## Snapshots", ""]
    out += [f"- {key}: {value}" for key, value in sorted(q.snapshot.items())]
    out += [
        f"- Trading days: {len(q.calendar)} ({q.calendar[0].date()} to {q.calendar[-1].date()})",
        f"- Candidates: {len(q.candidates)}; tickers with prices: {q.prices[TICKER].nunique()}",
        (
            f"- Price rows: {len(q.prices)}; returns: {len(q.returns)}; split days: {len(splits)}; "
            f"days with cash: {int((q.returns['cash'] != 0).sum())}"
        ),
        "",
    ]
    out += ["## Tickers with no data", "", ", ".join(q.no_data) + "\n" if q.no_data else "None.\n"]
    out += ["## Tickers that failed", "", "Failed downloads, and for a raw snapshot, tickers whose data fails a source rule.", ""]
    out += [*(f"- {t}: {why}" for t, why in sorted(q.failed.items())), ""] if q.failed else ["None.\n"]
    out += [f"## Coverage below {q.min_coverage:.0%} of the live window", ""]
    out += [_table(low[[TICKER, "first", "last", "bars", "expected", "coverage"]])]
    out += ["## Rows dropped by cleaning", "", _table(drop_reasons)]
    out += ["### By ticker", "", _table(drop_tickers)]
    large_tickers = q.returns.loc[q.returns["ret"].abs() > q.max_abs_return, TICKER].nunique()
    out += [f"## Daily total returns with absolute value above {q.max_abs_return:.0%}", ""]
    out += [
        (
            f"{int(moves['returns'].sum())} returns across {large_tickers} tickers, counted by year: "
            "on a day with a split or cash, and while the ticker was in the universe."
        ),
        "",
        _table(moves),
    ]
    out += [
        "## Split days",
        "",
        f"Split days: {len(splits)}; with an absolute return above {q.max_abs_return:.0%}: {len(split_jumps)}"
        + (f" ({', '.join(sorted(set(split_jumps)))})." if len(split_jumps) else "."),
        "",
    ]
    out += ["## Returns spanning missing trading days", "", f"{len(gaps)} returns span more than one trading day.", ""]
    if not gaps.empty:
        per_ticker = gaps.groupby(TICKER).size().rename("gapped_returns").reset_index()
        out += [_table(per_ticker.sort_values(["gapped_returns", TICKER], ascending=[False, True]).head(20))]
    out += ["## Zero-volume days", "", _table(zero_volume)]
    out += ["## Universe", ""]
    if not q.universe.empty:
        out += [
            f"- Effective from {q.universe[DATE].min().date()} to {q.universe[DATE].max().date()}",
            f"- Rebalances: {q.universe['rebalanced_on'].nunique()}",
            f"- Names entering per rebalance: mean {churn['entered'].mean():.1f}, max {churn['entered'].max()}",
            f"- Candidates that were ever members: {len(members)}",
            "",
        ]
    out += ["### Candidates never in the universe", "", ", ".join(never) + "\n" if never else "None.\n"]
    out += ["## Survivorship indicator", ""]
    out += [
        (
            f"{len(joined_late)} of {len(q.candidates)} candidates were added to the S&P 500 after "
            f"{q.data_start.date()}. Their earlier history is included only because they survived into "
            "today's index."
        ),
        "",
    ]
    return "\n".join(out)
