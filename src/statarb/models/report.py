"""Phase 5 report: reports/phase-05/ml.md and its charts.

Statistics only, no ticker's return on a date. Built from the development
runner's results in memory. Imports nothing from the runner, which runs as
`__main__` (`statarb.portfolio.paths` says why).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from statarb.backtest.cost_report import money, pct
from statarb.backtest.metrics import by_year
from statarb.factors.report import fmt, save_figure, table
from statarb.models.config import RULES

DECILE, ZONE, OPTIMISER = RULES


def _mean_t(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    """Rows by forecast, a column per value of `column`, each cell the mean IC with its t-statistic."""
    cells = frame.assign(cell=[f"{fmt(m, 4)} ({fmt(t, 1)})" for m, t in zip(frame["mean"], frame["t_stat"], strict=True)])
    order = list(dict.fromkeys(frame["forecast"]))
    wide = cells.pivot(index="forecast", columns=column, values="cell").reindex(order)
    wide.columns = [str(c) for c in wide.columns]
    return wide.reset_index().fillna("")


def _ic_chart(by_year: pd.DataFrame, path: Path) -> None:
    order = list(dict.fromkeys(by_year["forecast"]))
    years = sorted(by_year["year"].unique())
    fig = Figure(figsize=(9, 4))
    ax = fig.subplots()
    width = 0.8 / len(order)
    for k, f in enumerate(order):
        g = by_year.loc[by_year["forecast"] == f].set_index("year").reindex(years)
        ax.bar(np.arange(len(years)) + (k - (len(order) - 1) / 2) * width, g["mean"], width, label=f)
    ax.axhline(0, color="grey", lw=0.5)
    ax.set_xticks(np.arange(len(years)), [str(y) for y in years])
    ax.set_ylabel("mean daily rank IC, 1-day target")
    ax.set_title("Out-of-sample IC by year")
    ax.legend(fontsize=8)
    fig.tight_layout()
    save_figure(fig, path)


def _importance_chart(imp: pd.DataFrame, horizon: int, path: Path) -> None:
    d = imp.sort_values(["mean_abs_shap", "feature"], ascending=[True, False])
    fig = Figure(figsize=(7, 0.3 * len(d) + 1.2))
    ax = fig.subplots()
    ax.barh(d["feature"], d["mean_abs_shap"])
    ax.set_xlabel("mean |SHAP|, out of sample")
    ax.set_title(f"Feature importance, H = {horizon}")
    fig.tight_layout()
    save_figure(fig, path)


def _cumulative_chart(outcomes, books, rule: str, path: Path) -> None:
    fig = Figure(figsize=(9, 3.6 * len(books)))
    axes = np.atleast_1d(fig.subplots(len(books), 1, sharex=True))
    for ax, book in zip(axes, books, strict=True):
        for o in outcomes:
            if o.book == book and o.rule == rule:
                d = o.daily["net"]
                ax.plot(d.index, d.cumsum() * 100, lw=0.9, label=o.name)
        ax.axhline(0, color="grey", lw=0.5)
        ax.set_ylabel("cumulative net, % of capital")
        ax.set_title(f"{money(book)} of capital, headline cost model")
        ax.legend(fontsize=8)
    fig.tight_layout()
    save_figure(fig, path)


RESULT_COLUMNS = [
    "book", "forecast", "rule", "net Sharpe", "net %", "vol %", "gross %", "gross Sharpe", "cost %", "borrow %",
    "turnover", "capital", "names", "max drawdown %",
]


def _result_row(o) -> list:
    m = o.metrics
    return [
        money(o.book), o.forecast, o.label, fmt(m["sharpe"], 2), pct(m["ann_return"]), pct(m["ann_vol"]), pct(m["ann_gross_return"]),
        fmt(m["gross_sharpe"], 2), pct(m["ann_cost"]), pct(m["ann_borrow"]), fmt(m["turnover"], 3), fmt(m["mean_exposure"], 2),
        f"{m['median_names']:.0f}", pct(m["max_drawdown"]),
    ]


def _walk_summary(fc, dates) -> pd.DataFrame:
    rows = []
    for H, run in fc.runs.items():
        fits = run.walk.fits
        chosen = pd.Series([f"{f.chosen.num_leaves}/{f.chosen.min_data_in_leaf}" for f in fits]).value_counts().sort_index()
        rows.append(
            [
                f"H = {H}", len(fits), str(dates[fits[0].fold.test_start].date()), str(dates[fits[-1].fold.test_stop - 1].date()),
                f"{fits[0].train_rows:,} to {fits[-1].train_rows:,}", ", ".join(f"{k} ×{v}" for k, v in chosen.items()),
                f"{np.median([f.chosen.rounds for f in fits]):.0f}", fmt(float(np.nanmean([f.chosen.validation_ic for f in fits])), 4),
            ]
        )
    cols = ["target", "blocks", "first test day", "last test day", "training rows", "chosen leaves/min per leaf", "median trees", "mean validation IC"]
    return pd.DataFrame(rows, columns=cols)


def _blocks(run, dates) -> pd.DataFrame:
    rows = [
        [
            str(dates[f.fold.test_start].date()), str(dates[f.fold.test_stop - 1].date()), str(f.train_last.date()), f"{f.train_rows:,}",
            f.chosen.num_leaves, f.chosen.min_data_in_leaf, f.chosen.rounds, fmt(f.chosen.validation_ic, 4),
        ]
        for f in run.walk.fits
    ]
    return pd.DataFrame(rows, columns=["test from", "test to", "trained through", "training rows", "leaves", "min per leaf", "trees", "validation IC"])


def write_report(res, out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    plab, mc, fc = res.plab, res.mc, res.fc
    pc, lab = plab.pc, plab.lab
    dates = lab.tables.dates
    books = pc.run.book_sizes
    h, o_ = pc.headline, pc.optimiser
    H0 = mc.target.headline_horizon
    first, last = dates[fc.start].date(), dates[-1].date()
    lines = [
        "# Phase 5: ML signal",
        "",
        "Generated by `uv run python -m statarb.models.run` from `config/models.toml`, with the phase 3 variants and cost model",
        "(`config/costs.toml`) and the phase 4 headline optimiser (`config/portfolio.toml`), unchanged. Development data only:",
        f"every table is cut at {mc.period.development_end}, and the holdout, {mc.period.holdout_start} to {mc.period.holdout_end}, is not read.",
        "",
        f"Forecasts: the model at each target horizon ({', '.join(f'H = {x}' for x in mc.target.horizons)}; H = {H0} is the headline) and",
        f"the phase 3 variants {', '.join(f'`{v}`' for v in mc.runs.variants)}. Each is calibrated to the expected {o_.horizon_days}-day residual move by phase 3's",
        f"trailing calibration and run through {', '.join(mc.runs.rules)} at {' and '.join(money(b) for b in books)}, filled at `{pc.run.fill}`.",
        f"The optimiser is phase 4's headline: λ = {h.risk_aversion:g}, κ = {', '.join(f'{k:g}' for k in mc.runs.cost_multipliers)},",
        f"minimum trade ${h.min_trade_dollars:,.0f}, Model A residuals and risk. Every path starts flat on {first}, the first date every",
        f"forecast has a calibrated move, and ends on {last}. Returns are per dollar of capital, as in phases 3 and 4.",
        "",
        "## Walk-forward",
        "",
        f"Test blocks of {mc.walk_forward.block_days} trading days from {mc.period.first_test}; each block's model is trained at the close of its first",
        f"day on every member-day whose target is known by then. The grid ({', '.join(str(x) for x in mc.tuning.num_leaves)} leaves by",
        f"{', '.join(f'{x:,}' for x in mc.tuning.min_data_in_leaf)} per leaf) is chosen on the last {mc.tuning.validation_days} signal dates of each",
        "training window by mean daily rank IC, with trees by early stopping, and refitted on the whole window.",
        "",
        table(_walk_summary(fc, dates)),
        "",
        f"Blocks of the headline model, H = {H0}:",
        "",
        table(_blocks(fc.runs[H0], dates)),
        "",
        "## Information coefficient",
        "",
        "Daily Spearman correlation between each forecast and the ranked residual return over the next 1, 3 and 5 days, on the",
        "member-days every forecast covers (the test blocks). Mean, standard deviation and t-statistic of the daily series.",
        "",
    ]
    s = res.ic["summary"]
    lines += [
        table(pd.DataFrame({
            "forecast": s["forecast"], "target": s["target"], "mean IC": s["mean"].map(lambda x: fmt(x, 4)),
            "sd": s["sd"].map(lambda x: fmt(x, 4)), "t": s["t_stat"].map(lambda x: fmt(x, 1)), "days": s["days"].map(lambda x: f"{x:.0f}"),
        })),
        "",
        "By year, against the 1-day target: mean IC (t-statistic).",
        "",
        table(_mean_t(res.ic["by_year"], "year")),
        "",
        "![IC by year](ic_by_year.png)",
        "",
        "Decay: IC against the residual return of a single later day, day 1 to 5: mean IC (t-statistic).",
        "",
        table(_mean_t(res.ic["decay"], "day")),
        "",
    ]
    _ic_chart(res.ic["by_year"], out_dir / "ic_by_year.png")

    lines += [
        "## Feature importance",
        "",
        "Gain is summed over every block's model and shown as a share of the total. SHAP values are LightGBM's own TreeSHAP",
        "(`pred_contrib`), each block's model on its own test rows, so they are out of sample: mean absolute value, the size of",
        "a feature's contribution, and mean signed value, in units of the ranked target.",
        "",
    ]
    for H, imp in res.importance.items():
        lines += [
            f"H = {H}:",
            "",
            table(pd.DataFrame({
                "feature": imp["feature"], "gain share %": imp["gain_share"].map(lambda x: pct(x, 1)),
                "mean abs SHAP": imp["mean_abs_shap"].map(lambda x: fmt(x, 5)), "mean SHAP": imp["mean_shap"].map(lambda x: fmt(x, 5)),
            })),
            "",
        ]
    lines += [f"![Feature importance](importance_h{H0}.png)", ""]
    _importance_chart(res.importance[H0], H0, out_dir / f"importance_h{H0}.png")

    ev = res.events
    lines += [
        "## Reversal after event moves",
        "",
        "Member-days in the test blocks by quintile of the day's residual return (1 the most negative), split by phase 1's event",
        f"flag (volume at least {_event_ratio(res)} times its median). Mean forecast of the H = {H0} model and of `{pc.run.variant}`, and the mean",
        f"realised {H0}-day ranked target, which runs from -0.5 to 0.5. A weaker reversal after event moves shows as a smaller",
        "realised spread between the quintiles of event days.",
        "",
        table(pd.DataFrame({
            "quintile": ev["quintile"], "event": ev["event"].map({True: "yes", False: "no"}), "member-days": ev["rows"].map(lambda x: f"{x:,}"),
            "mean residual %": ev["mean_move"].map(lambda x: pct(x, 2)), "model forecast": ev["forecast"].map(lambda x: fmt(x, 4)),
            f"{pc.run.variant} signal %": ev["baseline"].map(lambda x: pct(x, 2)), "realised ranked target": ev["realised"].map(lambda x: fmt(x, 4)),
        })),
        "",
    ]

    d = res.defect
    measured = (
        f"they differ on {d['days_differ']:,} days, from {d['first_differ']} to {d['last_differ']}. The median difference is"
        f" {fmt(d['median_difference'] * 1e4, 2)} bps of daily return ({pct(d['median_relative'], 1)}% of the correct value) and the largest"
        f" {fmt(d['largest_difference'] * 1e4, 2)} bps ({pct(d['largest_relative'], 1)}%)."
        if d["days_differ"] else "they never differ where both have a value."
    )
    lines += [
        "## Dispersion over the whole stock axis",
        "",
        "The dispersion feature counts the members with a residual on or before each day. Counted over every member on the",
        "stock axis instead, it would also count members before their first residual, which the tables know of only because",
        f"they have a residual later. On the development data, from {d['first_day']} to {d['last_day']} ({d['days']:,} days),",
        measured,
        f"On {d['days_one_defined']:,} days only the whole-axis definition has a value, since fewer than two members are yet known.",
        "No model is trained on the whole-axis definition, so this adds no trial.",
        "",
    ]

    cal = res.calibration
    lines += [
        "## Calibration",
        "",
        f"Each forecast's calibration to the {o_.horizon_days}-day residual move over the path dates: the mean slope (in the forecast's own",
        "units, so not comparable across forecasts), the share of days it is positive, and the mean size of the expected move it gives",
        "a member.",
        "",
        table(pd.DataFrame({
            "forecast": cal["forecast"], "mean slope": cal["mean_slope"].map(lambda x: fmt(x, 4)),
            "positive days %": cal["positive_share"].map(lambda x: pct(x, 1)), "mean expected move, bps": cal["mean_abs_move"].map(lambda x: fmt(x * 1e4, 1)),
        })),
        "",
        "## Paths",
        "",
        table(pd.DataFrame([_result_row(o) for o in res.outcomes], columns=RESULT_COLUMNS)),
        "",
        "Turnover is capital traded per day; capital is the mean gross exposure per dollar of capital; names is the median",
        "number held. Cost and borrow are % of capital a year.",
        "",
    ]
    if any(o.rule == OPTIMISER for o in res.outcomes):
        lines += ["![Cumulative net return, optimiser](cumulative_net.png)", ""]
        _cumulative_chart(res.outcomes, books, OPTIMISER, out_dir / "cumulative_net.png")

    lines += ["### Net return by year", "", "% of capital.", ""]
    for book in books:
        rows = {}
        for o in res.outcomes:
            if o.book == book:
                rows[f"{o.forecast}, {o.label}"] = by_year(o.daily)["net_return"]
        frame = pd.DataFrame(rows).T
        frame.columns = [str(c) for c in frame.columns]
        lines += [f"{money(book)}:", "", table(frame.map(lambda x: pct(x, 1)).rename_axis("path").reset_index()), ""]

    v = res.verdict
    lines += [
        "## Against the bar",
        "",
        "The phase 3 bar: a t-statistic of at least 2 and a deflated-Sharpe probability of at least 0.95, against every position",
        "path in this repository's logs from phase 2 on and each model path here. A variant's paths repeat earlier paths over",
        "fewer dates and add no trial; book sizes are not separate trials.",
        "",
        table(pd.DataFrame({
            "forecast": v["forecast"], "rule": v["rule"], "book": v["book"].map(money), "net Sharpe": v["net_sharpe"].map(lambda x: fmt(x, 2)),
            "t": v["t_stat"].map(lambda x: fmt(x, 2)), "benchmark Sharpe": v["benchmark_sharpe"].map(lambda x: fmt(x, 2)),
            "probability": v["deflated_probability"].map(lambda x: fmt(x, 3)), "trials": v["trials"], "clears": v["clears"].map({True: "yes", False: "no"}),
        })),
        "",
    ]
    text = "\n".join(lines)
    (out_dir / "ml.md").write_text(text)
    return text


def _event_ratio(res) -> str:
    return f"{res.event_ratio:g}"
