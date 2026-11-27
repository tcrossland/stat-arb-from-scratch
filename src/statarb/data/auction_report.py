"""Auction prices against the daily bar: download, then report (docs/plans/auction-closes.md).

    uv run python -m statarb.data.auction_report --download   # a new auction snapshot, then stop
    uv run python -m statarb.data.auction_report              # reports/phase-08/auction_closes.md

The download fetches the auction prints of every ticker of the bar snapshot
pinned in config/data.toml, from config/auctions.toml's start to its last date,
into a raw snapshot of its own, and prints the setting that pins it. Run it
outside the forward run's scheduled downloads (13:15 and 13:45 CET), which share
the key's limit of 200 requests a minute.

The report reads the pinned auction snapshot and the pinned bar snapshot, both
checked against their digests, and the listing exchanges of
config/listings.toml. It compares the bars as Alpaca returned them, unadjusted
like the auction prices, from the start, or a ticker's listing start in
config/listing_starts.toml where later, to the last date. It writes no table,
changes no build input and reads no day of the forward run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from statarb.backtest.experiments import git_state
from statarb.config import load_config, raw_store, repo_root, resolve_path
from statarb.data import alpaca, auction_counts, auctions, cache, listings
from statarb.data.clean import parse_listing_starts
from statarb.data.schema import DATE, TICKER, exchange_today
from statarb.data.snapshot import BARS_DIR
from statarb.io import read_parquet

REPORT = Path("phase-08") / "auction_closes.md"
BAR_SOURCE = alpaca.AlpacaSource.name


def first_session(paper_cfg: dict[str, Any]) -> dt.date | None:
    value = paper_cfg["run"].get("first_session")
    return value if isinstance(value, dt.date) else None


def raw_bars(snapshot: Path, ticker: str) -> pd.DataFrame:
    """One ticker's bars as Alpaca returned them: date, open, close. Bars with no volume are left out, as the build does."""
    file = snapshot / BARS_DIR / f"{ticker}.parquet"
    if not file.is_file():
        return pd.DataFrame({DATE: pd.Series(dtype="datetime64[ns]"), "open": pd.Series(dtype="float64"), "close": pd.Series(dtype="float64")})
    return alpaca.bar_frame(read_parquet(file).to_dict("records"))[[DATE, "open", "close"]]


def all_days(
    auction_path: Path,
    bar_path: Path,
    tickers: list[str],
    table: pd.DataFrame,
    codes: dict[str, str],
    etfs: set[str],
    start: dt.date,
    last: dt.date,
    starts: Mapping[str, pd.Timestamp] | None = None,
) -> pd.DataFrame:
    """Every ticker's `auction_counts.ticker_days`, from `start`, or its listing start where later (`starts`, from
    config/listing_starts.toml, as the build drops the bars before it), to `last`, with its ticker and kind."""
    frames = []
    for ticker in tickers:
        bars = raw_bars(bar_path, ticker)
        first = max(pd.Timestamp(start), (starts or {}).get(ticker, pd.Timestamp(start)))
        bars = bars.loc[(bars[DATE] >= first) & (bars[DATE] <= pd.Timestamp(last))].reset_index(drop=True)
        if bars.empty:
            continue
        held = listings.exchange_on(table, ticker, bars[DATE])
        days = auction_counts.ticker_days(auctions.read_prints(auction_path, ticker), bars, held.map(codes))
        kind = auction_counts.ETF if ticker in etfs else auction_counts.STOCK
        frames.append(days.assign(**{TICKER: ticker, auction_counts.KIND: kind}))
    return pd.concat(frames, ignore_index=True)


def check_snapshot(manifest: dict[str, Any], s: auctions.Settings) -> None:
    """Refuse an auction snapshot taken with other dates than the settings, or past the last date."""
    for key, want in (("start", s.start), ("last", s.last), ("asof", s.asof)):
        if manifest.get(key) != want.isoformat():
            raise ValueError(f"auction snapshot: {key} is {manifest.get(key)}, config/auctions.toml says {want}")


def report(
    root: Path, cfg: dict[str, Any], data_cfg: dict[str, Any], s: auctions.Settings, table: pd.DataFrame,
    left_out: Mapping[str, str] | None = None,
    starts: Mapping[str, pd.Timestamp] | None = None,
) -> str:
    if not (s.snapshot and s.digest):
        raise ValueError("pin the auction snapshot first: [snapshot] date and digest in config/auctions.toml")
    raw_root = raw_store(data_cfg["paths"]["raw"], root)
    a_path = cache.select_snapshot(raw_root, auctions.SOURCE, s.snapshot, s.digest)
    a_manifest = cache.read_manifest(a_path)
    check_snapshot(a_manifest, s)
    auctions.check_exchanges(s.exchanges, auctions.read_meta(a_path, "exchanges.json"))
    src = data_cfg["source"]
    b_path = cache.select_snapshot(raw_root, BAR_SOURCE, src.get("snapshot", ""), src.get("digest", ""))
    b_manifest = cache.read_manifest(b_path)
    if pd.Timestamp(s.last) >= pd.Timestamp(b_manifest["end_exclusive"]):
        raise ValueError(f"the bar snapshot holds bars before {b_manifest['end_exclusive']}, not through {s.last}")
    f = data_cfg["factors"]
    etfs = {f["market"], *f["sectors"]}
    codes = {name: e.code for name, e in s.exchanges.items()}
    left_out = dict(left_out or {})
    listed = set(table[TICKER]) - set(left_out)
    tickers = sorted(set(a_manifest["tickers"]) & listed)
    days = all_days(a_path, b_path, tickers, table, codes, etfs, s.start, s.last, starts)
    tables = auction_counts.count_tables(days, s.tolerance)
    state = git_state(root)
    header = {
        "Auction snapshot": f"{a_path.name}, digest {a_manifest['digest'][:12]}, {len(a_manifest['tickers'])} tickers, "
                            f"no data {len(a_manifest['no_data'])}, failed {len(a_manifest['failed'])}",
        "Bar snapshot": f"{b_path.name}, digest {b_manifest['digest'][:12]}",
        "Dates": f"{s.start} to {s.last}",
        "Tickers compared": f"{len(tickers)}; with no listing in config/listings.toml: "
                            f"{', '.join(sorted(set(a_manifest['tickers']) - set(table[TICKER]))) or 'none'}",
        "Left out": "; ".join(f"{t} ({why})" for t, why in left_out.items()) or "none",
        "Tolerance": f"{s.tolerance}",
        "Commit": f"{state['git_commit']}, {'dirty' if state['git_dirty'] else 'clean'} tree",
    }
    return auction_counts.render(tables, header, float(cfg["compare"]["flag_share"]), codes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--download", action="store_true", help="download a new auction snapshot, print its pin, and stop")
    args = parser.parse_args(argv)
    root = repo_root()
    cfg = load_config("auctions", root)
    data_cfg = load_config("data", root)
    s = auctions.parse_settings(cfg, first_session(load_config("paper", root)))
    listed = listings.parse_listings(load_config("listings", root))
    table = listings.intervals(listed)

    if args.download:
        raw_root = raw_store(data_cfg["paths"]["raw"], root)
        src = data_cfg["source"]
        b_path = cache.select_snapshot(raw_root, BAR_SOURCE, src.get("snapshot", ""), src.get("digest", ""))
        client = alpaca.Client(retries=s.retries)       # reads the keys first, so a missing key fails before any request
        tickers = cache.read_manifest(b_path)["tickers"]
        auctions.download(client.get, raw_root, tickers, s, exchange_today(), f"{BAR_SOURCE}/{b_path.name}")
        return 0

    starts = parse_listing_starts(load_config("listing_starts", root).get("start", []))
    text = report(root, cfg, data_cfg, s, table, listed.left_out, starts)
    path = resolve_path(data_cfg["paths"]["reports"], root) / REPORT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
