"""Phase 2 report: reports/phase-02/backtest.md and its charts.

Statistics only: no ticker's price, volume or return on a date. Charts are
drawn with matplotlib's object interface, so no figure lives in global state,
and saved with no date or software metadata, so a rerun writes the same bytes.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from statarb.backtest.config import BacktestConfig
from statarb.backtest.engine import TRADING_DAYS
from statarb.backtest.metrics import by_year, deflated_sharpe, sharpe
from statarb.backtest.sweep import SSCORE_VARIANT, Variant, headline_variant, record
from statarb.backtest.trials import path_id, repository_trials
from statarb.data.schema import DATE, FORMER_GICS_SECTORS, GICS_SECTORS, TICKER
from statarb.factors.model import sector_etf_panel
from statarb.factors.report import fmt, save_figure, size_bucket, table
from statarb.signals.tables import Tables

PCT = 100.0


def pct(x: float, digits: int = 1) -> str:
    return fmt(x * PCT, digits)


def find(outcomes, variant, fill):
    return next(o for o in outcomes if o.variant == variant and o.fill == fill)


def cumulative_chart(o, levels, path: Path) -> None:
    fig = Figure(figsize=(9, 4.5))
    ax = fig.subplots()
    gross = o.daily[levels[0]]["gross"]
    ax.plot(gross.index, gross.cumsum() * PCT, color="black", lw=1.2, label="gross")
    for level in levels:
        net = o.daily[level]["net"]
        ax.plot(net.index, net.cumsum() * PCT, lw=0.9, label=f"net, {level:g} bps")
    ax.axhline(0, color="grey", lw=0.5)
    ax.set_ylabel("cumulative return on gross, %")
    ax.set_title(f"Headline: {o.variant.label()}, fill {o.fill}")
    ax.legend(fontsize=8)
    fig.tight_layout()
    save_figure(fig, path)


def rolling_chart(series: dict[str, pd.Series], path: Path) -> None:
    fig = Figure(figsize=(9, 4))
    ax = fig.subplots()
    for label, s in series.items():
        r = s.rolling(TRADING_DAYS, min_periods=TRADING_DAYS)
        ax.plot(s.index, r.mean() / r.std() * np.sqrt(TRADING_DAYS), lw=1, label=label)
    ax.axhline(0, color="grey", lw=0.5)
    ax.set_ylabel("rolling 1-year gross Sharpe")
    ax.legend(fontsize=8)
    fig.tight_layout()
    save_figure(fig, path)


def sector_attribution(inp: Tables, cfg: BacktestConfig, o) -> pd.Series:
    """Annualised gross P&L per dollar of gross, by the GICS sector of each stock on each day."""
    res = o.result
    labels = {s: s for s in GICS_SECTORS | FORMER_GICS_SECTORS}
    sector = sector_etf_panel(inp.sectors, inp.stocks, inp.dates, labels)
    sector = np.hstack([sector, np.full((len(inp.dates), len(inp.hedges)), "ETF hedges", dtype=object)])
    base = np.where(res.gross_held > 0, res.gross_held, res.gross_after)
    keep = (base > 0) & (inp.dates >= pd.Timestamp(cfg.period.start))
    scaled = res.pnl[keep] / base[keep, None]
    frame = pd.DataFrame({"sector": sector[keep].ravel(), "pnl": scaled.ravel()})
    frame["sector"] = frame["sector"].fillna("unknown")
    days = int(keep.sum())
    out = frame.groupby("sector")["pnl"].sum() / days * TRADING_DAYS
    return out.sort_values(ascending=False)


def _held_before(res) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Holdings filled at s-1, the gross that earned P&L at s, and which days count."""
    prev = np.vstack([np.zeros((1, res.holdings.shape[1])), res.holdings[:-1]])
    base = np.where(res.gross_held > 0, res.gross_held, res.gross_after)
    return prev, base, base > 0


def size_attribution(inp: Tables, cfg: BacktestConfig, o) -> pd.Series:
    """Annualised gross P&L per dollar of gross by size quintile on the day before the P&L."""
    res = o.result
    n = len(inp.stocks)
    _, base, keep = _held_before(res)
    keep &= inp.dates >= pd.Timestamp(cfg.period.start)
    t_idx, s_idx = np.nonzero(inp.members)
    rows = pd.DataFrame({DATE: inp.dates[t_idx], TICKER: np.asarray(inp.stocks, dtype=object)[s_idx]})
    rows["bucket"] = size_bucket(rows, inp.prices, inp.dates, 5).to_numpy()
    bucket = np.full((len(inp.dates), n), np.nan)
    bucket[t_idx, s_idx] = rows["bucket"].to_numpy()
    formed = np.vstack([np.full((1, n), np.nan), bucket[:-1]])      # bucket on the day before the P&L
    scaled = res.pnl[:, :n] / np.where(keep, base, np.inf)[:, None]
    frame = pd.DataFrame({"bucket": formed[keep].ravel(), "pnl": scaled[keep].ravel()}).dropna()
    return frame.groupby("bucket")["pnl"].sum() / int(keep.sum()) * TRADING_DAYS


def factor_exposure(inp: Tables, cfg: BacktestConfig, o) -> dict[str, float]:
    """Split close-to-close P&L into Model A residual and fitted parts; net market beta of the book."""
    res = o.result
    n = len(inp.stocks)
    prev, base, keep = _held_before(res)
    keep &= inp.dates >= pd.Timestamp(cfg.period.start)
    resid = np.nan_to_num(inp.residual.to_numpy())
    total = res.pnl[:, :n].sum(axis=1)[keep] / base[keep]
    residual = (prev[:, :n] * resid).sum(axis=1)[keep] / base[keep]
    fitted = total - residual
    beta = np.nansum(prev[:, :n] * inp.beta_market.to_numpy(), axis=1)[keep] / base[keep]
    s = pd.Series
    return {
        "total_sharpe": sharpe(s(total)),
        "total_ann": float(total.mean() * TRADING_DAYS),
        "residual_sharpe": sharpe(s(residual)),
        "residual_ann": float(residual.mean() * TRADING_DAYS),
        "fitted_ann": float(fitted.mean() * TRADING_DAYS),
        "fitted_vol": float(fitted.std() * np.sqrt(TRADING_DAYS)),
        "beta_mean": float(beta.mean()),
        "beta_sd": float(beta.std()),
    }


def write_report(tables: Tables, cfg: BacktestConfig, outcomes, placebo: pd.DataFrame, reports: Path, out_dir: Path) -> str:
    levels = list(cfg.costs.levels_bps)
    hc, hf = cfg.costs.headline_bps, cfg.fills.headline
    head = headline_variant(cfg)
    o = find(outcomes, head, hf)
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Phase 2: baseline backtest",
        "",
        "Generated by `uv run python -m statarb.backtest.run` from `config/backtest.toml`. Returns are per dollar of",
        "gross exposure, long-short, with no cash rate. Turnover is dollars traded (buys plus sells) per dollar of",
        "gross per day, so replacing the whole book is 2.0. Costs are one-way per dollar traded; the `close_t` fill",
        f"adds {cfg.fills.close_t_slippage_bps:g} bps of slippage to every cost level. Borrow is {pct(cfg.costs.borrow_annual)}% a year on",
        f"short notional. Signals from {cfg.period.start} to {tables.dates[-1].date()}.",
        "",
        f"Headline: **{head.label()}**, fill **{hf}**, cost **{hc:g} bps**.",
        "",
    ]

    # Headline by cost level.
    rows = []
    for level in levels:
        m = o.metrics[level]
        rows.append(
            {
                "cost bps": f"{level:g}",
                "ann. return %": pct(m["ann_return"], 2),
                "ann. vol %": pct(m["ann_vol"], 2),
                "Sharpe": fmt(m["sharpe"], 2),
                "max drawdown %": pct(m["max_drawdown"], 1),
                "turnover": fmt(m["turnover"], 2),
                "day hit rate %": pct(m["day_hit_rate"]),
            }
        )
    m0 = o.metrics[levels[0]]
    cumulative_chart(o, levels, out_dir / "headline_pnl.png")
    lines += [
        "## Headline",
        "",
        table(pd.DataFrame(rows)),
        "",
        f"- Gross Sharpe {fmt(m0['gross_sharpe'], 2)}, gross return {pct(m0['ann_gross_return'], 2)}% a year on gross.",
        f"- Break-even cost: **{fmt(m0['break_even_bps'], 2)} bps** one-way, against an assumed retail cost of {cfg.costs.retail_bps:g} bps.",
        f"- Position hit rate (held position-days with positive gross P&L): {pct(m0['position_hit_rate'], 2)}%.",
        f"- Long side {pct(m0['ann_long_pnl'], 2)}% a year, short side {pct(m0['ann_short_pnl'], 2)}%, gross, per dollar of gross.",
        "",
        "![headline P&L](headline_pnl.png)",
        "",
    ]

    # Fill timing.
    rows = []
    for fill in cfg.fills.timings:
        f = find(outcomes, head, fill)
        rows.append(
            {
                "fill": fill,
                "gross Sharpe": fmt(f.metrics[levels[0]]["gross_sharpe"], 2),
                "ann. gross %": pct(f.metrics[levels[0]]["ann_gross_return"], 2),
                "break-even bps": fmt(f.metrics[levels[0]]["break_even_bps"], 2),
                **{f"net Sharpe {lv:g}": fmt(f.metrics[lv]["sharpe"], 2) for lv in levels},
            }
        )
    lines += ["## Fill timing", "", "Headline signal and holding period. `close_t` includes its slippage in every net column.", "", table(pd.DataFrame(rows)), ""]

    # Holding period.
    rows = []
    for k in cfg.sweep.holding_days:
        v = Variant(head.signal, head.source, head.lookback_days, head.vol_scaled, k)
        f = find(outcomes, v, hf)
        rows.append(
            {
                "k": k,
                "turnover": fmt(f.metrics[levels[0]]["turnover"], 2),
                "gross Sharpe": fmt(f.metrics[levels[0]]["gross_sharpe"], 2),
                "break-even bps": fmt(f.metrics[levels[0]]["break_even_bps"], 2),
                **{f"net Sharpe {lv:g}": fmt(f.metrics[lv]["sharpe"], 2) for lv in levels},
            }
        )
    lines += ["## Holding period", "", f"Headline signal, fill {hf}.", "", table(pd.DataFrame(rows)), ""]

    # All variants at the headline fill.
    rows = []
    for f in outcomes:
        if f.fill != hf:
            continue
        m = f.metrics
        rows.append(
            {
                "configuration": f.variant.label(),
                "gross Sharpe": fmt(m[levels[0]]["gross_sharpe"], 2),
                "ann. gross %": pct(m[levels[0]]["ann_gross_return"], 2),
                "turnover": fmt(m[levels[0]]["turnover"], 2),
                "break-even bps": fmt(m[levels[0]]["break_even_bps"], 2),
                f"net Sharpe {hc:g}": fmt(m[hc]["sharpe"], 2),
            }
        )
    lines += ["## All configurations", "", f"Fill {hf}. The raw rows are the control; the s-score row is the Avellaneda and Lee rule.", "", table(pd.DataFrame(rows)), ""]

    # s-score detail.
    s_out = find(outcomes, SSCORE_VARIANT, hf)
    res = s_out.result
    n_stock = len(tables.stocks)
    active = res.dates >= pd.Timestamp(cfg.period.start)
    open_positions = (res.holdings[active, :n_stock] != 0).sum(axis=1)
    hedge_share = np.abs(res.holdings[active, n_stock:]).sum(axis=1) / np.maximum(np.abs(res.holdings[active]).sum(axis=1), 1e-12)
    rows = []
    for fill in cfg.fills.timings:
        f = find(outcomes, s_out.variant, fill)
        rows.append({"fill": fill, "gross Sharpe": fmt(f.metrics[levels[0]]["gross_sharpe"], 2), "break-even bps": fmt(f.metrics[levels[0]]["break_even_bps"], 2), **{f"net Sharpe {lv:g}": fmt(f.metrics[lv]["sharpe"], 2) for lv in levels}})
    lines += [
        "## s-score rule",
        "",
        f"Open stock positions per day: median {np.median(open_positions):.0f}, range {open_positions.min()} to {open_positions.max()}.",
        f"ETF and SPY hedges are {pct(float(np.median(hedge_share)))}% of gross on the median day. Avellaneda and Lee fill at the close of",
        "the signal day with 5 bps, which is the `close_t` row at 0 bps (5 bps of slippage).",
        "",
        table(pd.DataFrame(rows)),
        "",
    ]

    # Over time.
    yr = by_year(o.daily[hc])
    yr0 = by_year(o.daily[levels[0]])
    yt = pd.DataFrame(
        {
            "year": yr.index,
            "days": yr["days"].to_numpy(),
            "gross %": [pct(x, 2) for x in yr0["gross_return"]],
            "gross Sharpe": [fmt(x, 2) for x in yr0["gross_sharpe"]],
            f"net % at {hc:g} bps": [pct(x, 2) for x in yr["net_return"]],
            "turnover": [fmt(x, 2) for x in yr["turnover"]],
        }
    )
    raw = Variant("raw", "raw", head.lookback_days, head.vol_scaled, head.holding_days)
    rolling_chart(
        {
            head.label(): o.daily[levels[0]]["gross"],
            raw.label(): find(outcomes, raw, hf).daily[levels[0]]["gross"],
            "s-score": s_out.daily[levels[0]]["gross"],
        },
        out_dir / "rolling_sharpe.png",
    )
    lines += ["## By year", "", f"Headline, fill {hf}.", "", table(yt), "", "![rolling Sharpe](rolling_sharpe.png)", ""]

    # By sector.
    sec = sector_attribution(tables, cfg, o)
    lines += [
        "## By sector",
        "",
        "Headline, gross, annualised P&L per dollar of total gross, by each stock's sector on the day.",
        "",
        table(pd.DataFrame({"sector": sec.index, "ann. gross %": [pct(x, 2) for x in sec]})),
        "",
    ]

    # By size.
    size = size_attribution(tables, cfg, o)
    lines += [
        "## By size",
        "",
        "Headline, gross, annualised P&L per dollar of total gross, by quintile of trailing 60-day median dollar volume among",
        "universe members on the day the position was formed (5 = most traded).",
        "",
        table(pd.DataFrame({"quintile": size.index.astype(int), "ann. gross %": [pct(x, 2) for x in size]})),
        "",
    ]

    # Factor exposure.
    fx = factor_exposure(tables, cfg, find(outcomes, head, "close_t1"))
    lines += [
        "## Factor exposure",
        "",
        "Headline book with the close-of-*t+1* fill, where P&L is close to close and splits into the Model A residual",
        "and the fitted market and sector part. The book is dollar neutral but not beta or sector neutral.",
        "",
        f"- Gross Sharpe on total returns {fmt(fx['total_sharpe'], 2)} ({pct(fx['total_ann'], 2)}% a year); on residual returns alone",
        f"  {fmt(fx['residual_sharpe'], 2)} ({pct(fx['residual_ann'], 2)}% a year). The fitted part contributes {pct(fx['fitted_ann'], 2)}% a year",
        f"  with an annualised volatility of {pct(fx['fitted_vol'], 2)}%.",
        f"- Net market beta of the book per dollar of gross: mean {fmt(fx['beta_mean'], 3)}, standard deviation {fmt(fx['beta_sd'], 3)}.",
        "",
    ]

    # Fill timing across every decile configuration.
    rows = []
    for group, pick in [("residual decile", lambda v: v.source == "residual"), ("raw decile", lambda v: v.source == "raw"), ("s-score", lambda v: v == SSCORE_VARIANT)]:
        row = {"configurations": group}
        for fill in cfg.fills.timings:
            vals = [f.metrics[levels[0]]["gross_sharpe"] for f in outcomes if f.fill == fill and pick(f.variant)]
            row[f"median gross Sharpe, {fill}"] = fmt(float(np.median(vals)), 2)
        rows.append(row)
    lines += ["## Fill timing across configurations", "", table(pd.DataFrame(rows)), ""]

    # Placebo.
    pm, ps = placebo["ann_gross_return"].mean(), placebo["ann_gross_return"].std(ddof=1)
    t = pm / (ps / np.sqrt(len(placebo))) if len(placebo) > 1 and ps > 0 else float("nan")
    lines += [
        "## Placebo",
        "",
        f"Headline configuration with the signal shuffled among members each day, {len(placebo)} seeds from {cfg.run.seed}, gross:",
        f"mean {pct(pm, 2)}% a year (standard error {pct(ps / np.sqrt(len(placebo)), 2)}, t {fmt(t, 1)}), mean gross Sharpe {fmt(placebo['gross_sharpe'].mean(), 2)};",
        f"the real signal earns {pct(m0['ann_gross_return'], 2)}% (Sharpe {fmt(m0['gross_sharpe'], 2)}).",
        "",
    ]

    # Multiple testing. Deflate the gross Sharpe: across configurations the spread of
    # net Sharpe is mostly the spread of costs, which is not selection noise. The trials
    # are every distinct position path in the repository's experiment logs, with this
    # sweep's paths added in case it was run without logging.
    gross = {(f.variant, f.fill): f.daily[levels[0]]["gross"] for f in outcomes}
    trials = repository_trials(reports)
    for f in outcomes:
        g = gross[(f.variant, f.fill)]
        trials[path_id(record(f.variant, f.fill, levels[0], cfg))] = float(g.mean() / g.std())
    gbest_key = max(gross, key=lambda k: sharpe(gross[k]))
    gbest = deflated_sharpe(gross[gbest_key], len(trials), np.array(list(trials.values())))
    nets = {(f.variant, f.fill): f.daily[hc]["net"] for f in outcomes}
    best_key = max(nets, key=lambda k: sharpe(nets[k]))
    best_net = nets[best_key]
    years = len(best_net) / TRADING_DAYS
    lines += [
        "## Configurations tried",
        "",
        f"This sweep ran {len(outcomes)} configurations (signal, holding period and fill), each at {len(levels)} cost levels.",
        f"The repository's experiment logs hold {len(trials)} distinct position paths, this sweep's included; each is a trial.",
        "",
        f"- Best gross Sharpe: {gbest_key[0].label()}, fill {gbest_key[1]}: {fmt(gbest['sharpe'], 2)}. The best of {gbest['trials']}",
        f"  trials would be expected to reach {fmt(gbest['benchmark_sharpe'], 2)} by chance if none had an edge (Bailey and",
        f"  López de Prado); deflated Sharpe probability {fmt(gbest['deflated_sharpe_probability'], 3)}.",
        f"- Best net Sharpe at {hc:g} bps: {best_key[0].label()}, fill {best_key[1]}: {fmt(sharpe(best_net), 2)}, with a t-statistic of",
        f"  {fmt(sharpe(best_net) * np.sqrt(years), 2)} over {fmt(years, 1)} years before any allowance for selection.",
        "",
        "The benchmark treats trials as independent. Many are close variants of each other, so the effective",
        "number is smaller and the benchmark somewhat too high.",
        "",
    ]
    text = "\n".join(lines)
    (out_dir / "backtest.md").write_text(text)
    return text
