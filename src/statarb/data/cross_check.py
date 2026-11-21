"""Phase 7: one price source against another, for the same names (reports/phase-07/cross_check.md).

Pure comparisons of two tables of daily bars: the first source's, put on the
split basis of its download, and the second's, which is served on that basis.
Statistics only: counts, shares and dates, never a symbol's price, volume or
return on a date (CLAUDE.md, "No data values").

Putting the first source on the download's basis divides each price by every
later split, which is look-ahead by construction. It is done here to compare
two sources and nowhere a decision is made.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

import numpy as np
import pandas as pd

from statarb.data.returns import total_returns
from statarb.data.schema import DATE, PRICE_COLUMNS, TICKER

FIRST, SECOND = "_a", "_m"       # column suffixes of the first and second source in a paired table
KINDS = ["none", "cash", "split"]


def on_download_basis(prices: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Unadjusted bars adjusted for every split after each bar's date: prices divided, volume multiplied."""
    bars = prices.merge(actions[[DATE, TICKER, "split_ratio"]], on=[DATE, TICKER], how="left", validate="one_to_one")
    bars = bars.sort_values([TICKER, DATE], kind="mergesort").reset_index(drop=True)
    ratio = bars["split_ratio"].fillna(1.0)
    through = ratio.groupby(bars[TICKER], sort=False).cumprod()
    later = through.groupby(bars[TICKER], sort=False).transform("last") / through
    out = bars[[DATE, TICKER]].copy()
    for column in PRICE_COLUMNS:
        out[column] = bars[column] / later
    out["volume"] = bars["volume"] * later
    return out


def paired(first: pd.DataFrame, second: pd.DataFrame) -> pd.DataFrame:
    """Both sources' bars side by side, one row per date and ticker either holds, with `held`: both, first or second."""
    columns = [DATE, TICKER, *PRICE_COLUMNS, "volume"]
    both = first[columns].merge(second[columns], on=[DATE, TICKER], how="outer", suffixes=(FIRST, SECOND), indicator="held")
    held = both["held"].map({"both": "both", "left_only": "first", "right_only": "second"}).astype("str")
    return both.assign(held=held).sort_values([TICKER, DATE], kind="mergesort").reset_index(drop=True)


def one_sided(pairs: pd.DataFrame) -> pd.DataFrame:
    """Tickers with rows in one source alone: how many and over which days."""
    alone = pairs.loc[pairs["held"] != "both"]
    found = alone.groupby([TICKER, "held"])[DATE].agg(rows="count", first="min", last="max").reset_index()
    return found.sort_values(["held", "rows", TICKER], ascending=[True, False, True]).reset_index(drop=True)


def _share(flags: pd.Series) -> str:
    return f"{100 * flags.mean():.3f}%" if len(flags) else "none"


def agreement_by_year(pairs: pd.DataFrame, close_tolerance: float, volume_tolerance: float) -> pd.DataFrame:
    """Of the symbol-days both hold: the share whose closes and whose volumes agree within a relative
    tolerance, and the median of the second source's volume over the first's."""
    both = pairs.loc[pairs["held"] == "both"]
    frame = pd.DataFrame({
        "year": both[DATE].dt.year.to_numpy(),
        "close": ((both["close" + SECOND] / both["close" + FIRST] - 1).abs() <= close_tolerance).to_numpy(),
        "volume": ((both["volume" + SECOND] / both["volume" + FIRST] - 1).abs() <= volume_tolerance).to_numpy(),
        "ratio": (both["volume" + SECOND] / both["volume" + FIRST]).to_numpy(),
    })
    rows = [
        (year, len(g), _share(g["close"]), _share(g["volume"]), round(float(g["ratio"].median()), 4))
        for year, g in frame.groupby("year")
    ]
    return pd.DataFrame(rows, columns=["year", "symbol_days", "closes_agree", "volumes_agree", "median_volume_ratio"])


def return_pairs(first: pd.DataFrame, second: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    """Each source's price return on the days both have one from the same previous day, with the first
    source's total return and what went ex: `price_ret`, `second_ret`, `total_ret`, `kind`."""
    flat = {"cash": 0.0, "split_ratio": 1.0}
    one = total_returns(first.assign(**flat))[[DATE, TICKER, "ret", "prev_date"]].rename(columns={"ret": "price_ret"})
    two = total_returns(second.assign(**flat))[[DATE, TICKER, "ret", "prev_date"]].rename(columns={"ret": "second_ret"})
    out = one.merge(two, on=[DATE, TICKER, "prev_date"], validate="one_to_one")
    out = out.merge(
        returns[[DATE, TICKER, "prev_date", "ret", "split_ratio", "cash"]].rename(columns={"ret": "total_ret"}),
        on=[DATE, TICKER, "prev_date"],
        validate="one_to_one",
    )
    out["kind"] = np.where(out["split_ratio"] != 1.0, "split", np.where(out["cash"] != 0.0, "cash", "none"))
    return out.drop(columns=["split_ratio", "cash"])


def returns_by_kind(r: pd.DataFrame, tolerance: float, step: float) -> pd.DataFrame:
    """By what went ex in the first source: how often the second's price return is the first's."""
    gap = (r["second_ret"] - r["price_ret"]).abs()
    rows = []
    for kind in KINDS:
        of = gap[r["kind"] == kind]
        rows.append((kind, len(of), _share(of <= tolerance), int((of > step).sum())))
    return pd.DataFrame(rows, columns=["went_ex", "returns", "agree", "apart"])


def partings(r: pd.DataFrame, step: float) -> pd.DataFrame:
    """The returns on which the two split-adjusted series part by more than `step`: `date`, `ticker`, `kind`."""
    return r.loc[(r["second_ret"] - r["price_ret"]).abs() > step, [DATE, TICKER, "kind"]].reset_index(drop=True)


def partings_by_year(r: pd.DataFrame, apart: pd.DataFrame) -> pd.DataFrame:
    counted = r.groupby(r[DATE].dt.year.rename("year")).size().rename("returns").to_frame()
    for kind in KINDS:
        of = apart.loc[apart["kind"] == kind]
        counted[kind] = of.groupby(of[DATE].dt.year).size()
    counted["tickers"] = apart.groupby(apart[DATE].dt.year)[TICKER].nunique()
    return counted.fillna(0).astype("int64").reset_index()


def busiest_days(apart: pd.DataFrame, most: int) -> pd.DataFrame:
    """The days on which the most tickers part."""
    counted = apart.groupby(DATE)[TICKER].nunique().rename("tickers").reset_index()
    return counted.sort_values(["tickers", DATE], ascending=[False, True]).head(most).reset_index(drop=True)


def cash_days(r: pd.DataFrame, tolerance: float, sizes: Sequence[float]) -> pd.DataFrame:
    """The first source's cash days by the size of what went ex (its total return less its price return):
    whether the second source's return is the price return, or else nearer the total or the price return."""
    cash = r.loc[r["kind"] == "cash"]
    to_price = (cash["second_ret"] - cash["price_ret"]).abs()
    to_total = (cash["second_ret"] - cash["total_ret"]).abs()
    verdict = np.where(to_price <= tolerance, "price_return", np.where(to_total < to_price, "nearer_total", "nearer_price"))
    edges = [0.0, *sizes, np.inf]
    labels = [f"up to {100 * sizes[0]:g}%", *(f"{100 * a:g}% to {100 * b:g}%" for a, b in itertools.pairwise(sizes)),
              f"over {100 * sizes[-1]:g}%"]
    size = pd.cut(cash["total_ret"] - cash["price_ret"], edges, labels=labels)
    frame = pd.DataFrame({"cash_over_price": size.astype("str").to_numpy(), "verdict": verdict})
    counted = frame.groupby(["cash_over_price", "verdict"]).size().unstack("verdict")
    counted = counted.reindex(index=labels, columns=["price_return", "nearer_total", "nearer_price"]).fillna(0).astype("int64")
    return counted.assign(days=counted.sum(axis=1)).reset_index()[["cash_over_price", "days", "price_return", "nearer_total", "nearer_price"]]


def variance_shares(r: pd.DataFrame) -> pd.DataFrame:
    """By year, pooled over symbol-days: how much of the first source's squared total return its own price
    return lacks, how much the second source's return lacks, and the two returns' correlation."""
    rows = []
    for year, g in r.groupby(r[DATE].dt.year):
        total = float((g["total_ret"] ** 2).sum())
        rows.append((
            year,
            f"{100 * float(((g['total_ret'] - g['price_ret']) ** 2).sum()) / total:.3f}%",
            f"{100 * float(((g['total_ret'] - g['second_ret']) ** 2).sum()) / total:.3f}%",
            round(float(np.corrcoef(g["total_ret"], g["second_ret"])[0, 1]), 5),
        ))
    return pd.DataFrame(rows, columns=["year", "first_price_return_lacks", "second_return_lacks", "correlation"])


def against_basis(pairs: pd.DataFrame, window: int) -> pd.DataFrame:
    """Each symbol-day both hold, with `basis`, the centred median over `window` of its days of the second
    close over the first, and `off`, how far that day's ratio is from it. The median looks both ways: a
    diagnostic of the sources, never an input."""
    both = pairs.loc[pairs["held"] == "both", [DATE, TICKER]].copy()
    ratio = pairs.loc[pairs["held"] == "both", "close" + SECOND] / pairs.loc[pairs["held"] == "both", "close" + FIRST]
    both["basis"] = ratio.groupby(both[TICKER], sort=False).transform(lambda s: s.rolling(window, center=True, min_periods=1).median())
    both["off"] = (ratio / both["basis"] - 1).abs()
    return both


def closes_by_year(based: pd.DataFrame, bands: Sequence[float]) -> pd.DataFrame:
    """The share of closes further from their basis than each band, by year."""
    rows = [(year, len(g), *(_share(g["off"] > band) for band in bands)) for year, g in based.groupby(based[DATE].dt.year)]
    return pd.DataFrame(rows, columns=["year", "symbol_days", *(f"over_{band:g}" for band in bands)])


def other_basis(based: pd.DataFrame, tolerance: float) -> pd.DataFrame:
    """Tickers the second source holds on another basis than the first's splits give, and over which days."""
    off = based.loc[(based["basis"] - 1).abs() > tolerance]
    found = off.groupby(TICKER)[DATE].agg(days="count", first="min", last="max").reset_index()
    return found.sort_values(["days", TICKER], ascending=[False, True]).reset_index(drop=True)


def other_basis_by_year(based: pd.DataFrame, tolerance: float) -> pd.DataFrame:
    off = (based["basis"] - 1).abs() > tolerance
    year = based[DATE].dt.year.rename("year")
    counted = pd.DataFrame({"symbol_days": off.groupby(year).sum(), "tickers": based.loc[off].groupby(year)[TICKER].nunique()})
    return counted.fillna(0).astype("int64").reset_index()
