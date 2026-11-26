"""Phase 7: the quality report on MarketParquet's day files (reports/phase-07/data_quality.md).

    uv run python -m statarb.data.marketparquet_quality

It reads the snapshot pinned in config/marketparquet.toml and nothing else, and
writes statistics only: counts, shares and dates, never a symbol's price,
volume or return on a date (CLAUDE.md, "No data values").

What it reads of a day file depends on the file's day (`[sample]` of the config):

- before `start`: the file's footer alone, for its schema and row count;
- from `start` to before `end`: the bars;
- from `end` on: nothing. The file is not opened, and only its name is counted.

The suffix of a delisted symbol is counted here and decides nothing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from statarb.config import load_config, raw_store, repo_root
from statarb.data import cache, marketparquet
from statarb.data.quality import _table
from statarb.data.schema import DATE, TICKER, exchange_calendar

PRICES = ["open", "high", "low", "close"]
# Sessions a symbol is absent between two of its bars, as the report groups them.
GAP_BINS = [0, 1, 5, 20, 250, 10**6]
GAP_LABELS = ["1", "2 to 5", "6 to 20", "21 to 250", "over 250"]


def file_facts(path: Path, asset: str, before: dt.date) -> pd.DataFrame:
    """Each day file's row count and schema, from its footer alone, for days before `before`."""
    rows = []
    for day in marketparquet.snapshot_days(path, asset):
        if day >= before:
            continue
        meta = pq.read_metadata(path / asset / str(day.year) / f"{day.isoformat()}.parquet")
        schema = ", ".join(f"{f.name} {f.type}" for f in meta.schema.to_arrow_schema())
        rows.append((pd.Timestamp(day), meta.num_rows, schema))
    return pd.DataFrame(rows, columns=[DATE, "rows", "schema"]).astype({DATE: "datetime64[ns]", "rows": "int64"})


def rows_by_year(facts: pd.DataFrame) -> pd.DataFrame:
    """Sessions and symbols per session, by year."""
    by_year = facts.groupby(facts[DATE].dt.year.rename("year"))["rows"].agg(
        sessions="count", fewest="min", mean="mean", most="max"
    )
    return by_year.assign(mean=by_year["mean"].round().astype("int64")).reset_index()


def schemas(facts: pd.DataFrame) -> pd.DataFrame:
    """The distinct schemas among the files, with how many files carry each and over which days."""
    found = facts.groupby("schema")[DATE].agg(files="count", first="min", last="max").reset_index()
    return found.sort_values("first")[["files", "first", "last", "schema"]].reset_index(drop=True)


def missing_sessions(days: Sequence[dt.date], sessions: Sequence[dt.date]) -> tuple[list[dt.date], list[dt.date]]:
    """Sessions of the calendar with no file, and files on days that are not sessions."""
    return sorted(set(sessions) - set(days)), sorted(set(days) - set(sessions))


def suffix_share(bars: pd.DataFrame) -> pd.DataFrame:
    """Symbols and symbol-days carrying the delisted suffix, by year."""
    frame = pd.DataFrame({
        "year": bars[DATE].dt.year.to_numpy(),
        TICKER: bars[TICKER].to_numpy(),
        "dead": bars[TICKER].str.endswith(marketparquet.SUFFIX).to_numpy(dtype=bool),
    })
    symbols = frame.drop_duplicates(["year", TICKER]).groupby("year")["dead"].agg(symbols="size", suffixed="sum")
    days = frame.groupby("year")["dead"].agg(symbol_days="size", suffixed_days="sum")
    out = symbols.join(days)
    out["share_of_symbols"] = out["suffixed"] / out["symbols"]
    out["share_of_symbol_days"] = out["suffixed_days"] / out["symbol_days"]
    return out.reset_index()


def bad_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Bars that cannot be right as they stand, counted by year. A bar may be in several columns."""
    prices = bars[PRICES]
    flags = pd.DataFrame({
        "year": bars[DATE].dt.year.to_numpy(),
        "bars": 1,
        "price_missing": prices.isna().any(axis=1).to_numpy(),
        "price_not_positive": (prices <= 0).any(axis=1).to_numpy(),
        "high_below_low": (bars["high"] < bars["low"]).to_numpy(),
        "open_outside_range": ((bars["open"] > bars["high"]) | (bars["open"] < bars["low"])).to_numpy(),
        "close_outside_range": ((bars["close"] > bars["high"]) | (bars["close"] < bars["low"])).to_numpy(),
        "volume_zero": (bars["volume"] == 0).to_numpy(),
        "volume_missing_or_negative": (bars["volume"].isna() | (bars["volume"] < 0)).to_numpy(),
    })
    return flags.groupby("year").sum().astype("int64").reset_index()


def overnight_moves(bars: pd.DataFrame) -> pd.DataFrame:
    """Each bar's open over the same symbol's previous close, where both are positive: `date`, `ticker`, `move`."""
    ordered = bars.sort_values([TICKER, DATE], kind="mergesort")
    previous = ordered.groupby(TICKER, sort=False)["close"].shift()
    known = (previous > 0) & (ordered["open"] > 0)
    return pd.DataFrame({
        DATE: ordered.loc[known, DATE].to_numpy(),
        TICKER: ordered.loc[known, TICKER].to_numpy(),
        "move": (ordered.loc[known, "open"] / previous[known]).to_numpy(),
    })


def split_sized(moves: pd.DataFrame, ratios: Sequence[float], tolerance: float) -> pd.DataFrame:
    """The moves within `tolerance` of a ratio or its inverse: `date`, `ticker`, `ratio`, `direction`.

    A fall to 1/ratio is what a forward split not yet applied looks like, a rise to the ratio a reverse split.
    """
    found = []
    for ratio in ratios:
        for direction, target in (("fall", 1 / ratio), ("rise", float(ratio))):
            near = moves.loc[(moves["move"] / target - 1).abs() <= tolerance, [DATE, TICKER]]
            found.append(near.assign(ratio=float(ratio), direction=direction))
    return pd.concat(found, ignore_index=True)


def split_sized_by_year(moves: pd.DataFrame, sized: pd.DataFrame) -> pd.DataFrame:
    counted = moves.groupby(moves[DATE].dt.year.rename("year")).size().rename("moves").to_frame()
    for direction in ("fall", "rise"):
        part = sized.loc[sized["direction"] == direction]
        counted[f"{direction}s"] = part.groupby(part[DATE].dt.year).size()
    counted["symbols"] = sized.groupby(sized[DATE].dt.year)[TICKER].nunique()
    return counted.fillna(0).astype("int64").reset_index()


def split_sized_by_ratio(sized: pd.DataFrame, ratios: Sequence[float]) -> pd.DataFrame:
    counted = sized.groupby(["ratio", "direction"]).size().unstack("direction")
    counted = counted.reindex(index=[float(r) for r in ratios], columns=["fall", "rise"]).fillna(0).astype("int64")
    counted.index = [f"{r:g}" for r in counted.index]
    return counted.rename_axis("ratio").rename(columns={"fall": "falls", "rise": "rises"}).reset_index()


def absences(bars: pd.DataFrame) -> pd.DataFrame:
    """Each stretch of sessions a symbol is absent between two of its bars: `ticker`, `left` (its last bar
    before), `sessions` (how many it missed). The sessions are the days the table itself holds."""
    position = pd.Series(range(bars[DATE].nunique()), index=sorted(bars[DATE].unique()))
    ordered = bars[[TICKER, DATE]].sort_values([TICKER, DATE], kind="mergesort")
    at = position.loc[ordered[DATE]].to_numpy()
    held = pd.DataFrame({TICKER: ordered[TICKER].to_numpy(), DATE: ordered[DATE].to_numpy(), "at": at})
    held["previous"] = held.groupby(TICKER, sort=False)["at"].shift()
    held["left"] = held.groupby(TICKER, sort=False)[DATE].shift()
    gone = held.loc[held["at"] - held["previous"] > 1]
    return pd.DataFrame({
        TICKER: gone[TICKER].to_numpy(),
        "left": gone["left"].to_numpy(),
        "sessions": (gone["at"] - gone["previous"] - 1).to_numpy(dtype="int64"),
    })


def absences_by_length(gone: pd.DataFrame) -> pd.DataFrame:
    length = pd.cut(gone["sessions"], GAP_BINS, labels=GAP_LABELS)
    counted = gone.groupby(length, observed=False)[TICKER].agg(absences="size", symbols="nunique")
    return counted.rename_axis("sessions_absent").reset_index().astype({"sessions_absent": "str"})


def absences_by_year(gone: pd.DataFrame) -> pd.DataFrame:
    """Absences by the year of the last bar before each."""
    counted = gone.groupby(gone["left"].dt.year.rename("year"))[TICKER].agg(absences="size", symbols="nunique")
    return counted.reset_index()


def _dates(days: Sequence[dt.date]) -> str:
    return ", ".join(day.isoformat() for day in days) if days else "none"


def dataset_section(
    asset: str,
    facts: pd.DataFrame,
    days: Sequence[dt.date],
    sessions: Sequence[dt.date],
    bars: pd.DataFrame,
    ratios: Sequence[float],
    tolerance: float,
) -> list[str]:
    """The report's section on one dataset: `facts` of the files read at all, `days` of every file by name,
    and the `bars` of the sample."""
    missing, extra = missing_sessions(days, sessions)
    unopened = len(days) - len(facts)
    moves = overnight_moves(bars)
    sized = split_sized(moves, ratios, tolerance)
    gone = absences(bars)
    symbols = bars[TICKER].nunique()
    out = [f"## {asset}", ""]
    out += [
        f"- Files: {len(days)}, {days[0]} to {days[-1]}; not opened: {unopened}",
        f"- Sessions of the calendar with no file: {_dates(missing)}",
        f"- Files on days that are not sessions: {_dates(extra)}",
        f"- In the sample: {len(bars)} bars of {symbols} symbols over {bars[DATE].nunique()} sessions",
        "",
    ]
    out += ["### Schemas", "", "From the footers of every file opened.", "", _table(schemas(facts))]
    out += ["### Symbols per session, by year", "", "From the footers' row counts.", "", _table(rows_by_year(facts))]
    out += [
        "### Symbols with the delisted suffix",
        "",
        ("A symbol is counted in each year it has a bar. The suffix is the archive's knowledge at the download, "
        "so these shares are what a later reader knows, not what was known in the year."),
        "",
        _table(suffix_share(bars)),
    ]
    out += ["### Bars that cannot be right", "", "A bar may be counted in several columns.", "", _table(bad_bars(bars))]
    out += [
        "### Moves the size of a split",
        "",
        (f"The move from a symbol's close to its next bar's open, where both are positive. It counts as the size "
        f"of a split when within {tolerance:.0%} of a ratio or its inverse. Prices here are already adjusted for "
        "splits, so these are candidates for a split that was not applied, or was applied twice, among moves "
        "that happened to be that size."),
        "",
        f"{len(sized)} of {len(moves)} moves, in {sized[TICKER].nunique()} symbols.",
        "",
        _table(split_sized_by_ratio(sized, ratios)),
        _table(split_sized_by_year(moves, sized)),
    ]
    out += [
        "### Symbols that vanish and reappear",
        "",
        ("A stretch of sessions with no bar between two bars of one symbol, the suffix being part of the symbol. "
        "By year, an absence is counted in the year of the last bar before it."),
        "",
        f"{len(gone)} absences in {gone[TICKER].nunique()} of {symbols} symbols.",
        "",
        _table(absences_by_length(gone)),
        _table(absences_by_year(gone)),
    ]
    return out


def quality_report(
    path: Path,
    manifest: dict[str, Any],
    start: dt.date,
    end: dt.date,
    sessions: Sequence[dt.date],
    ratios: Sequence[float],
    tolerance: float,
) -> str:
    """The report on the snapshot at `path`: bars of [start, end), footers before `start`, nothing from `end`."""
    out = ["# Phase 7 data quality report: MarketParquet", ""]
    out += ["Statistics only: no price, volume or return of any symbol on any date.", ""]
    out += [
        "## Snapshot",
        "",
        (f"- Source: {manifest['source']}, basis {manifest['basis']}, snapshot {path.name}, "
        f"digest {manifest['digest'][:12]}"),
        f"- Bars read: {start} to before {end}",
        f"- Before {start}: each file's schema and row count, from its footer alone",
        f"- From {end} on: no file opened",
        "",
    ]
    for asset in manifest["assets"]:
        days = marketparquet.snapshot_days(path, asset)
        out += dataset_section(
            asset,
            file_facts(path, asset, end),
            days,
            sessions,
            marketparquet.read_days(path, asset, start, end),
            ratios,
            tolerance,
        )
    return "\n".join(out)


def calendar_sessions(calendar: str, start: dt.date, end: dt.date) -> list[dt.date]:
    """The calendar's sessions in [start, end)."""
    last = end - dt.timedelta(days=1)
    found = exchange_calendar(calendar, start=pd.Timestamp(start), end=pd.Timestamp(last)).sessions
    return [day.date() for day in found if start <= day.date() < end]


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    root = repo_root()
    cfg = load_config("marketparquet", root)
    paths = load_config("data", root)["paths"]
    source = cfg["source"]
    path = cache.select_snapshot(raw_store(paths["raw"], root), marketparquet.NAME, source["snapshot"], source["digest"])
    manifest = cache.read_manifest(path)
    sessions = calendar_sessions(
        cfg["dates"]["calendar"],
        dt.date.fromisoformat(manifest["start"]),
        dt.date.fromisoformat(manifest["end_exclusive"]),
    )
    report = quality_report(
        path,
        manifest,
        cfg["sample"]["start"],
        cfg["sample"]["end"],
        sessions,
        cfg["quality"]["split_ratios"],
        cfg["quality"]["split_tolerance"],
    )
    target = root / paths["reports"] / "phase-07" / "data_quality.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report)
    print(f"wrote {target.relative_to(root)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
