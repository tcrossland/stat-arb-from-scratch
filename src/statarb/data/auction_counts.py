"""How often the listing exchange's auction prices differ from the daily bar's (docs/plans/auction-closes.md).

Pure functions. `ticker_days` reduces one ticker's auction prints to one row
per bar day: the listing exchange's four auction prices (`PRICES`), whether it
and other exchanges printed an official open or close, and which exchange
printed the largest closing auction. `count_tables` turns every ticker's days
into the report's tables, by year and by stocks and ETFs apart, and `render`
writes them. The tables hold counts, shares and sizes of differences in basis
points, never a price, so the report carries no data values.

A print is the listing exchange's when its exchange code is the code of the
exchange `config/listings.toml` lists the ticker on that day. No condition
code is assumed to identify the official price: the conditions table says how
often the listing exchange prints `M` and `Q`, how often other exchanges print
them too, and whether `M` agrees with the closing cross.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from statarb.data.schema import DATE, TICKER

# name: (session, condition, the bar's price it is compared with). Condition codes from Alpaca's market data FAQ:
# 6 Market Center Closing Trade, M Market Center Official Close, O Market Center Opening Trade, Q Market Center Official Open.
PRICES = {
    "close_cross": ("close", "6", "close"),
    "official_close": ("close", "M", "close"),
    "open_cross": ("open", "O", "open"),
    "official_open": ("open", "Q", "open"),
}
LABELS = {
    "close_cross": "Closing cross (`6`) against the bar's close",
    "official_close": "Official close (`M`) against the bar's close",
    "open_cross": "Opening cross (`O`) against the bar's open",
    "official_open": "Official open (`Q`) against the bar's open",
}
STOCK, ETF = "stocks", "ETFs"
KIND, YEAR, CODE = "kind", "year", "code"
BP = 1e4


def _first_by_day(prints: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(each day's earliest price, whether the day has more than one distinct price)."""
    ordered = prints.sort_values([DATE, "ts"], kind="mergesort")
    grouped = ordered.groupby(DATE)["p"]
    return grouped.first(), grouped.nunique() > 1


def ticker_days(prints: pd.DataFrame, bars: pd.DataFrame, codes: pd.Series) -> pd.DataFrame:
    """One row per bar of one ticker.

    `prints` are the ticker's auction prints (`statarb.data.auctions.PRINT_COLUMNS`), `bars` its bars with `date`,
    `open` and `close`, and `codes` the listing exchange's code on each bar's date (aligned with `bars`, None where
    the listing is not known). Columns: the date, the bar's open and close, the code; `any_auction`, `listing_open`,
    `listing_close`; each of `PRICES` with `several_<name>`; `m_listing`, `m_other`, `q_listing`, `q_other`;
    `largest` (the exchange code of the largest sized closing print, None when there is none or two exchanges tie)
    and `largest_tie`.
    """
    days = bars[[DATE, "open", "close"]].reset_index(drop=True).assign(**{CODE: codes.reset_index(drop=True)})
    by_date = days.set_index(DATE)
    p = prints.assign(ts=pd.to_datetime(prints["t"], utc=True, format="ISO8601")) if len(prints) else prints.assign(ts=pd.Series(dtype="datetime64[ns, UTC]"))
    p = p.loc[p[DATE].isin(by_date.index)]
    code = p[DATE].map(by_date[CODE])
    listing = p.loc[p["x"].eq(code) & code.notna()]
    other = p.loc[p["x"].ne(code) | code.isna()]

    def flag(frame: pd.DataFrame) -> pd.Series:
        return days[DATE].isin(set(frame[DATE]))

    out = days.assign(
        any_auction=flag(p),
        listing_open=flag(listing.loc[listing["session"] == "open"]),
        listing_close=flag(listing.loc[listing["session"] == "close"]),
    )
    for name, (session, condition, _) in PRICES.items():
        sub = listing.loc[(listing["session"] == session) & (listing["c"] == condition)]
        first, several = _first_by_day(sub)
        out[name] = out[DATE].map(first).astype("float64")
        out[f"several_{name}"] = out[DATE].map(several).eq(True)
    for flag_name, frame, session, condition in (
        ("m_listing", listing, "close", "M"), ("m_other", other, "close", "M"),
        ("q_listing", listing, "open", "Q"), ("q_other", other, "open", "Q"),
    ):
        out[flag_name] = flag(frame.loc[(frame["session"] == session) & (frame["c"] == condition)])
    sized = p.loc[(p["session"] == "close") & (p["s"] > 0)]
    top = sized.loc[sized["s"] == sized.groupby(DATE)["s"].transform("max")]
    venues = top.groupby(DATE)["x"].unique()
    out["largest"] = out[DATE].map(venues.map(lambda v: v[0] if len(v) == 1 else None))
    out["largest_tie"] = out[DATE].map(venues.map(lambda v: len(v) > 1)).eq(True)
    return out


@dataclass(frozen=True)
class Tables:
    coverage: pd.DataFrame
    conditions: pd.DataFrame
    counts: pd.DataFrame
    listing_check: pd.DataFrame


def _share(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return (numerator / denominator.where(denominator > 0)).astype("float64")


def count_tables(days: pd.DataFrame, tolerance: float) -> Tables:
    """The report's tables from every ticker's `ticker_days`, with `ticker` and `kind` (stocks or ETFs) added."""
    d = days.assign(**{YEAR: days[DATE].dt.year})
    keys = [YEAR, KIND]
    g = d.groupby(keys)
    coverage = pd.DataFrame({
        "bar_days": g.size(),
        "auction_days": g["any_auction"].sum(),
        "listing_close_days": g["listing_close"].sum(),
        "listing_open_days": g["listing_open"].sum(),
        "no_listing_days": g[CODE].apply(lambda s: int(s.isna().sum())),
    }).reset_index()

    both = d[["official_close", "close_cross"]].notna().all(axis=1)
    m_vs_6 = both & ((d["official_close"] - d["close_cross"]).abs() > tolerance)
    known = d["largest"].notna()
    lc, lo = d["listing_close"], d["listing_open"]
    several = d[[f"several_{n}" for n in PRICES]].any(axis=1)
    c = d.assign(
        _m_listing=d["m_listing"] & lc, _m_other=d["m_other"] & lc, _q_listing=d["q_listing"] & lo, _q_other=d["q_other"] & lo,
        _both=both, _m_vs_6=m_vs_6, _known=known, _largest_listing=known & d["largest"].eq(d[CODE]), _several=several,
    ).groupby(keys)
    conditions = pd.DataFrame({
        "listing_close_days": c["listing_close"].sum(),
        "m_listing": _share(c["_m_listing"].sum(), c["listing_close"].sum()),
        "m_other": _share(c["_m_other"].sum(), c["listing_close"].sum()),
        "listing_open_days": c["listing_open"].sum(),
        "q_listing": _share(c["_q_listing"].sum(), c["listing_open"].sum()),
        "q_other": _share(c["_q_other"].sum(), c["listing_open"].sum()),
        "m_and_6_days": c["_both"].sum(),
        "m_differs_from_6": _share(c["_m_vs_6"].sum(), c["_both"].sum()),
        "largest_days": c["_known"].sum(),
        "largest_is_listing": _share(c["_largest_listing"].sum(), c["_known"].sum()),
        "largest_ties": c["largest_tie"].sum(),
        "several_price_days": c["_several"].sum(),
    }).reset_index()

    rows = []
    for name, (_, _, bar) in PRICES.items():
        compared = d[name].notna() & d[bar].notna() & (d[bar] > 0)
        gap = (d[name] - d[bar]).abs()
        bp = (d[name] / d[bar] - 1).abs() * BP
        differs = compared & (gap > tolerance)
        frame = d.assign(_compared=compared, _differs=differs, _bp=bp.where(differs))
        for (year, kind), grp in frame.groupby(keys):
            n, k = int(grp["_compared"].sum()), int(grp["_differs"].sum())
            sizes = grp["_bp"].dropna()
            rows.append({
                YEAR: year, KIND: kind, "price": name, "compared": n, "differ": k, "share": k / n if n else np.nan,
                "median_bp": float(sizes.median()) if k else np.nan, "p95_bp": float(sizes.quantile(0.95)) if k else np.nan,
            })
    counts = pd.DataFrame(rows, columns=[YEAR, KIND, "price", "compared", "differ", "share", "median_bp", "p95_bp"])

    checked = d.loc[known & d[CODE].notna()]
    mismatch = checked.loc[checked["largest"] != checked[CODE]]
    per = checked.groupby([YEAR, TICKER]).size().rename("days")
    bad = mismatch.groupby([YEAR, TICKER]).agg(mismatched=("largest", "size"), venue=("largest", lambda s: s.mode().iat[0]))
    listing_check = bad.join(per).reset_index()
    listing_check["share"] = listing_check["mismatched"] / listing_check["days"]
    listing_check = listing_check[[YEAR, TICKER, "days", "mismatched", "share", "venue"]].sort_values([YEAR, TICKER]).reset_index(drop=True)
    return Tables(coverage, conditions, counts, listing_check)


def flagged(check: pd.DataFrame, share: float) -> pd.DataFrame:
    """The ticker-years whose largest closing print is on another exchange on at least `share` of their days."""
    return check.loc[check["share"] >= share].reset_index(drop=True)


# Rendering ---------------------------------------------------------------------------------------------


def _pct(x: float) -> str:
    return "" if pd.isna(x) else f"{100 * x:.2f}%"


def _bp(x: float) -> str:
    return "" if pd.isna(x) else f"{x:.1f}"


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return "\n".join([*lines, *("| " + " | ".join(r) + " |" for r in rows)])


def render(t: Tables, header: Mapping[str, str], flag_share: float, codes: Mapping[str, str]) -> str:
    """The report: the run's header, then coverage, the condition check, the counts and the listing check."""
    out = ["# Auction prices against the daily bar", ""]
    out += [("Generated by `uv run python -m statarb.data.auction_report`; see the plan in `docs/plans/auction-closes.md`. "
            "Statistics only: no price, size or return."), ""]
    out += [f"- {k}: {v}" for k, v in header.items()]
    out += ["- Listing exchange codes: " + ", ".join(f"{name} `{code}`" for name, code in codes.items()), ""]

    out += ["## Coverage", "", "Symbol-days with a bar, with any auction print, and with a print from the listing exchange.", ""]
    out.append(_table(
        ["Year", "Kind", "Bar days", "Any auction", "Listing close", "Listing open", "Listing not known"],
        [[str(r.year), r.kind, str(r.bar_days), str(r.auction_days), str(r.listing_close_days), str(r.listing_open_days),
          str(r.no_listing_days)] for r in t.coverage.itertuples()],
    ))
    out += ["", "## Condition codes", "",
            ("Of the days with a closing print from the listing exchange: the share on which it prints `M` (official close) "
            "and on which another exchange prints `M` too; the same for `Q` (official open) over the days with an opening "
            "print from it. Then the share of days with both on which its `M` and `6` prices differ, and the share of days "
            "with sized closing prints on which the largest is the listing exchange's."), ""]
    out.append(_table(
        ["Year", "Kind", "Close days", "`M` listing", "`M` other", "Open days", "`Q` listing", "`Q` other", "`M` and `6` days",
         "`M` differs from `6`", "Sized days", "Largest is listing", "Ties", "Several prices"],
        [[str(r.year), r.kind, str(r.listing_close_days), _pct(r.m_listing), _pct(r.m_other), str(r.listing_open_days),
          _pct(r.q_listing), _pct(r.q_other), str(r.m_and_6_days), _pct(r.m_differs_from_6), str(r.largest_days),
          _pct(r.largest_is_listing), str(r.largest_ties), str(r.several_price_days)] for r in t.conditions.itertuples()],
    ))
    out += ["", "## How often the auction price differs from the bar's", "",
            ("Symbol-days with both prices; how many differ by more than the tolerance; and, of those, the median and 95th "
            "percentile of the absolute difference in basis points."), ""]
    for name in PRICES:
        rows = t.counts.loc[t.counts["price"] == name]
        out += [f"### {LABELS[name]}", ""]
        out.append(_table(
            ["Year", "Kind", "Compared", "Differ", "Share", "Median (bp)", "95th percentile (bp)"],
            [[str(r.year), r.kind, str(r.compared), str(r.differ), _pct(r.share), _bp(r.median_bp), _bp(r.p95_bp)]
             for r in rows.itertuples()],
        ))
        out.append("")
    flags = flagged(t.listing_check, flag_share)
    total = t.listing_check.groupby(YEAR)["mismatched"].sum()
    out += ["## Listing check", "",
            ("Days on which the largest closing print is on another exchange than the listed one, by year; then each ticker "
            f"and year where that holds on at least {_pct(flag_share)} of its days, which needs a sourced transfer or "
            "the ticker left out."), ""]
    out.append(_table(["Year", "Days elsewhere"], [[str(y), str(int(n))] for y, n in total.items()]) if len(total) else "None.")
    out += [""]
    out.append(_table(
        ["Year", "Ticker", "Days", "Elsewhere", "Share", "Largest on"],
        [[str(r.year), r.ticker, str(r.days), str(r.mismatched), _pct(r.share), f"`{r.venue}`"] for r in flags.itertuples()],
    ) if len(flags) else "No ticker-year is flagged.")
    return "\n".join(out).rstrip() + "\n"
