"""Phase 1 diagnostics: reports/phase-01/diagnostics.md and its charts.

Statistics are computed on universe members at the start of each pair (the
day a signal would be formed), so they describe the stocks we would trade.
They are statistics only: no ticker's return on a date. `diagnostics`
computes the text and the figures; `write_report` writes them. Figures are
built with matplotlib's object interface, not pyplot, so no figure lives in
global state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from statarb.data.schema import DATE, TICKER
from statarb.data.universe import trailing_median_dollar_volume

REPORT_KEYS = {"size_buckets", "autocorrelation_lags", "calm_year"}
SIZE_WINDOW, SIZE_MIN_OBS = 60, 54
MIN_CORR_DAYS = 100


@dataclass(frozen=True)
class Report:
    text: str
    figures: dict[str, Figure]   # file name -> figure


def save_figure(fig: Figure, path: Path) -> None:
    """PNG without software or date metadata, so a rebuild writes identical bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110, metadata={"Software": None})


def sector_on_date(rows: pd.DataFrame, sectors: pd.DataFrame) -> pd.Series:
    """GICS sector of each (date, ticker) row from the dated intervals."""
    left = rows[[DATE, TICKER]].reset_index().sort_values(DATE, kind="mergesort")
    right = sectors.sort_values("valid_from", kind="mergesort")
    merged = pd.merge_asof(left, right, left_on=DATE, right_on="valid_from", by=TICKER, direction="backward")
    inside = merged["valid_to"].isna() | (merged[DATE] < merged["valid_to"])
    return merged.set_index("index")["sector"].where(inside).reindex(rows.index)


def size_bucket(rows: pd.DataFrame, prices: pd.DataFrame, calendar: pd.DatetimeIndex, buckets: int) -> pd.Series:
    """Bucket (1 = smallest) of trailing median dollar volume among the given rows on each date."""
    dv = trailing_median_dollar_volume(prices, calendar, SIZE_WINDOW, SIZE_MIN_OBS)
    dv_long = dv.stack(future_stack=True).rename("dv").reset_index()
    dv_long.columns = [DATE, TICKER, "dv"]
    merged = rows[[DATE, TICKER]].reset_index().merge(dv_long, on=[DATE, TICKER], how="left").set_index("index")
    pct = merged.groupby(DATE)["dv"].rank(pct=True)
    return np.ceil(pct * buckets).clip(1, buckets).reindex(rows.index)


def lead(frame: pd.DataFrame, column: str, k: int, calendar: pd.DatetimeIndex) -> pd.Series:
    """Value of `column` for the same ticker exactly k trading days later, else NaN."""
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    keyed = frame.assign(_pos=pos.loc[frame[DATE]].to_numpy())
    later = keyed[[TICKER, "_pos", column]].assign(_pos=lambda f: f["_pos"] - k)
    out = keyed[[TICKER, "_pos"]].merge(later, on=[TICKER, "_pos"], how="left")
    return pd.Series(out[column].to_numpy(), index=frame.index)


def daily_rank_correlation(x: pd.Series, y: pd.Series, keys: list[pd.Series], min_names: int = 5) -> pd.Series:
    """Spearman correlation of x and y within each group of keys (normally the date)."""
    ok = x.notna() & y.notna()
    frame = pd.DataFrame({"x": x[ok], "y": y[ok], **{f"k{i}": k[ok] for i, k in enumerate(keys)}})
    by = [f"k{i}" for i in range(len(keys))]
    g = frame.groupby(by)
    frame["x"] = g["x"].rank()
    frame["y"] = g["y"].rank()
    frame = frame.assign(xx=frame.x**2, yy=frame.y**2, xy=frame.x * frame.y)
    s = frame.groupby(by)[["x", "y", "xx", "yy", "xy"]].sum()
    n = frame.groupby(by).size()
    cov = s.xy - s.x * s.y / n
    var = (s.xx - s.x**2 / n) * (s.yy - s.y**2 / n)
    corr = cov / np.sqrt(var)
    return corr[(n >= min_names) & (var > 0)]


def summarise(daily: pd.Series) -> dict[str, float]:
    """Mean of a daily series, with a t-statistic that treats days as independent."""
    n = len(daily)
    mean, sd = daily.mean(), daily.std()
    return {"mean": mean, "t": mean / (sd / np.sqrt(n)) if n > 1 and sd > 0 else np.nan, "days": n}


def average_pairwise_correlation(panel: pd.DataFrame) -> float:
    """Mean of the off-diagonal correlations of a dates x stocks panel, pairs with enough common days."""
    corr = panel.corr(min_periods=MIN_CORR_DAYS).to_numpy()
    off = corr[~np.eye(len(corr), dtype=bool)]
    return float(np.nanmean(off))


def fmt(value: float, digits: int = 3) -> str:
    return "" if pd.isna(value) else f"{value:.{digits}f}"


def table(frame: pd.DataFrame) -> str:
    """A markdown table of the frame's values as they stand."""
    cols = [str(c) for c in frame.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in frame.itertuples(index=False):
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def _betas_figure(members: pd.DataFrame) -> Figure:
    monthly = members.groupby(members[DATE].dt.to_period("M"))
    q = monthly[["beta_market", "beta_sector"]].quantile([0.1, 0.5, 0.9]).unstack()
    fig = Figure(figsize=(9, 6))
    axes = fig.subplots(2, 1, sharex=True)
    for ax, col in zip(axes, ["beta_market", "beta_sector"]):
        x = q.index.to_timestamp()
        ax.fill_between(x, q[(col, 0.1)], q[(col, 0.9)], alpha=0.3, label="10th to 90th percentile")
        ax.plot(x, q[(col, 0.5)], label="median")
        ax.axhline(1.0 if col == "beta_market" else 0.0, color="grey", lw=0.8)
        ax.set_ylabel(col.replace("_", " "))
        ax.legend(loc="upper left", fontsize=8)
    axes[0].set_title("Betas of universe members, by month")
    return fig


def _correlation_by_year(members: pd.DataFrame, res: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, grp in members.groupby("year"):
        days = grp[DATE].nunique()
        if days < MIN_CORR_DAYS:
            continue
        steady = grp.groupby(TICKER)[DATE].count()
        tickers = steady[steady >= 0.9 * days].index
        sub = res[(res[DATE].dt.year == year) & res[TICKER].isin(tickers)]
        raw = sub.pivot(index=DATE, columns=TICKER, values="ret")
        resid = sub.pivot(index=DATE, columns=TICKER, values="residual")
        rows.append((year, len(tickers), average_pairwise_correlation(raw), average_pairwise_correlation(resid)))
    return pd.DataFrame(rows, columns=["year", "stocks", "raw", "residual"])


def _lag1(grp: pd.DataFrame, column: str = "residual", later: str = "res_lead1") -> dict[str, float]:
    return summarise(daily_rank_correlation(grp[column], grp[later], [grp[DATE]]))


def diagnostics(
    residuals: pd.DataFrame,
    universe: pd.DataFrame,
    sectors: pd.DataFrame,
    prices: pd.DataFrame,
    cfg: dict[str, Any],
) -> Report:
    """The diagnostics report's markdown and charts, from the residuals and the phase 0 tables."""
    if set(cfg) != REPORT_KEYS:
        raise ValueError(f"[report] keys must be {sorted(REPORT_KEYS)}, got {sorted(cfg)}")
    calendar = pd.DatetimeIndex(sorted(residuals[DATE].unique()))
    res = residuals.merge(universe[[DATE, TICKER]].assign(member=True), on=[DATE, TICKER], how="left")
    res["member"] = res["member"].fillna(False).astype(bool)
    members = res[res["member"]].copy()
    members["sector"] = sector_on_date(members, sectors)
    members["size"] = size_bucket(members, prices, calendar, cfg["size_buckets"])
    lags = range(1, cfg["autocorrelation_lags"] + 1)
    for k in lags:
        members[f"res_lead{k}"] = lead(res, "residual", k, calendar).reindex(members.index)
    members["ret_lead1"] = lead(res, "ret", 1, calendar).reindex(members.index)
    members["year"] = members[DATE].dt.year
    figures: dict[str, Figure] = {}

    out: list[str] = ["# Phase 1 diagnostics: Model A (ETF regression)", ""]
    out += [
        "Generated by `uv run python -m statarb.factors.build`. Statistics use universe members on the day a pair",
        "starts. Daily rank correlation is the Spearman correlation across stocks on one day, averaged over days;",
        "the t-statistic treats days as independent.",
        "",
        "## Coverage",
        "",
        f"- Residual rows: {len(res):,} for {res[TICKER].nunique()} stocks, {res[DATE].min().date()} to {res[DATE].max().date()}.",
        (
            f"- Universe member rows with a residual: {len(members):,}"
            f" of {len(universe):,} ({len(members) / len(universe):.1%})."
        ),
        (
            f"- Market-only rows (no sector ETF that day, or too few days with one in the window):"
            f" {res['market_only'].sum():,} ({res['market_only'].mean():.1%}); among members"
            f" {members['market_only'].mean():.1%}."
        ),
        f"- Event flag (volume spike): {res['event'].sum():,} rows ({res['event'].mean():.1%}).",
        "",
    ]

    # Betas over time.
    figures["betas.png"] = _betas_figure(members)
    yearly = members.groupby("year")[["beta_market", "beta_sector"]].median()
    out += ["## Betas", "", "![Betas over time](betas.png)", "", "Median beta of universe members by year:", ""]
    out.append(table(pd.DataFrame({
        "year": yearly.index, "market": [fmt(v, 2) for v in yearly.beta_market],
        "sector": [fmt(v, 2) for v in yearly.beta_sector]})))
    out.append("")

    # Average pairwise correlation, raw versus residual.
    corr = _correlation_by_year(members, res)
    fig = Figure(figsize=(9, 3.5))
    ax = fig.subplots()
    ax.plot(corr.year, corr.raw, marker="o", label="raw returns")
    ax.plot(corr.year, corr.residual, marker="o", label="residuals")
    ax.axhline(0, color="grey", lw=0.8)
    ax.set_title("Average pairwise correlation among universe members")
    ax.legend(fontsize=8)
    figures["pairwise_correlation.png"] = fig
    out += [
        "## Average pairwise correlation",
        "",
        "Stocks in the universe on at least 90% of the year's trading days; correlations of daily values within",
        f"the year, averaged over all pairs. Years with fewer than {MIN_CORR_DAYS} days of residuals are left out.",
        "",
        "![Average pairwise correlation](pairwise_correlation.png)",
        "",
        table(corr.assign(raw=corr.raw.map(fmt), residual=corr.residual.map(fmt))),
        "",
        f"Mean over years: raw {corr.raw.mean():.3f}, residual {corr.residual.mean():.3f}.",
        "",
    ]

    # Autocorrelation.
    by_date = [members[DATE]]
    lag_rows = []
    for k in lags:
        lead_k = members[f"res_lead{k}"]
        pooled = members["residual"].corr(lead_k)
        s = summarise(daily_rank_correlation(members["residual"], lead_k, by_date))
        lag_rows.append((k, fmt(pooled), fmt(s["mean"], 4), fmt(s["t"], 1)))
    raw1 = _lag1(members, "ret", "ret_lead1")
    out += [
        "## Residual autocorrelation",
        "",
        "Pooled: Pearson correlation of a residual with the same stock's residual *k* days later, over all",
        "member-days. Daily rank: the cross-sectional version, which is what a reversal signal trades.",
        "",
        table(pd.DataFrame(lag_rows, columns=["lag", "pooled Pearson", "daily rank mean", "daily rank t"])),
        "",
        f"For comparison, raw returns at lag 1: daily rank mean {raw1['mean']:.4f} (t {raw1['t']:.1f}).",
        "",
    ]
    yearly_rows, yearly_means = [], []
    for year, grp in members.groupby("year"):
        s = _lag1(grp)
        yearly_rows.append((year, fmt(s["mean"], 4), fmt(s["t"], 1), s["days"]))
        yearly_means.append(float(fmt(s["mean"], 4) or "nan"))   # the bar is the value the table prints
    yearly_ac = pd.DataFrame(yearly_rows, columns=["year", "lag-1 daily rank mean", "t", "days"])
    fig = Figure(figsize=(9, 3.5))
    ax = fig.subplots()
    ax.bar(yearly_ac.year, yearly_means)
    ax.axhline(0, color="grey", lw=0.8)
    ax.set_title("Lag-1 residual daily rank autocorrelation by year")
    figures["autocorrelation_by_year.png"] = fig
    out += ["### By year (lag 1)", "", "![Lag-1 by year](autocorrelation_by_year.png)", "", table(yearly_ac), ""]

    def by_group(column: str, label: str) -> str:
        rows = []
        for value, grp in members.groupby(column):
            cells = [value]
            for k in lags:
                s = summarise(daily_rank_correlation(grp["residual"], grp[f"res_lead{k}"], [grp[DATE]]))
                cells.append(fmt(s["mean"], 4))
            if any(c != "" for c in cells[1:]):
                rows.append(cells)
        return table(pd.DataFrame(rows, columns=[label, *[f"lag {k}" for k in lags]]))

    members["size"] = members["size"].astype("Int64")
    out += [
        "### By sector",
        "",
        "Daily rank correlation within the sector, mean over days with at least five members. Sectors that never",
        "have five members on a day (Telecommunication Services before 2018-09-24) are left out.",
        "",
        by_group("sector", "sector"),
        "",
        "### By size",
        "",
        (
            f"Buckets of trailing {SIZE_WINDOW}-day median dollar volume among members each day, 1 = smallest."
            " The largest names dominate their sector ETFs, which understates their residuals (ETF self-inclusion)."
        ),
        "",
        by_group("size", "bucket"),
        "",
        "### Event days",
        "",
        "Lag-1 daily rank correlation, split by whether day *t* had a volume spike.",
        "",
    ]
    ev_rows = []
    for flagged, grp in members.groupby("event"):
        s = _lag1(grp)
        ev_rows.append(("volume spike" if flagged else "normal", len(grp), fmt(s["mean"], 4), fmt(s["t"], 1)))
    out += [table(pd.DataFrame(ev_rows, columns=["day t", "rows", "mean", "t"])), ""]

    # March 2020 versus a calm year.
    calm = members.loc[members["year"] == cfg["calm_year"], "residual"]
    crash = members.loc[members[DATE].dt.to_period("M") == pd.Period("2020-03"), "residual"]
    qs = [0.01, 0.05, 0.5, 0.95, 0.99]
    periods = [(str(cfg["calm_year"]), calm), ("March 2020", crash)]
    dist_rows = [
        (name, len(s), fmt(s.std(), 4), *[fmt(s.quantile(p), 4) for p in qs], fmt(s.kurt(), 1)) for name, s in periods
    ]
    fig = Figure(figsize=(9, 3.5))
    ax = fig.subplots()
    bins = np.linspace(-0.2, 0.2, 161)
    for name, s in periods:
        ax.hist(s.clip(-0.2, 0.2), bins=bins, density=True, histtype="step", label=name)
    ax.set_yscale("log")
    ax.set_title("Residual distribution of universe members")
    ax.legend(fontsize=8)
    figures["residual_distribution.png"] = fig
    out += [
        f"## Residuals in March 2020 compared with {cfg['calm_year']}",
        "",
        "![Residual distribution](residual_distribution.png)",
        "",
        table(pd.DataFrame(dist_rows, columns=["period", "rows", "std", *[f"q{int(p * 100)}" for p in qs], "excess kurtosis"])),
        "",
    ]
    return Report(text="\n".join(out) + "\n", figures=figures)


def write_report(report: Report, out_dir: Path) -> None:
    """Write diagnostics.md and each chart into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, fig in report.figures.items():
        save_figure(fig, out_dir / name)
    (out_dir / "diagnostics.md").write_text(report.text)
