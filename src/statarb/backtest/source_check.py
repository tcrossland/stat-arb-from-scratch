"""Phase 7: check MarketParquet against Alpaca on the existing names, and write reports/phase-07/cross_check.md.

    uv run python -m statarb.backtest.source_check

Reads the phase 0 tables, the pinned MarketParquet snapshot and the phase 2
log. It compares the two sources' bars for the candidates and the factor ETFs
(statarb.data.cross_check), then runs the phase 2 headline twice, once on each
source's prices for the same universe, and sets both beside the logged metrics.

The second run repeats a logged path on other prices to size the difference
between the sources. It is not logged and adds no trial. No day after the last
the backtest runners read is read from either source.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from statarb.backtest import experiments
from statarb.backtest.config import BacktestConfig, load_backtest_config
from statarb.backtest.metrics import by_year
from statarb.backtest.run import Outcome, evaluate
from statarb.backtest.sweep import (
    build_grids,
    fill,
    headline_variant,
    record,
    signal_of,
    start_index,
    targets,
)
from statarb.config import load_config, raw_store, repo_root, resolve_path
from statarb.data import cache, cross_check, marketparquet
from statarb.data.quality import _table
from statarb.data.returns import total_returns
from statarb.data.schema import DATE, PRICE_COLUMNS, TICKER
from statarb.factors.build import build_residuals, stocks_to_model
from statarb.io import read_parquet
from statarb.paper.config import backtest_last
from statarb.signals.tables import Tables, build_tables, cut_after, load_long

METRICS = [
    "days", "sharpe", "gross_sharpe", "ann_return", "ann_gross_return", "ann_vol", "max_drawdown", "turnover",
    "break_even_bps", "ann_long_pnl", "ann_short_pnl", "position_hit_rate", "day_hit_rate", "missing_returns",
]


def second_bars(path: Path, stocks: list[str], etfs: list[str], start: dt.date, end: dt.date) -> pd.DataFrame:
    """The snapshot's bars in [start, end) for the stocks, from the stock dataset, and the ETFs, from the ETF one."""
    stock_set, etf_set = marketparquet.ASSETS
    frames = [marketparquet.read_days(path, stock_set, start, end, stocks), marketparquet.read_days(path, etf_set, start, end, etfs)]
    bars = pd.concat(frames, ignore_index=True)[[DATE, TICKER, *PRICE_COLUMNS, "volume"]]
    return bars.sort_values([DATE, TICKER], kind="mergesort").reset_index(drop=True)


def second_tables(
    bars: pd.DataFrame,
    candidates: pd.DataFrame,
    universe: pd.DataFrame,
    sectors: pd.DataFrame,
    factors_cfg: dict[str, Any],
    market: str,
) -> Tables:
    """The backtest's tables with the second source's prices and price returns, Model A refitted on them,
    and the universe and sectors as they are: the same names on other prices."""
    returns = total_returns(bars.assign(cash=0.0, split_ratio=1.0))
    stocks = stocks_to_model(candidates, returns)
    residuals = build_residuals(returns, sectors, bars, stocks, factors_cfg, market)
    return build_tables(returns, bars, residuals, universe, sectors, market, factors_cfg["sector_etfs"])


@dataclass(frozen=True)
class Headline:
    outcome: Outcome
    book: pd.DataFrame       # target weights, dates by tickers
    start: int


def headline(tables: Tables, cfg: BacktestConfig, sector_etfs: dict[str, str]) -> Headline:
    """The phase 2 headline configuration at its headline fill, on `tables`."""
    head = headline_variant(cfg)
    book = targets(head, signal_of(head, cfg, sector_etfs).scores(tables), tables, cfg)
    result = fill(book, build_grids(tables), cfg.fills.headline, cfg)
    frame = pd.DataFrame(book, index=tables.dates, columns=tables.tickers)
    return Headline(evaluate(cfg, head, cfg.fills.headline, result, True), frame, start_index(tables, cfg))


def logged_metrics(entries: list[dict[str, Any]], cfg: BacktestConfig) -> dict[float, dict[str, Any]]:
    """The latest logged metrics of the headline at each cost level."""
    head = headline_variant(cfg)
    out = {}
    for level in cfg.costs.levels_bps:
        wanted = experiments.config_id(record(head, cfg.fills.headline, level, cfg))
        found = [e for e in entries if e["config_id"] == wanted]
        if not found:
            raise ValueError(f"the phase 2 log holds no entry for the headline at {level} bps")
        out[level] = found[-1]["metrics"]
    return out


def leg_overlap(first: Headline, second: Headline) -> pd.DataFrame:
    """Of the names in each leg of the first book, the share also in that leg of the second, averaged over
    the days the first holds the leg."""
    names = sorted(set(first.book.columns) & set(second.book.columns))
    a = first.book.iloc[first.start:][names].to_numpy()
    b = second.book.reindex(index=first.book.index[first.start:], columns=names).fillna(0.0).to_numpy()
    rows = []
    for leg, sign in (("long", 1.0), ("short", -1.0)):
        held, also = sign * a > 0, (sign * a > 0) & (sign * b > 0)
        days = held.sum(axis=1) > 0
        rows.append((leg, int(days.sum()), round(float((also[days].sum(axis=1) / held[days].sum(axis=1)).mean()), 4)))
    return pd.DataFrame(rows, columns=["leg", "days", "mean_share_in_common"])


def metrics_table(logged: dict[str, Any], first: dict[str, Any], second: dict[str, Any]) -> pd.DataFrame:
    def cell(value: Any) -> str:
        return str(value) if isinstance(value, int) else f"{value:.4f}"

    rows = [(name, cell(logged[name]), cell(first[name]), cell(second[name]), cell(second[name] - logged[name])) for name in METRICS]
    return pd.DataFrame(rows, columns=["metric", "logged", "alpaca_rerun", "marketparquet", "difference"])


def years_table(first: pd.DataFrame, second: pd.DataFrame) -> pd.DataFrame:
    a, b = by_year(first), by_year(second)
    out = pd.DataFrame({
        "year": a.index,
        "alpaca_net_return": a["net_return"].round(4).to_numpy(),
        "marketparquet_net_return": b["net_return"].reindex(a.index).round(4).to_numpy(),
        "alpaca_net_sharpe": a["net_sharpe"].round(4).to_numpy(),
        "marketparquet_net_sharpe": b["net_sharpe"].reindex(a.index).round(4).to_numpy(),
    })
    return out


def comparison_section(
    first: pd.DataFrame, second: pd.DataFrame, returns: pd.DataFrame, etfs: list[str], check: dict[str, Any]
) -> list[str]:
    """The report's sections on the bars: `first` on the download's split basis, `second` as served."""
    pairs = cross_check.paired(first, second)
    held = pairs["held"].value_counts()
    alone = cross_check.one_sided(pairs)
    few = alone["rows"] < check["one_sided_rows"]
    r = cross_check.return_pairs(first, second, returns)
    apart = cross_check.partings(r, check["step"])
    based = cross_check.against_basis(pairs, check["basis_window_days"])
    other = cross_check.other_basis(based, check["basis_tolerance"])
    tol, step = check["return_tolerance"], check["step"]
    out = ["## Names and rows", ""]
    out += [
        f"- Tickers: {first[TICKER].nunique()} in Alpaca's tables, {second[TICKER].nunique()} of them in MarketParquet's files",
        (f"- Symbol-days: {int(held.get('both', 0))} in both, {int(held.get('first', 0))} in Alpaca alone, "
        f"{int(held.get('second', 0))} in MarketParquet alone"),
        "",
        (f"Tickers with at least {check['one_sided_rows']} rows in one source alone (`first` is Alpaca, `second` "
         "MarketParquet). Alpaca's rows are after its cleaning, which drops a ticker's bars before its configured listing."),
        "",
        _table(alone.loc[~few]),
        (f"With fewer: {int((alone.loc[few, 'held'] == 'first').sum())} tickers in Alpaca alone, "
         f"{int((alone.loc[few, 'held'] == 'second').sum())} in MarketParquet alone."),
        "",
    ]
    out += [
        "## Closes and volumes on one split basis",
        "",
        (f"Alpaca's bars are divided by every later split, MarketParquet's are as served. A close agrees within "
        f"{check['close_tolerance']:g} of the other, a volume within {check['volume_tolerance']:g}, both relative. "
        "The volume ratio is MarketParquet's over Alpaca's."),
        "",
        _table(cross_check.agreement_by_year(pairs, check["close_tolerance"], check["volume_tolerance"])),
    ]
    out += [
        "## Price returns, by what went ex",
        "",
        (f"Each source's close over its previous close, where both have the same previous day; Alpaca's on its "
        f"split-adjusted closes, so neither holds a dividend. They agree within {tol:g} and are apart beyond {step:g}, "
        "both absolute. The kind is what Alpaca's actions say went ex that day."),
        "",
        _table(cross_check.returns_by_kind(r, tol, step)),
    ]
    out += [
        "## Where the split-adjusted series part",
        "",
        f"Returns apart by more than {step:g}, by year and by what went ex in Alpaca's actions.",
        "",
        _table(cross_check.partings_by_year(r, apart)),
        f"The {check['busiest_days']} days on which the most tickers part:",
        "",
        _table(cross_check.busiest_days(apart, check["busiest_days"])),
        (f"A ticker is on another basis where the centred {check['basis_window_days']}-day median of the two closes' "
        f"ratio is further than {check['basis_tolerance']:g} from 1: MarketParquet's adjustment holds something "
        "Alpaca's splits do not, or lacks one of them."),
        "",
        _table(cross_check.other_basis_by_year(based, check["basis_tolerance"])),
        f"{len(other)} tickers, with the days each is on another basis:",
        "",
        _table(other),
    ]
    out += [
        "## Cash days",
        "",
        ("Alpaca's days with cash going ex and no split, by the size of the cash as a share of the price (its total "
        f"return less its price return). MarketParquet's return is Alpaca's price return within {tol:g}, so the cash "
        "is not in it, or else it is nearer Alpaca's total return, so the cash is folded into its adjustment, or "
        "nearer the price return. Alpaca's cash includes spin-offs valued as cash (decision record 0004)."),
        "",
        _table(cross_check.cash_days(r, tol, check["cash_sizes"])),
    ]
    out += [
        "## What the returns lack",
        "",
        ("Pooled over symbol-days by year, as a share of Alpaca's squared total returns: what Alpaca's own price "
        "return lacks, which is its dividends and other cash, and what MarketParquet's return lacks, which is "
        "that less what it folds in, plus every other difference between the sources."),
        "",
        _table(cross_check.variance_shares(r)),
    ]
    out += [
        "## Whether the two closes are the same close",
        "",
        ("The share of closes further from the ticker's basis than each band, relative, so a different basis does "
        "not count and a different print does."),
        "",
    ]
    of_etfs = based[TICKER].isin(etfs)
    for label, part in (("Stocks", based.loc[~of_etfs]), ("ETFs", based.loc[of_etfs])):
        out += [f"{label}:", "", _table(cross_check.closes_by_year(part, check["close_bands"]))]
    return out


def headline_section(
    first: Headline, second: Headline, logged: dict[float, dict[str, Any]], cfg: BacktestConfig, inputs: list[str]
) -> list[str]:
    head = headline_variant(cfg)
    same = all(first.outcome.metrics[level] == logged[level] for level in cfg.costs.levels_bps)
    out = ["## The headline on this source", ""]
    out += [
        (f"The phase 2 headline ({head.label()}, fill {cfg.fills.headline}) on the same universe and sectors, with "
        "MarketParquet's prices, its price returns in place of total returns, and Model A refitted on them. It "
        "repeats a logged path to size the sources' difference: it is not logged and adds no trial."),
        "",
        f"Alpaca's rerun gives the logged metrics exactly at every cost level: {'yes' if same else 'no'}.",
        "",
        *inputs,
        "",
    ]
    for level in (0.0, float(cfg.costs.headline_bps)):
        out += [f"At {level:g} bps one way:", "", _table(metrics_table(logged[level], first.outcome.metrics[level], second.outcome.metrics[level]))]
    level = float(cfg.costs.headline_bps)
    a, b = first.outcome.daily[level], second.outcome.daily[level]
    shared = a.index.intersection(b.index)
    out += [
        (f"Daily returns of the two runs at {level:g} bps over {len(shared)} days: correlation "
        f"{np.corrcoef(a.loc[shared, 'net'], b.loc[shared, 'net'])[0, 1]:.4f} net, "
        f"{np.corrcoef(a.loc[shared, 'gross'], b.loc[shared, 'gross'])[0, 1]:.4f} gross."),
        "",
        _table(leg_overlap(first, second)),
        f"By year at {level:g} bps:",
        "",
        _table(years_table(a, b)),
    ]
    return out


def input_differences(first: Tables, second: Tables, start: int) -> list[str]:
    """What the second run's tables hold that differs from the first's, counted."""
    def member_days(tables: Tables, frame: pd.DataFrame) -> int:
        return int((tables.members[start:] & frame.to_numpy()[start:]).sum())

    names = sorted(set(first.stocks) & set(second.stocks))
    a = first.residual[names].notna() & second.residual[names].isna()
    b = second.residual[names].notna() & first.residual[names].isna()
    total = int(first.members[start:].sum())
    return [
        f"- Stocks with residuals: {len(first.stocks)} on Alpaca, {len(second.stocks)} on MarketParquet",
        (f"- Member-days from the first signal date: {total}; with a residual: {member_days(first, first.residual.notna())} on "
        f"Alpaca, {member_days(second, second.residual.reindex(columns=first.stocks).notna())} on MarketParquet"),
        f"- Stock-days with a residual on one source alone: {int(a.to_numpy().sum())} on Alpaca, {int(b.to_numpy().sum())} on MarketParquet",
    ]


def cross_check_report(
    path: Path,
    manifest: dict[str, Any],
    long: dict[str, pd.DataFrame],
    candidates: pd.DataFrame,
    actions: pd.DataFrame,
    entries: list[dict[str, Any]],
    cfg: BacktestConfig,
    factors_cfg: dict[str, Any],
    market: str,
    etfs: list[str],
    start: dt.date,
    last: pd.Timestamp,
    check: dict[str, Any],
    source: dict[str, str],
) -> str:
    """The report: `long` the phase 0 and 1 tables cut at `last`, the snapshot at `path` read from `start` to `last`."""
    prices, returns = long["prices"], long["returns"]
    end = (last + pd.Timedelta(days=1)).date()
    bars = second_bars(path, sorted(candidates[TICKER]), etfs, start, end)
    first = cross_check.on_download_basis(prices, actions.loc[actions[DATE] <= last])
    sector_etfs = factors_cfg["sector_etfs"]
    first_tables = build_tables(*long.values(), market, sector_etfs)
    second_run_tables = second_tables(bars, candidates, long["universe"], long["sectors"], factors_cfg, market)
    one, two = headline(first_tables, cfg, sector_etfs), headline(second_run_tables, cfg, sector_etfs)
    out = ["# Phase 7 cross-check: MarketParquet against Alpaca", ""]
    out += ["Statistics only: no price, volume or return of any symbol on any date.", ""]
    out += [
        "## Snapshots",
        "",
        f"- Alpaca: snapshot {source['snapshot']}, digest {source['digest'][:12]}, the phase 0 tables built from it",
        f"- MarketParquet: snapshot {path.name}, digest {manifest['digest'][:12]}, basis {manifest['basis']}",
        f"- Days compared: from {start} through {last.date()}, the last day the backtest runners read",
        "",
    ]
    out += comparison_section(first, bars, returns, etfs, check)
    out += headline_section(one, two, logged_metrics(entries, cfg), cfg, input_differences(first_tables, second_run_tables, one.start))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    root = repo_root()
    data_cfg, mp_cfg, factors_cfg = load_config("data", root), load_config("marketparquet", root), load_config("factors", root)
    last = backtest_last(root)
    if last is None or last.date() >= mp_cfg["sample"]["end"]:
        raise ValueError(f"the backtest runners' last day, {last}, is not before [sample] end, {mp_cfg['sample']['end']}")
    processed = resolve_path(data_cfg["paths"]["processed"], root)
    reports = resolve_path(data_cfg["paths"]["reports"], root)
    source = mp_cfg["source"]
    path = cache.select_snapshot(raw_store(data_cfg["paths"]["raw"], root), marketparquet.NAME, source["snapshot"], source["digest"])
    report = cross_check_report(
        path,
        cache.read_manifest(path),
        cut_after(load_long(processed), last),
        read_parquet(processed / "candidates.parquet"),
        read_parquet(processed / "actions.parquet"),
        experiments.read(reports / "phase-02" / "experiments.jsonl"),
        load_backtest_config(root),
        factors_cfg,
        data_cfg["factors"]["market"],
        [data_cfg["factors"]["market"], *data_cfg["factors"]["sectors"]],
        mp_cfg["sample"]["start"],
        last,
        mp_cfg["cross_check"],
        data_cfg["source"],
    )
    target = reports / "phase-07" / "cross_check.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report)
    print(f"wrote {target.relative_to(root)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
