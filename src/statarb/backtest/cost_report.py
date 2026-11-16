"""Phase 3 report: reports/phase-03/costs.md and its charts."""

from __future__ import annotations

import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from statarb.backtest.costs import COMPONENTS, half_spread
from statarb.backtest.spreads import pooled, window_spread
from statarb.backtest.sweep import SSCORE
from statarb.factors.report import fmt, save_figure, table
from statarb.testing.prices import simulate_ohlc

PCT = 100.0

# What the estimators measure on simulated prices: a true round-trip spread of 2 bps,
# 40 names over a year, with reversal and opening noise added one at a time.
SIM_SPREAD = 0.0002
SIM_DAYS, SIM_NAMES, SIM_VOL, SIM_SEED = 252, 40, 0.015, 2
SIM_REVERSAL = (0.0, -0.05, -0.1, -0.2)
SIM_OPEN_NOISE = (0.0005, 0.001, 0.002)


def pct(x: float, digits: int = 2) -> str:
    return fmt(x * PCT, digits)


def money(x: float) -> str:
    for unit, div in (("bn", 1e9), ("m", 1e6), ("k", 1e3)):
        if x >= div:
            return f"${x / div:g}{unit}"
    return f"${x:g}"


def label(o) -> str:
    return o.name + (", no-trade zone" if o.no_trade else "")


def pick(outcomes, name, book, setting, no_trade=False):
    return next(o for o in outcomes if o.name == name and o.book == book and o.setting == setting and o.no_trade == no_trade)


def capacity_chart(rows: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for name, g in rows.groupby("configuration", sort=False):
        ax.plot(g["book"], g["net_sharpe"], marker="o", lw=1, label=name)
    ax.set_xscale("log")
    ax.axhline(0, color="grey", lw=0.5)
    ax.set_xlabel("capital, US dollars (log scale)")
    ax.set_ylabel("net Sharpe")
    ax.set_title("Net Sharpe by book size, headline cost model")
    ax.legend(fontsize=8)
    fig.tight_layout()
    save_figure(fig, path)
    plt.close(fig)


def pnl_chart(series: dict[str, pd.Series], title: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for name, s in series.items():
        ax.plot(s.index, s.cumsum() * PCT, lw=1, label=name)
    ax.axhline(0, color="grey", lw=0.5)
    ax.set_ylabel("cumulative net return on capital, %")
    ax.set_title(title)
    ax.legend(fontsize=8)
    fig.tight_layout()
    save_figure(fig, path)
    plt.close(fig)


def simulated_estimates() -> pd.DataFrame:
    """Each estimator's pooled round-trip spread (bps) on simulated prices with a known 2 bps spread."""
    cases = [("none", {})]
    cases += [(f"reversal {-r:g}", {"rho": r}) for r in SIM_REVERSAL if r]
    cases += [(f"open noise {n * 1e4:g} bps", {"open_noise": n}) for n in SIM_OPEN_NOISE]
    rows = []
    for name, kw in cases:
        prices = simulate_ohlc(SIM_DAYS, SIM_NAMES, SIM_SPREAD, SIM_VOL, seed=SIM_SEED, **kw)
        rows.append({"added to the prices": name, **{m: fmt(pooled(window_spread(*prices, m)) * 1e4, 1) for m in ("edge", "ar", "cs")}})
    return pd.DataFrame(rows)


def _yearly_median(panel: np.ndarray, lab) -> pd.DataFrame:
    keep = lab.tables.dates >= pd.Timestamp(lab.cfg.period.start)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        daily = np.nanmedian(panel, axis=1) if panel.ndim == 2 else panel
    return pd.Series(daily, index=lab.tables.dates.year)[keep].groupby(level=0).median()


def spread_diagnostics(lab) -> pd.DataFrame:
    """Median pooled round-trip spread by year (bps) for the smallest and largest stock quintiles and the ETFs."""
    c = lab.costs
    groups = lab.ccfg.spread.size_groups
    cols = {}
    for m, panel in c.spread.items():
        for g, name in ((0, "smallest"), (groups - 1, "largest"), (groups, "ETFs")):
            cols[f"{m} {name}"] = _yearly_median(np.where(c.groups == g, panel, np.nan) * 1e4, lab)
    return pd.DataFrame(cols)


def market_estimates(lab) -> pd.DataFrame:
    """The market ETF's own trailing-year estimate (signed, round trip, bps), median by year."""
    j = lab.tables.tickers.index(lab.tables.market)
    return pd.DataFrame({m: _yearly_median(v[:, j] * 1e4, lab) for m, v in lab.costs.name_spread.items()})


def headline_half_spread(lab, spread: str | float) -> pd.Series:
    """Median one-way half-spread charged to members by year, after the half-tick floor (bps)."""
    hs = half_spread(lab.costs, spread, lab.ccfg.spread.half_tick_floor)[:, : len(lab.tables.stocks)]
    return _yearly_median(np.where(lab.tables.members, hs, np.nan) * 1e4, lab)


def binding(m: dict) -> str:
    return max(COMPONENTS, key=lambda c: m[f"{c}_bps_per_dollar"])


def write_report(
    lab,
    configs: list,
    settings: list,
    outcomes: list,
    verdict: pd.DataFrame,
    break_even: float | None,
    log: list[dict],
    out_dir: Path,
) -> str:
    """The report from the runner's results: `configs` are (name, variant) pairs, `settings` the cost
    settings with the headline first, `break_even` phase 2's for the first configuration, if logged there."""
    cc = lab.ccfg
    head = settings[0]
    books = list(cc.run.book_sizes)
    names = [n for n, _ in configs]
    decile = [n for n, v in configs if v.signal != SSCORE]
    first = names[0]
    hb = cc.run.headline_book
    sched = cc.schedule(head.commission)
    start = lab.tables.dates[lab.start].date()
    end = lab.tables.dates[-1].date()
    out: list[str] = []
    add = out.append

    add("# Phase 3: cost realism\n")
    add(
        "Generated by `uv run python -m statarb.backtest.cost_run` from `config/costs.toml` and `config/backtest.toml`. "
        f"Signals, holding rules and the s-score rule are phase 2's, unchanged; fills at `{cc.run.fill}`. Signals from {start} to {end}.\n"
    )
    add("Configurations:\n")
    for name, v in configs:
        add(f"- **{name}:** {v.label()}.")
    add("")
    add(
        "**Returns are per dollar of capital**, with idle capital earning nothing. Weights are fractions of capital: a "
        "decile book's gross exposure is the capital, less where slices of the *k*-day book offset each other; the "
        "no-trade zone deploys only what passes its rule; the s-score book deploys whatever its open positions and hedges add up to. "
        "Phase 2 reported returns per dollar of gross, so its figures for the same configuration differ where the "
        "capital deployed is not 1 (the `capital` column of the no-trade table).\n"
    )
    add("Headline cost model:\n")
    add(
        f"- **Spread:** {head.spread:g} bps one-way, at least half a cent over the previous close; an assumption, not a measurement "
        "(decision record 0005 and the spread section below)."
    )
    add(
        f"- **Impact:** {head.impact:g} × σ × √(dollars traded / average daily dollar volume), σ the {cc.impact.volatility_window_days}-day "
        f"volatility of daily returns and volume averaged over {cc.impact.volume_window_days} days, both up to the day before the fill."
    )
    add(
        f"- **Commission:** `{sched.name}`: ${sched.per_share:g} a share, at least ${sched.min_per_order:.2f} and at most "
        f"{sched.max_fraction:.1%} of the order's value; one order per name per day. Read from {cc.commission.source} on {cc.commission.read_on}."
    )
    add(
        f"- **Borrow:** {cc.borrow.general_annual:.1%} a year on short notional; {cc.borrow.hard_annual:.0%} for stocks whose trailing "
        f"volatility is in the top {cc.borrow.hard_quantile:.0%} of stocks that day (a proxy for hard to borrow)."
    )
    add("")

    # Net results ------------------------------------------------------------------
    add("## Net results by book size\n")
    add("Headline cost model. Costs and returns in % a year of capital.\n")
    rows = []
    for name in names:
        for book in books:
            m = pick(outcomes, name, book, head).metrics
            rows.append(
                {
                    "configuration": name,
                    "capital": money(book),
                    "gross %": pct(m["ann_gross_return"]),
                    "spread %": pct(m["ann_cost_spread"]),
                    "impact %": pct(m["ann_cost_impact"]),
                    "commission %": pct(m["ann_cost_commission"]),
                    "borrow %": pct(m["ann_borrow"]),
                    "net %": pct(m["ann_return"]),
                    "net Sharpe": fmt(m["sharpe"], 2),
                    "t": fmt(m["t_stat"], 2),
                    "turnover": fmt(m["turnover"], 2),
                }
            )
    add(table(pd.DataFrame(rows)) + "\n")

    cap_rows = pd.DataFrame(
        [{"configuration": label(o), "book": o.book, "net_sharpe": o.metrics["sharpe"]} for o in outcomes if o.setting == head]
    )
    capacity_chart(cap_rows, out_dir / "capacity.png")
    add("![net Sharpe by book size](capacity.png)\n")
    add("Where net Sharpe changes sign, by configuration:\n")
    for name, g in cap_rows.groupby("configuration", sort=False):
        pos = [money(b) for b, s in zip(g["book"], g["net_sharpe"], strict=True) if s > 0]
        neg = [money(b) for b, s in zip(g["book"], g["net_sharpe"], strict=True) if s <= 0]
        if not pos:
            add(f"- **{name}:** below zero at every book size.")
        elif not neg:
            add(f"- **{name}:** above zero at every book size.")
        else:
            add(f"- **{name}:** above zero at {', '.join(pos)}; at or below zero at {', '.join(neg)}.")
    add("")

    # Cost per dollar ----------------------------------------------------------------
    add("## Cost per dollar traded\n")
    add(
        "Headline cost model, bps one-way per dollar traded. Commission per dollar falls with order size until the "
        "per-share rate takes over; impact rises with it. `binding` names the largest component.\n"
    )
    rows = []
    for name in names:
        for book in books:
            m = pick(outcomes, name, book, head).metrics
            rows.append(
                {
                    "configuration": name,
                    "capital": money(book),
                    **{c: fmt(m[f"{c}_bps_per_dollar"], 2) for c in COMPONENTS},
                    "total": fmt(sum(m[f"{c}_bps_per_dollar"] for c in COMPONENTS), 2),
                    "binding": binding(m),
                }
            )
    add(table(pd.DataFrame(rows)) + "\n")
    base = pick(outcomes, first, hb, head)
    be = break_even
    if be is not None:
        add(
            f"Phase 2's break-even for the {first} was {be:.2f} bps one-way per dollar of gross under its flat cost. At {money(hb)} the {first} "
            f"deploys {base.metrics['mean_exposure']:.2f} of its capital on average and holds a median of {base.metrics['median_names']:.0f} names.\n"
        )

    # Spread -------------------------------------------------------------------------------
    add("## Spread\n")
    add(
        "**What the estimators measure.** Each reads negative serial covariance of prices as bid-ask bounce. On simulated prices "
        f"with a true round-trip spread of {SIM_SPREAD * 1e4:g} bps ({SIM_NAMES} names, {SIM_DAYS} days, daily volatility {SIM_VOL:.1%}), "
        "pooled round-trip estimate in bps as reversal (the share of each day's move that reverses the next day) or noise in the "
        "opening print is added. The true spread is the same in every row.\n"
    )
    add(table(simulated_estimates()) + "\n")
    add(
        "**On the real data.** Pooled across stocks in the same size quintile over a trailing year: median round-trip spread in bps by "
        "year. The ETF group includes the market ETF, whose quoted spread is a fraction of a basis point.\n"
    )
    diag = spread_diagnostics(lab).round(1)
    diag.insert(0, "year", diag.index)
    add(table(diag) + "\n")
    mkt = market_estimates(lab).round(1)
    mkt.insert(0, "year", mkt.index)
    add(f"The market ETF ({lab.tables.market}) alone, its own trailing-year estimate, median by year (bps, round trip, signed):\n")
    add(table(mkt) + "\n")
    neg = {m: float((v[np.isfinite(v)] < 0).mean()) for m, v in lab.costs.name_spread.items()}
    add("Share of per-name, per-day estimates that are negative: " + ", ".join(f"{m} {v:.0%}" for m, v in neg.items()) + ".\n")
    hs = headline_half_spread(lab, head.spread).round(2)
    add("Headline half-spread charged to members after the half-tick floor, median by year (bps): " + ", ".join(f"{y} {v}" for y, v in hs.items()) + ".\n")

    # Sensitivity -----------------------------------------------------------------------------
    add("## Sensitivity\n")
    add("Net Sharpe by book size when one part of the headline cost model changes. The first row of each block is the headline.\n")
    for name in names:
        rows = []
        for setting in settings:
            row = {"cost model": setting.label()}
            for book in books:
                row[money(book)] = fmt(pick(outcomes, name, book, setting).metrics["sharpe"], 2)
            rows.append(row)
        add(f"**{name}**\n")
        add(table(pd.DataFrame(rows)) + "\n")

    # No-trade zone ------------------------------------------------------------------------------
    add("## No-trade zone\n")
    add(
        "Decile configurations with the no-trade rule, headline cost model. A name opens only if its expected move over the "
        "holding period exceeds the estimated round-trip cost, and is resized only if the move exceeds the one-way cost of the "
        "trade; exits always trade. The expected move is the signal times a slope from a trailing pooled regression of the "
        "move over the next *k* days on the signal "
        f"({cc.no_trade.calibration_window_days} signal dates, outcomes known by the decision date). `capital` is the share "
        "of capital deployed on average; `imbalance` the mean of |longs − shorts| / gross.\n"
    )
    rows = []
    for name in decile:
        for book in books:
            for nt in (False, True):
                m = pick(outcomes, name, book, head, nt).metrics
                rows.append(
                    {
                        "configuration": name + (", no-trade" if nt else ""),
                        "capital $": money(book),
                        "capital": fmt(m["mean_exposure"], 2),
                        "median names": fmt(m["median_names"], 0),
                        "turnover": fmt(m["turnover"], 2),
                        "imbalance": fmt(m["net_dollar_imbalance"], 2),
                        "gross Sharpe": fmt(m["gross_sharpe"], 2),
                        "net %": pct(m["ann_return"]),
                        "net Sharpe": fmt(m["sharpe"], 2),
                        "t": fmt(m["t_stat"], 2),
                    }
                )
    add(table(pd.DataFrame(rows)) + "\n")
    series = {money(b): pick(outcomes, first, b, head).daily["net"] for b in books}
    series[f"{money(hb)}, no-trade zone"] = pick(outcomes, first, hb, head, True).daily["net"]
    pnl_chart(series, f"{first[0].upper()}{first[1:]}, headline cost model", out_dir / "baseline_pnl.png")
    add(f"![{first} net P&L](baseline_pnl.png)\n")

    # Borrow ------------------------------------------------------------------------------------
    add("## Borrow\n")
    rows = []
    for name in names:
        m = pick(outcomes, name, hb, head).metrics
        rows.append(
            {
                "configuration": name,
                "short notional flagged hard to borrow": pct(m["hard_short_share"], 1) + "%",
                "borrow % a year": pct(m["ann_borrow"]),
                "of which hard-to-borrow extra": pct(m["ann_borrow_hard_extra"]),
            }
        )
    add(f"At {money(hb)}; borrow does not depend on book size.\n")
    add(table(pd.DataFrame(rows)) + "\n")

    # Judging --------------------------------------------------------------------------------------
    add("## Judging the result\n")
    trials = sorted(set(verdict["trials"])) if len(verdict) else [0]
    add(
        "The bar from the phase 3 brief: a t-statistic of at least 2 for mean net return and a deflated Sharpe probability of "
        f"at least 0.95. Trials are the distinct position paths in the repository's experiment logs up to this phase, this run's "
        f"included: {', '.join(str(t) for t in trials)}. A no-trade path is one trial per decile configuration, whatever the book size. "
        "The benchmark is the Sharpe the best of that many paths would reach by chance with no edge, from the variance of their gross "
        "Sharpes, with each no-trade path's at the book size in question; the net Sharpe is judged against it. Net Sharpes are not used "
        "for the variance: they differ across paths mainly through turnover times cost.\n"
    )
    v = verdict.copy()
    v["capital"] = v["book"].map(money)
    v = v[["configuration", "capital", "net_sharpe", "t_stat", "benchmark_sharpe", "deflated_probability", "clears"]]
    v = v.assign(
        net_sharpe=v["net_sharpe"].map(lambda x: fmt(x, 2)),
        t_stat=v["t_stat"].map(lambda x: fmt(x, 2)),
        benchmark_sharpe=v["benchmark_sharpe"].map(lambda x: fmt(x, 2)),
        deflated_probability=v["deflated_probability"].map(lambda x: fmt(x, 3)),
        clears=v["clears"].map(lambda x: "yes" if x else "no"),
    )
    v.columns = ["configuration", "capital", "net Sharpe", "t", "benchmark Sharpe", "deflated probability", "clears the bar"]
    add(table(v) + "\n")
    add(f"{int(verdict['clears'].sum()) if len(verdict) else 0} of {len(verdict)} configuration and book-size pairs clear the bar.\n")

    # Log ---------------------------------------------------------------------------------------------
    add("## Configurations tried\n")
    ids = {e["config_id"] for e in log}
    add(
        f"This run evaluated {len(outcomes)} configuration, book size and cost-model combinations. `experiments.jsonl` holds "
        f"{len(log)} entries, {len(ids)} distinct. Cost-model settings and book sizes are not counted as trials (see above); every one is logged. "
        "The s-score rule appears as `s-score`.\n"
    )

    text = "\n".join(out).rstrip() + "\n"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "costs.md").write_text(text)
    return text
