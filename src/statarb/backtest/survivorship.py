"""Phase 7: how much survivorship flatters the reversal results (reports/phase-07/survivorship.md).

    uv run python -m statarb.backtest.survivorship            # run, log and report
    uv run python -m statarb.backtest.survivorship --no-log   # run and report without logging

The phase 2 headline's lookback, holding period, decile and fill, with no
sweep, on four universes of the same size over development:

    1  Alpaca          today's S&P 500                     the logged path, rerun over development
    2  MarketParquet   today's S&P 500         candidates  isolates the source and the missing dividends
    3  MarketParquet   listed, trading today   survivors   isolates the change of candidates
    4  MarketParquet   listed on the day       listed      isolates survivorship

in two forms: reversal on returns (`raw`), and on Model B's residuals, which
need no sectors. Model A runs on universes 1 and 2, where sectors exist. The
seven paths on universes 2 to 4 are trials and are logged; universe 1's are
paths already counted and are not logged again.

Universe 3 is built with look-ahead on purpose: it keeps the symbols without
the delisted suffix, which is the bias being measured. `survivors_universe`
builds it, takes the suffix as an explicit argument, and is called here alone.
Nothing else in this module reads the suffix to decide anything: the report
counts it in each leg.

Model B is fitted month by month on the symbols that have been members up to
that month's ranking, so no residual rests on a later membership.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from matplotlib.figure import Figure

from statarb.backtest import experiments
from statarb.backtest.config import BacktestConfig, load_backtest_config
from statarb.backtest.costs import FlatCost
from statarb.backtest.engine import (
    FILL_TIMINGS,
    TRADING_DAYS,
    EngineResult,
    Grid,
    daily_returns,
    run,
)
from statarb.backtest.metrics import by_year, sharpe
from statarb.backtest.run import Outcome, evaluate
from statarb.backtest.sweep import (
    Variant,
    build_grids,
    decile_variants,
    headline_variant,
    record,
    signal_of,
    start_index,
    targets,
)
from statarb.backtest.trials import path_id, repository_trials
from statarb.config import load_config, repo_root, resolve_path
from statarb.data import marketparquet
from statarb.data.quality import _table
from statarb.data.schema import DATE, TICKER
from statarb.data.universe import build_universe
from statarb.factors.build import build_residuals, market_calendar, stocks_to_model
from statarb.factors.pca import PcaFactorModel, PcaModelConfig
from statarb.factors.report import save_figure
from statarb.io import read_parquet
from statarb.signals.tables import Tables, build_tables, cut_after, load_long

CANDIDATES, SURVIVORS, LISTED = "candidates", "survivors", "listed"
EXISTING = "existing"            # universe 1: Alpaca's tables, never logged here
MODEL_A, MODEL_B, RAW = "Model A", "Model B", "raw"
PCT = 100.0


def read_cut(path: Path, last: pd.Timestamp) -> pd.DataFrame:
    """A stored table's rows dated on or before `last`: later rows are filtered out as the file is read."""
    return pq.read_table(path, filters=[(DATE, "<=", pd.Timestamp(last))]).to_pandas()


def survivors_universe(
    bars: pd.DataFrame, suffix: str, calendar: pd.DatetimeIndex, ranking: dict[str, Any], etfs: list[str]
) -> pd.DataFrame:
    """The ranking over the stock symbols that do not carry `suffix`: those still trading at the download.

    Look-ahead on purpose, for this measurement alone. The suffix says what happened after each day ranked.
    """
    alive = sorted(t for t in set(bars[TICKER]) - set(etfs) if not t.endswith(suffix))
    return build_universe(bars, alive, calendar, ranking["size"], ranking["liquidity_window_days"], ranking["liquidity_min_observations"])


def candidates_universe(
    bars: pd.DataFrame, candidates: pd.DataFrame, calendar: pd.DatetimeIndex, ranking: dict[str, Any]
) -> pd.DataFrame:
    """The ranking over today's S&P 500 names, on this source's bars."""
    names = sorted(set(candidates[TICKER]) & set(bars[TICKER]))
    return build_universe(bars, names, calendar, ranking["size"], ranking["liquidity_window_days"], ranking["liquidity_min_observations"])


def members_to_date(universe: pd.DataFrame) -> dict[pd.Timestamp, list[str]]:
    """For each rebalance day, the symbols chosen at it or at any earlier one."""
    chosen = universe.groupby("rebalanced_on")[TICKER].agg(lambda s: set(s)).sort_index()
    out, so_far = {}, set()
    for day, names in chosen.items():
        so_far = so_far | names
        out[day] = sorted(so_far)
    return out


def pca_residuals_to_date(
    returns: pd.DataFrame, universe: pd.DataFrame, calendar: pd.DatetimeIndex, cfg: PcaModelConfig
) -> pd.DataFrame:
    """Model B's residuals for the days each ranking is in force, fitted on the members to date of that ranking.

    A day's fit reads the window before it, so each month is fitted on the calendar from one window before
    its first day, and only its own days are kept. Nothing here depends on a later ranking.
    """
    model = PcaFactorModel(cfg)
    position = pd.Series(range(len(calendar)), index=calendar)
    days = universe.groupby("rebalanced_on")[DATE].agg(["min", "max"]).sort_index()
    ordered = returns.sort_values(DATE, kind="mergesort")
    frames = []
    for day, stocks in members_to_date(universe).items():
        first, last = int(position.loc[days.loc[day, "min"]]), int(position.loc[days.loc[day, "max"]])
        span = calendar[max(0, first - cfg.window_days): last + 1]
        lo, hi = ordered[DATE].searchsorted(span[0], "left"), ordered[DATE].searchsorted(span[-1], "right")
        block = ordered.iloc[lo:hi]
        got = model.residuals(block.loc[block[TICKER].isin(stocks)], pd.DataFrame(), stocks, span)
        frames.append(got.loc[got[DATE] >= calendar[first]])
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values([DATE, TICKER], kind="mergesort").reset_index(drop=True)


def tables_for(
    returns: pd.DataFrame, prices: pd.DataFrame, residuals: pd.DataFrame, universe: pd.DataFrame,
    sectors: pd.DataFrame, market: str, sector_etfs: dict[str, str],
) -> Tables:
    """The backtest's tables for one universe and one set of residuals, holding the bars of its names alone."""
    names = set(residuals[TICKER]) | set(sector_etfs.values()) | {market}
    if "beta_market" not in residuals:
        residuals = residuals.assign(beta_market=np.nan)        # Model B has none; only the s-score's hedge reads it
    return build_tables(
        returns.loc[returns[TICKER].isin(names)], prices.loc[prices[TICKER].isin(names)], residuals, universe, sectors, market, sector_etfs
    )


@dataclass(frozen=True)
class Path_:
    """One path: where it ran, what it ran and what came of it."""

    universe: str
    form: str                    # RAW, MODEL_A or MODEL_B: what the signal is built from
    variant: Variant
    outcome: Outcome
    book: pd.DataFrame           # target weights, dates by tickers
    grid: Grid
    start: int
    close_after: int | None

    @property
    def result(self) -> EngineResult:
        return self.outcome.result

    @property
    def label(self) -> str:
        return f"{self.universe}, {self.form}"


def variants(cfg: BacktestConfig) -> dict[str, Variant]:
    """The headline and its control on raw returns: the same lookback, scaling and holding period."""
    head = headline_variant(cfg)
    same = (head.lookback_days, head.vol_scaled, head.holding_days)
    raw = next(v for v in decile_variants(cfg) if v.signal == "raw" and (v.lookback_days, v.vol_scaled, v.holding_days) == same)
    return {"residual": head, RAW: raw}


def run_path(
    universe: str, form: str, variant: Variant, tables: Tables, cfg: BacktestConfig, sector_etfs: dict[str, str], close_after: int | None
) -> Path_:
    book = targets(variant, signal_of(variant, cfg, sector_etfs).scores(tables), tables, cfg)
    kind, delay = FILL_TIMINGS[cfg.fills.headline]
    grid = getattr(build_grids(tables), kind)
    result = run(book, grid, delay, cfg.costs.borrow_annual, close_after=close_after)
    frame = pd.DataFrame(book, index=tables.dates, columns=tables.tickers)
    return Path_(universe, form, variant, evaluate(cfg, variant, cfg.fills.headline, result, True), frame, grid, start_index(tables, cfg), close_after)


def entry_config(p: Path_, level: float, cfg: BacktestConfig, last: pd.Timestamp) -> dict[str, Any]:
    """The configuration an entry logs. `universe` and `close_after` put the path apart from every earlier one."""
    return {
        **record(p.variant, cfg.fills.headline, level, cfg),
        "universe": p.universe,
        "close_after": p.close_after,
        "residuals": None if p.form == MODEL_A else "pca",       # the raw form is scored from Model B's first residual on
        "last_date": last.date().isoformat(),
    }


def log_entries(paths: list[Path_], cfg: BacktestConfig, last: pd.Timestamp, state: dict[str, Any], now: dt.datetime) -> list[dict[str, Any]]:
    return [
        experiments.entry(entry_config(p, level, cfg, last), {**m, "closed": p.result.closed}, cfg.run.seed, state, now)
        for p in paths
        for level, m in p.outcome.metrics.items()
    ]


def stopped_after_a_fall(prices: pd.DataFrame, last: pd.Timestamp, bars: int, fall: float) -> set[str]:
    """Symbols whose bars stop before `last` and whose close fell by more than `fall` over their last `bars` bars."""
    ordered = prices.sort_values([TICKER, DATE], kind="mergesort")
    g = ordered.groupby(TICKER, sort=False)
    ends = g[DATE].last()
    final, earlier, count = g["close"].last(), g["close"].nth(-(bars + 1)), g.size()
    earlier = pd.Series(earlier.to_numpy(), index=ordered.loc[earlier.index, TICKER].to_numpy())
    change = final / earlier.reindex(final.index) - 1
    return set(final.index[(ends < last) & (count > bars) & (change < -fall)])


def with_delisting_loss(result: EngineResult, grid: Grid, names: set[str], loss: float) -> tuple[EngineResult, int]:
    """The result with a further loss of `loss` on each holding the engine closed in one of `names` because
    its bars had stopped: a long loses it and a short gains it, booked when it is closed. Positions are unchanged."""
    before = np.vstack([np.zeros((1, result.holdings.shape[1])), result.holdings[:-1]])
    closed = (result.holdings == 0) & (before != 0) & ~grid.tradable
    closed &= np.isin(np.asarray(result.tickers), sorted(names))[None, :]
    return dataclasses.replace(result, pnl=result.pnl - loss * np.where(closed, before, 0.0)), int(closed.sum())


def leg_shares(p: Path_, suffix: str) -> dict[str, float]:
    """Of the name-days in each leg of the target book, the share whose symbol carries `suffix`."""
    book = p.book.iloc[p.start:]
    marked = np.array([str(t).endswith(suffix) for t in book.columns])
    values = book.to_numpy()
    out = {}
    for leg, sign in (("long", 1.0), ("short", -1.0)):
        held = sign * values > 0
        out[leg] = float(held[:, marked].sum() / held.sum()) if held.any() else 0.0
    return out


def _pct(x: float, digits: int = 2) -> str:
    return f"{PCT * x:.{digits}f}%"


def summary_table(paths: list[Path_], level: float) -> pd.DataFrame:
    rows = []
    for p in paths:
        m = p.outcome.metrics[level]
        rows.append((
            p.universe, p.form, m["days"], f"{m['gross_sharpe']:.3f}", f"{m['sharpe']:.3f}", _pct(m["ann_gross_return"]), _pct(m["ann_return"]),
            _pct(m["ann_long_pnl"]), _pct(m["ann_short_pnl"]), f"{m['turnover']:.3f}", f"{m['break_even_bps']:.2f}",
            m["missing_returns"], p.result.closed,
        ))
    columns = ["universe", "form", "days", "gross_sharpe", "net_sharpe", "gross_return", "net_return", "long_leg", "short_leg",
               "turnover", "break_even_bps", "missing_returns", "closed"]
    return pd.DataFrame(rows, columns=columns)


def difference_table(paths: list[Path_], level: float, a: str, b: str) -> pd.DataFrame:
    """Universe `a` less universe `b`, for each form both ran: what the move from b to a adds."""
    rows = []
    by = {(p.universe, p.form): p.outcome.metrics[level] for p in paths}
    for form in (RAW, MODEL_B, MODEL_A):
        if (a, form) in by and (b, form) in by:
            x, y = by[a, form], by[b, form]
            rows.append((
                form, f"{x['gross_sharpe'] - y['gross_sharpe']:+.3f}", f"{x['sharpe'] - y['sharpe']:+.3f}",
                _pct(x["ann_gross_return"] - y["ann_gross_return"]), _pct(x["ann_long_pnl"] - y["ann_long_pnl"]),
                _pct(x["ann_short_pnl"] - y["ann_short_pnl"]), f"{x['turnover'] - y['turnover']:+.3f}",
            ))
    return pd.DataFrame(rows, columns=["form", "gross_sharpe", "net_sharpe", "gross_return", "long_leg", "short_leg", "turnover"])


def years_table(paths: list[Path_], level: float, column: str) -> pd.DataFrame:
    frames = {p.label: by_year(p.outcome.daily[level])[column] for p in paths}
    out = pd.DataFrame(frames).map("{:.3f}".format)
    return out.rename_axis("year").reset_index()


def legs_table(paths: list[Path_], suffix: str) -> pd.DataFrame:
    rows = [(p.universe, p.form, _pct(leg_shares(p, suffix)["long"]), _pct(leg_shares(p, suffix)["short"])) for p in paths]
    return pd.DataFrame(rows, columns=["universe", "form", "long_leg_later_delisted", "short_leg_later_delisted"])


def sensitivity_table(paths: list[Path_], names: set[str], loss: float, cfg: BacktestConfig) -> pd.DataFrame:
    rows = []
    for p in paths:
        hit, count = with_delisting_loss(p.result, p.grid, names, loss)
        plain, moved = daily_returns(p.result, FlatCost(0.0)), daily_returns(hit, FlatCost(0.0))
        rows.append((
            p.universe, p.form, p.result.closed, count, f"{sharpe(plain['gross']):.3f}", f"{sharpe(moved['gross']):.3f}",
            _pct(plain["gross"].mean() * TRADING_DAYS), _pct(moved["gross"].mean() * TRADING_DAYS),
            _pct(moved["long_pnl"].mean() * TRADING_DAYS - plain["long_pnl"].mean() * TRADING_DAYS, 3),
            _pct(moved["short_pnl"].mean() * TRADING_DAYS - plain["short_pnl"].mean() * TRADING_DAYS, 3),
        ))
    columns = ["universe", "form", "closed", "with_the_loss", "gross_sharpe", "gross_sharpe_with_loss", "gross_return",
               "gross_return_with_loss", "long_leg_change", "short_leg_change"]
    return pd.DataFrame(rows, columns=columns)


def chart(paths: list[Path_], path: Path) -> None:
    """Cumulative gross return on gross exposure, one panel per form."""
    forms = [f for f in (RAW, MODEL_B, MODEL_A) if any(p.form == f for p in paths)]
    fig = Figure(figsize=(9, 3.6 * len(forms)))
    axes = np.atleast_1d(fig.subplots(len(forms), 1, sharex=True))
    for ax, form in zip(axes, forms, strict=True):
        for p in paths:
            if p.form == form:
                gross = p.outcome.daily[0.0]["gross"]
                ax.plot(gross.index, gross.cumsum() * PCT, lw=1, label=p.universe)
        ax.axhline(0, color="grey", lw=0.5)
        ax.set_ylabel("cumulative gross return, %")
        ax.set_title(f"Reversal on {form if form == RAW else form + ' residuals'}" if form != RAW else "Reversal on returns")
        ax.legend(fontsize=8)
    fig.tight_layout()
    save_figure(fig, path)


@dataclass(frozen=True)
class Inputs:
    """What the measurement reads, every table already cut at the development end."""

    existing: dict[str, pd.DataFrame]     # Alpaca's long tables (statarb.signals.tables.TABLES)
    candidates: pd.DataFrame
    prices: pd.DataFrame                  # this source's
    returns: pd.DataFrame
    listed: pd.DataFrame                  # universe 4, as stored
    last: pd.Timestamp


def measure(
    inputs: Inputs, cfg: BacktestConfig, factors_cfg: dict[str, Any], market: str, ranking: dict[str, Any], suffix: str, close_after: int,
) -> tuple[list[Path_], list[Path_], dict[str, pd.DataFrame]]:
    """Universe 1's paths, the seven on this source, and the three universes built on it."""
    sector_etfs = factors_cfg["sector_etfs"]
    etfs = sorted({*sector_etfs.values(), market})
    calendar = market_calendar(inputs.returns, market)
    pca = PcaModelConfig.from_config(factors_cfg["pca"])
    kinds = variants(cfg)
    sectors = inputs.existing["sectors"]

    first_tables = build_tables(*inputs.existing.values(), market, sector_etfs)
    existing = [
        run_path(EXISTING, MODEL_A, kinds["residual"], first_tables, cfg, sector_etfs, None),
        run_path(EXISTING, RAW, kinds[RAW], first_tables, cfg, sector_etfs, None),
    ]

    universes = {
        CANDIDATES: candidates_universe(inputs.prices, inputs.candidates, calendar, ranking),
        SURVIVORS: survivors_universe(inputs.prices, suffix, calendar, ranking, etfs),
        LISTED: inputs.listed,
    }
    paths = []
    for name, universe in universes.items():
        residuals = pca_residuals_to_date(inputs.returns, universe, calendar, pca)
        tables = tables_for(inputs.returns, inputs.prices, residuals, universe, sectors.iloc[0:0], market, sector_etfs)
        paths.append(run_path(name, RAW, kinds[RAW], tables, cfg, sector_etfs, close_after))
        paths.append(run_path(name, MODEL_B, kinds["residual"], tables, cfg, sector_etfs, close_after))
        if name == CANDIDATES:
            stocks = stocks_to_model(inputs.candidates, inputs.returns)
            keep = inputs.returns[TICKER].isin({*stocks, *etfs})
            model_a = build_residuals(inputs.returns.loc[keep], sectors, inputs.prices.loc[inputs.prices[TICKER].isin({*stocks, *etfs})], stocks, factors_cfg, market)
            tables_a = tables_for(inputs.returns, inputs.prices, model_a, universe, sectors, market, sector_etfs)
            paths.append(run_path(name, MODEL_A, kinds["residual"], tables_a, cfg, sector_etfs, close_after))
    return existing, paths, universes


def report(
    existing: list[Path_], paths: list[Path_], universes: dict[str, pd.DataFrame], inputs: Inputs, cfg: BacktestConfig,
    suffix: str, delisting: dict[str, Any], snapshots: dict[str, str], trials: tuple[int, int],
) -> str:
    level = float(cfg.costs.headline_bps)
    everything = [*existing, *paths]
    head = headline_variant(cfg)
    failed = stopped_after_a_fall(inputs.prices, inputs.last, delisting["bars"], delisting["fall"])
    out = ["# Phase 7: survivorship in the reversal results", ""]
    out += ["Statistics only: no price, volume or return of any symbol on any date.", ""]
    out += [
        "## What ran",
        "",
        (f"- The phase 2 headline's settings: lookback {head.lookback_days}, holding {head.holding_days}, decile "
        f"{cfg.portfolio.decile:g}, fill {cfg.fills.headline}, first signal {cfg.period.start}, through {inputs.last.date()}, the development end"),
        f"- Alpaca snapshot {snapshots['alpaca']}; MarketParquet snapshot {snapshots['marketparquet']}",
        "- `existing`: today's S&P 500 on Alpaca's total returns, the logged universe, rerun over development and not logged again",
        "- `candidates`: today's S&P 500, ranked and priced on MarketParquet",
        "- `survivors`: every listed stock symbol without the delisted suffix, built with look-ahead on purpose",
        "- `listed`: every stock symbol of the day",
        ("- On MarketParquet returns are price returns: no dividends, and a spin-off only where the archive folded it in "
        "(decision record 0009). The engine closes a held name after "
        f"{paths[0].close_after} sessions without a bar; `closed` counts those."),
        "- The raw form is scored from a symbol's first Model B residual on, as phase 2 scores it from its first Model A residual.",
        f"- Trials: the {trials[0]} paths on MarketParquet are new; the repository's logs hold {trials[1]} with them.",
        "",
    ]
    for name, universe in universes.items():
        out += [f"- `{name}`: {universe[TICKER].nunique()} symbols ever members, {universe['rebalanced_on'].nunique()} rankings"]
    out += [""]
    for at in (0.0, level):
        out += [f"## Every path at {at:g} bps one way", "", "Returns are annualised, per dollar of gross exposure.", "", _table(summary_table(everything, at))]
    out += [
        "## What each step adds",
        "",
        f"Differences at {level:g} bps, the second universe taken from the first.",
        "",
        "The source, with its missing dividends (`candidates` less `existing`):",
        "",
        _table(difference_table(everything, level, CANDIDATES, EXISTING)),
        "The change of candidates, from today's S&P 500 to every surviving listed symbol (`survivors` less `candidates`):",
        "",
        _table(difference_table(everything, level, SURVIVORS, CANDIDATES)),
        "Survivorship (`survivors` less `listed`): what leaving out the names that later delisted adds.",
        "",
        _table(difference_table(everything, level, SURVIVORS, LISTED)),
    ]
    out += [
        "## Names that later delisted, by leg",
        "",
        "Of the name-days in each leg of the target book, the share whose symbol carries the delisted suffix.",
        "",
        _table(legs_table(paths, suffix)),
    ]
    out += [
        "## After the last bar",
        "",
        ("A last bar is the last trade, and no result above assumes anything after it. The source has no delisting "
        "returns, and a name that fails loses more after its last trade than its last bar shows. Leaving that out "
        "flatters a long leg in recent losers and understates a short leg in them, so it makes `listed` look better "
        "than it was when the book is long more failing names than it is short, and worse when it is short more."),
        "",
        (f"One stated sensitivity (decision record 0009, rule 10): a held name whose bars stop before {inputs.last.date()}, "
        f"and whose close fell by more than {_pct(delisting['fall'], 0)} over its last {delisting['bars']} bars, takes a further loss of "
        f"{_pct(delisting['loss'], 0)} when the engine closes it. {len(failed)} symbols meet the test. Gross, annualised."),
        "",
        _table(sensitivity_table(paths, failed, delisting["loss"], cfg)),
    ]
    out += ["## By year", "", "Gross Sharpe ratio by year.", "", _table(years_table(everything, level, "gross_sharpe"))]
    out += [f"Net return by year at {level:g} bps, per dollar of gross exposure.", "", _table(years_table(everything, level, "net_return"))]
    out += ["![cumulative gross return by universe](survivorship.png)", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-log", action="store_true", help="do not append to experiments.jsonl")
    args = parser.parse_args(argv)
    root = repo_root()
    data_cfg, mp_cfg, factors_cfg = load_config("data", root), load_config("marketparquet", root), load_config("factors", root)
    cfg = load_backtest_config(root)
    last = pd.Timestamp(load_config("models", root)["period"]["development_end"])
    if last.date() >= mp_cfg["sample"]["end"]:
        raise ValueError(f"the development end, {last.date()}, is not before [sample] end, {mp_cfg['sample']['end']}")
    processed = resolve_path(data_cfg["paths"]["processed"], root)
    derived = resolve_path(mp_cfg["tables"]["derived"], root)
    reports = resolve_path(data_cfg["paths"]["reports"], root)
    inputs = Inputs(
        existing=cut_after(load_long(processed), last),
        candidates=read_parquet(processed / "candidates.parquet"),
        prices=read_cut(derived / "prices.parquet", last),
        returns=read_cut(derived / "returns.parquet", last),
        listed=read_cut(derived / f"universe_{LISTED}.parquet", last),
        last=last,
    )
    existing, paths, universes = measure(
        inputs, cfg, factors_cfg, data_cfg["factors"]["market"], data_cfg["universe"], marketparquet.SUFFIX, mp_cfg["engine"]["close_after_sessions"]
    )
    out_dir = reports / "phase-07"
    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.no_log:
        state = experiments.run_state(root, mp_cfg["source"])
        experiments.append(out_dir / "experiments.jsonl", log_entries(paths, cfg, last, state, dt.datetime.now(dt.UTC)))
    new = {path_id(entry_config(p, 0.0, cfg, last)) for p in paths}
    text = report(
        existing, paths, universes, inputs, cfg, marketparquet.SUFFIX, mp_cfg["survivorship"]["delisting"],
        {"alpaca": data_cfg["source"]["snapshot"], "marketparquet": mp_cfg["source"]["snapshot"]},
        (len(new), len(set(repository_trials(reports)) | new)),
    )
    chart([*existing, *paths], out_dir / "survivorship.png")
    (out_dir / "survivorship.md").write_text(text)
    print(f"wrote {(out_dir / 'survivorship.md').relative_to(root)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
