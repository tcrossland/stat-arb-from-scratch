"""Phase 7: this source's tables and its universe, from the pinned MarketParquet snapshot.

    uv run python -m statarb.data.marketparquet_tables

Reads the snapshot pinned in config/marketparquet.toml, the bars of `[sample]`
alone, applies the rules of decision record 0009 and writes, under `[tables]
derived`: `prices` (the bars the rules keep, every stock symbol and the factor
ETFs), `returns` (price returns) and `universe_<name>` (the phase 0 liquidity
ranking over every stock symbol of the day). It writes the universe's report to
reports/phase-07/universe.md, statistics only.

The suffix of a delisted symbol is part of each key here and of no decision.
The report counts it, as it counts symbol shapes, to describe what the ranking
let in.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from statarb.config import load_config, raw_store, repo_root, resolve_path
from statarb.data import cache, marketparquet
from statarb.data.quality import _table, monthly_churn
from statarb.data.returns import total_returns
from statarb.data.schema import DATE, PRICE_COLUMNS, TICKER
from statarb.data.universe import build_universe
from statarb.io import read_parquet, write_parquet

BAR = [DATE, TICKER, *PRICE_COLUMNS, "volume"]
# Why a bar is dropped (decision record 0009, rules 2 and 3), in the order the rules are applied.
NOT_A_SESSION, ZERO_VOLUME, CONTRADICTS = "not a trading day", "zero volume", "contradicts itself"
SHAPES = ["one to four letters", "five letters", "a letter after a dot", "other"]


def apply_rules(bars: pd.DataFrame, calendar: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The bars the rules keep, and a log of those dropped with `date`, `ticker` and `reason`.

    A bar contradicts itself when a price is missing or not positive, its high is below its low, or its
    open or close lies outside the two.
    """
    prices = bars[PRICE_COLUMNS]
    low, high = bars["low"], bars["high"]
    broken = (
        prices.isna().any(axis=1) | (prices <= 0).any(axis=1) | (high < low)
        | (bars["open"] > high) | (bars["open"] < low) | (bars["close"] > high) | (bars["close"] < low)
    )
    reason = pd.Series("", index=bars.index, dtype="str")
    reason = reason.mask(broken, CONTRADICTS)
    reason = reason.mask(~(bars["volume"] > 0), ZERO_VOLUME)
    reason = reason.mask(~bars[DATE].isin(calendar), NOT_A_SESSION)
    dropped = reason != ""
    log = bars.loc[dropped, [DATE, TICKER]].assign(reason=reason[dropped]).reset_index(drop=True)
    return bars.loc[~dropped, BAR].reset_index(drop=True), log


def price_returns(bars: pd.DataFrame) -> pd.DataFrame:
    """The returns table for this source: the close over the symbol's previous close, with `split_ratio` 1
    and `cash` 0 on every row, since the prices are already split-adjusted and hold no cash."""
    return total_returns(bars.assign(cash=0.0, split_ratio=1.0))


def shape(symbol: str) -> str:
    """What a symbol's form shows of its kind, the suffix aside. Share classes of common stock take every
    form, so this describes and decides nothing (decision record 0009, rule 8)."""
    base = symbol.removesuffix(marketparquet.SUFFIX)
    if re.fullmatch(r"[A-Z]{1,4}", base):
        return SHAPES[0]
    if re.fullmatch(r"[A-Z]{5}", base):
        return SHAPES[1]
    if re.fullmatch(r"[A-Z]+\.[A-Z]+", base):
        return SHAPES[2]
    return SHAPES[3]


@dataclass(frozen=True)
class SourceTables:
    prices: pd.DataFrame
    returns: pd.DataFrame
    universe: pd.DataFrame
    drops: pd.DataFrame
    calendar: pd.DatetimeIndex


def build_tables(stocks: pd.DataFrame, etfs: pd.DataFrame, market: str, ranking: dict[str, Any]) -> SourceTables:
    """The tables from the stock dataset's bars and the factor ETFs': the market ETF's days are the calendar,
    the rules are applied to both, and every stock symbol is ranked."""
    calendar = pd.DatetimeIndex(sorted(etfs.loc[etfs[TICKER] == market, DATE].unique()))
    if len(calendar) == 0:
        raise ValueError(f"no bars for the market instrument {market}")
    both = set(stocks[TICKER]) & set(etfs[TICKER])
    if both:
        raise ValueError(f"symbols in both datasets: {sorted(both)[:5]}")
    bars, drops = apply_rules(pd.concat([stocks[BAR], etfs[BAR]], ignore_index=True), calendar)
    bars = bars.sort_values([DATE, TICKER], kind="mergesort").reset_index(drop=True)
    listed = sorted(set(bars[TICKER]) - set(etfs[TICKER]))
    universe = build_universe(
        bars, listed, calendar, ranking["size"], ranking["liquidity_window_days"], ranking["liquidity_min_observations"]
    )
    return SourceTables(bars, price_returns(bars), universe, drops, calendar)


def drops_by_year(drops: pd.DataFrame) -> pd.DataFrame:
    counted = drops.groupby([drops[DATE].dt.year.rename("year"), "reason"]).size().unstack("reason")
    counted = counted.reindex(columns=[NOT_A_SESSION, ZERO_VOLUME, CONTRADICTS]).fillna(0).astype("int64")
    return counted.rename(columns=lambda c: c.replace(" ", "_")).reset_index()


def members_by_year(universe: pd.DataFrame) -> pd.DataFrame:
    """Member-days by year: how many, how many distinct symbols, and the share by symbol shape and with the suffix."""
    frame = pd.DataFrame({
        "year": universe[DATE].dt.year.to_numpy(),
        TICKER: universe[TICKER].to_numpy(),
        "shape": universe[TICKER].map(shape).to_numpy(),
        "suffixed": universe[TICKER].str.endswith(marketparquet.SUFFIX).to_numpy(dtype=bool),
    })
    rows = []
    for year, g in frame.groupby("year"):
        shares = g["shape"].value_counts(normalize=True)
        rows.append((year, len(g), g[TICKER].nunique(), *(f"{100 * shares.get(s, 0.0):.2f}%" for s in SHAPES), f"{100 * g['suffixed'].mean():.2f}%"))
    return pd.DataFrame(rows, columns=["year", "member_days", "symbols", *(s.replace(" ", "_") for s in SHAPES), "suffixed"])


def near_copies(universe: pd.DataFrame, returns: pd.DataFrame, calendar: pd.DatetimeIndex, window: int, min_obs: int, level: float) -> pd.DataFrame:
    """For each rebalance: the pairs of its members whose returns over the `window` sessions ending that day
    correlate above `level`, and the members in any such pair. Only returns up to the rebalance day are read."""
    members = universe.groupby("rebalanced_on")[TICKER].agg(lambda s: sorted(set(s)))
    wide = returns.loc[returns[TICKER].isin(set(universe[TICKER]))].pivot(index=DATE, columns=TICKER, values="ret").reindex(calendar)
    position = pd.Series(range(len(calendar)), index=calendar)
    rows = []
    for day, names in members.items():
        at = int(position.loc[day])
        block = wide.iloc[max(0, at - window + 1): at + 1][names]
        corr = block.loc[:, block.notna().sum() >= min_obs].corr(min_periods=min_obs).to_numpy()
        above = np.triu(corr > level, k=1)
        rows.append((day, int(above.sum()), int((above | above.T).any(axis=0).sum())))
    return pd.DataFrame(rows, columns=["rebalanced_on", "pairs", "members"])


def near_copies_by_year(copies: pd.DataFrame) -> pd.DataFrame:
    by = copies.groupby(copies["rebalanced_on"].dt.year.rename("year")).agg(
        rebalances=("pairs", "size"), mean_pairs=("pairs", "mean"), most_pairs=("pairs", "max"), mean_members=("members", "mean")
    )
    return by.assign(mean_pairs=by["mean_pairs"].map("{:.2f}".format), mean_members=by["mean_members"].map("{:.2f}".format)).reset_index()


def overlap_by_year(universe: pd.DataFrame, other: pd.DataFrame) -> pd.DataFrame:
    """By year, on the days both universes have members: the share of the other's member-days whose ticker
    is a member here that day."""
    days = set(universe[DATE]) & set(other[DATE])
    theirs = other.loc[other[DATE].isin(days), [DATE, TICKER]]
    found = theirs.merge(universe[[DATE, TICKER]].assign(here=True), on=[DATE, TICKER], how="left")
    found["here"] = found["here"].notna()
    by = found.groupby(found[DATE].dt.year.rename("year"))["here"].agg(member_days="size", also_here="mean")
    return by.assign(also_here=(100 * by["also_here"]).map("{:.2f}%".format)).reset_index()


def universe_report(
    tables: SourceTables, name: str, snapshot: str, digest: str, start: dt.date, end: dt.date,
    ranking: dict[str, Any], level: float, other: pd.DataFrame | None,
) -> str:
    u, churn = tables.universe, monthly_churn(tables.universe)
    copies = near_copies(u, tables.returns, tables.calendar, ranking["liquidity_window_days"], ranking["liquidity_min_observations"], level)
    out = [f"# Phase 7 universe report: `{name}`", ""]
    out += ["Statistics only: no price, volume or return of any symbol on any date.", ""]
    out += [
        "## Snapshot and rules",
        "",
        f"- MarketParquet snapshot {snapshot}, digest {digest[:12]}; bars read from {start} to before {end}",
        f"- Trading days: {len(tables.calendar)} ({tables.calendar[0].date()} to {tables.calendar[-1].date()})",
        f"- Bars kept: {len(tables.prices)} of {tables.prices[TICKER].nunique()} symbols; returns: {len(tables.returns)}",
        f"- Bars dropped: {len(tables.drops)} in {tables.drops[TICKER].nunique()} symbols",
        "",
        ("Bars dropped by the rules of decision record 0009, by year. A bar with zero volume is counted there "
        "whatever else is wrong with it."),
        "",
        _table(drops_by_year(tables.drops)),
    ]
    out += [
        "## Universe",
        "",
        (f"The {ranking['size']} symbols of the stock dataset with the highest median dollar volume over the "
        f"{ranking['liquidity_window_days']} sessions to each month end, of those with bars on at least "
        f"{ranking['liquidity_min_observations']} of them, held from the next session. Dollar volume is unchanged by "
        "split adjustment. No price floor is applied: on adjusted prices it would look ahead."),
        "",
        f"- Effective from {u[DATE].min().date()} to {u[DATE].max().date()}",
        f"- Rebalances: {u['rebalanced_on'].nunique()}",
        f"- Symbols entering per rebalance: mean {churn['entered'].mean():.1f}, most {churn['entered'].max()}",
        f"- Symbols that were ever members: {u[TICKER].nunique()}",
        "",
    ]
    out += [
        "## What the ranking let in",
        "",
        ("Member-days by the form of the symbol and by whether it carries the delisted suffix. The form shows "
        "little of the kind of security: share classes of common stock take every form. The suffix is what "
        "the archive knew at the download, counted here and read by no rule."),
        "",
        _table(members_by_year(u)),
    ]
    out += [
        "## Near-copies",
        "",
        (f"At each month end, pairs of members whose returns over the ranking's window correlate above {level:g}: "
        "two share classes of one company, or one company the archive holds under two symbols. Only returns up "
        "to the month end are read. They are left in (decision record 0009, rule 9)."),
        "",
        _table(near_copies_by_year(copies)),
    ]
    if other is not None:
        out += [
            "## Against the existing universe",
            "",
            ("Of the member-days of the universe built from today's S&P 500 on Alpaca's prices, the share whose "
            "ticker is a member here on the same day."),
            "",
            _table(overlap_by_year(u, other)),
        ]
    return "\n".join(out)


def read_sample(path: Path, start: dt.date, end: dt.date, etfs: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The stock dataset's bars and the named ETFs' in [start, end)."""
    stock_set, etf_set = marketparquet.ASSETS
    return marketparquet.read_days(path, stock_set, start, end)[BAR], marketparquet.read_days(path, etf_set, start, end, etfs)[BAR]


def write_tables(tables: SourceTables, derived: Path, name: str) -> None:
    write_parquet(tables.prices, derived / "prices.parquet", [DATE, TICKER])
    write_parquet(tables.returns, derived / "returns.parquet", [DATE, TICKER])
    write_parquet(tables.universe, derived / f"universe_{name}.parquet", [DATE, TICKER])


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    root = repo_root()
    cfg, data_cfg = load_config("marketparquet", root), load_config("data", root)
    source, ranking, market = cfg["source"], data_cfg["universe"], data_cfg["factors"]["market"]
    if ranking["rebalance"] != "monthly":
        raise ValueError(f"unsupported rebalance rule: {ranking['rebalance']}")
    path = cache.select_snapshot(raw_store(data_cfg["paths"]["raw"], root), marketparquet.NAME, source["snapshot"], source["digest"])
    start, end = cfg["sample"]["start"], cfg["sample"]["end"]
    stocks, etfs = read_sample(path, start, end, [market, *data_cfg["factors"]["sectors"]])
    tables = build_tables(stocks, etfs, market, ranking)
    name = cfg["universe"]["name"]
    write_tables(tables, resolve_path(cfg["tables"]["derived"], root), name)
    existing = resolve_path(data_cfg["paths"]["processed"], root) / "universe.parquet"
    other = read_parquet(existing) if existing.exists() else None
    report = universe_report(
        tables, name, path.name, cache.read_manifest(path)["digest"], start, end, ranking, cfg["universe"]["near_copy_correlation"],
        None if other is None else other.loc[other[DATE] < pd.Timestamp(end)],
    )
    target = resolve_path(data_cfg["paths"]["reports"], root) / "phase-07" / "universe.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report)
    print(f"wrote {target.relative_to(root)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
