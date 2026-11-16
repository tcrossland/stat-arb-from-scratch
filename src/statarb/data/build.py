"""Phase 0 data build.

    uv run python -m statarb.data.build              # rebuild from the pinned snapshots
    uv run python -m statarb.data.build --download   # download new snapshots first

Rebuilds read only the cache in data/raw/. Downloads write a new dated
snapshot and never modify an existing one. An Alpaca snapshot keeps what Alpaca
returned, and the build applies the rules of decision record 0004 to it
(statarb.data.snapshot), so a changed rule needs only a rebuild.

The sources may throttle requests. Downloads pace and retry with backoff
([download] in config/data.toml) and list tickers that still fail under
"failed" in the manifest. Wait or slow down; never evade a limit.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from statarb.config import load_config, raw_store, repo_root, resolve_path
from statarb.data import cache, snapshot
from statarb.data.alpaca import AlpacaSource
from statarb.data.canonical import to_unadjusted
from statarb.data.clean import clean_bars
from statarb.data.quality import QualityInputs, render_report
from statarb.data.returns import total_returns
from statarb.data.schema import DATE, TICKER, exchange_today
from statarb.data.sectors import build_sector_intervals
from statarb.data.sources import ConstituentSource, PriceBasis, PriceSource
from statarb.data.universe import build_universe
from statarb.data.wikipedia import WikipediaConstituents
from statarb.io import write_parquet

# The HTTP client the adapters use: the standard library's, so no client library to record.
CLIENT = f"Python-urllib/{sys.version_info.major}.{sys.version_info.minor}"
PRICE_SOURCES = ("alpaca",)    # decision record 0003: one price source per build


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def download_constituents(source: ConstituentSource, raw_root: Path, revision_id: int, today: dt.date) -> Path:
    """Today's snapshot of the constituent page. A complete one of the pinned revision is reused, not fetched again."""
    existing = cache.snapshot_dir(raw_root, source.name, today)
    if revision_id and cache.is_complete(existing) and cache.read_manifest(existing)["revision_id"] == revision_id:
        _log(f"constituents: revision {revision_id} already saved today in {existing}")
        return existing
    fetched = source.fetch(revision_id or None)
    writer = cache.SnapshotWriter(raw_root, source.name, today)
    writer.write_bytes("page.html", fetched.raw)
    path = writer.commit(
        {"source": source.name, "revision_id": fetched.revision_id, "retrieved": today.isoformat()}
    )
    _log(f"constituents: revision {fetched.revision_id} saved to {path}")
    _log(f"to build from it, set in config/universe.toml: revision_id = {fetched.revision_id}, "
         f"snapshot = \"{today}\", digest = \"{cache.read_manifest(path)['digest']}\"")
    return path


def download_prices(
    source: PriceSource,
    raw_root: Path,
    tickers: list[str],
    start: dt.date,
    today: dt.date,
    pause: float,
    retries: int,
) -> Path:
    """One snapshot of every ticker's bars before `today`, New York's date at the time of the download."""
    writer = cache.SnapshotWriter(raw_root, source.name, today)
    no_data: list[str] = []
    failed: dict[str, str] = {}
    raw = source.layout == snapshot.RAW
    for i, ticker in enumerate(sorted(tickers), start=1):
        for attempt in range(retries + 1):
            try:
                bars = source.fetch_raw(ticker, start, today) if raw else source.fetch(ticker, start, today)
                break
            except Exception as exc:  # noqa: BLE001 - network and parsing errors are recorded, not fatal
                if attempt == retries:
                    failed[ticker] = f"{type(exc).__name__}: {exc}"
                    bars = None
                else:
                    time.sleep(pause * 2 ** (attempt + 2))
        if bars is None:
            pass
        elif bars.empty:
            no_data.append(ticker)
        elif raw:
            snapshot.write_raw(writer, ticker, bars)
        else:
            writer.write_frame(ticker, bars, sort_by=[DATE])
        if i % 50 == 0:
            _log(f"prices: {i}/{len(tickers)}")
        time.sleep(pause)
    manifest = {
        "source": source.name,
        "basis": str(source.basis),
        "layout": source.layout,
        "client": CLIENT,
        "start": start.isoformat(),
        "end_exclusive": today.isoformat(),
        "downloaded_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "tickers": sorted(tickers),
        "no_data": sorted(no_data),
        "failed": dict(sorted(failed.items())),
    }
    path = writer.commit(manifest)
    _log(f"prices: saved to {path}; no data {len(no_data)}, failed {len(failed)}")
    _log(f"to build from it, set in [source] of config/data.toml: snapshot = \"{today}\", "
         f"digest = \"{cache.read_manifest(path)['digest']}\"")
    return path


def select_constituent_snapshot(raw_root: Path, source: str, revision_id: int, pinned: str = "", pinned_digest: str = "") -> Path:
    """The pinned snapshot (download date and digest), verified and of the pinned revision; with no date pinned,
    the latest complete snapshot of the pinned revision, or the latest of any."""
    if pinned:
        path = cache.select_snapshot(raw_root, source, pinned, pinned_digest)
        if revision_id and cache.read_manifest(path)["revision_id"] != revision_id:
            raise ValueError(f"{path} holds revision {cache.read_manifest(path)['revision_id']}, not the pinned {revision_id}")
        return path
    snapshots = cache.complete_snapshots(raw_root, source)
    if revision_id:
        for path in reversed(snapshots):
            if cache.read_manifest(path)["revision_id"] == revision_id:
                return path
        raise FileNotFoundError(f"no {source} snapshot with revision {revision_id}; run with --download")
    if not snapshots:
        raise FileNotFoundError(f"no complete {source} snapshot; run with --download")
    return snapshots[-1]


@dataclass(frozen=True)
class BuildOutputs:
    candidates: pd.DataFrame
    prices: pd.DataFrame
    actions: pd.DataFrame
    returns: pd.DataFrame
    universe: pd.DataFrame
    sectors: pd.DataFrame
    report: str
    failed: dict[str, str]      # ticker -> why the snapshot gave no bars for it: a failed download or a failed rule


def build(
    raw_root: Path,
    cfg: dict[str, Any],
    universe_cfg: dict[str, Any],
    changes: list[dict[str, Any]],
    constituent_source: ConstituentSource,
    price_source_name: str,
) -> BuildOutputs:
    """The phase 0 tables and quality report, from the snapshots under `raw_root` alone."""
    start = cfg["dates"]["start"]
    market = cfg["factors"]["market"]

    c_path = select_constituent_snapshot(
        raw_root,
        constituent_source.name,
        int(universe_cfg["revision_id"]),
        universe_cfg.get("snapshot", ""),
        universe_cfg.get("digest", ""),
    )
    c_manifest = cache.read_manifest(c_path)
    candidates = constituent_source.parse((c_path / "page.html").read_bytes())

    p_path = cache.select_snapshot(
        raw_root, price_source_name, cfg["source"].get("snapshot", ""), cfg["source"].get("digest", "")
    )
    prices_snapshot = snapshot.PriceSnapshot.open(p_path)
    p_manifest = prices_snapshot.manifest
    basis = PriceBasis(p_manifest["basis"])

    by_ticker, rule_failed = prices_snapshot.read_all()
    failed = dict(sorted({**p_manifest.get("failed", {}), **rule_failed}.items()))
    available = sorted(by_ticker)
    frames = [to_unadjusted(by_ticker[t], basis).assign(**{TICKER: t}) for t in available]
    raw_bars = pd.concat(frames, ignore_index=True)
    raw_bars = raw_bars.loc[raw_bars[DATE] >= pd.Timestamp(start)]

    calendar = pd.DatetimeIndex(sorted(raw_bars.loc[raw_bars[TICKER] == market, DATE].unique()))
    if len(calendar) == 0:
        raise ValueError(f"no bars for the market instrument {market}")
    bars, drops = clean_bars(raw_bars, calendar)

    prices = bars[[DATE, TICKER, "open", "high", "low", "close", "volume"]].astype({"volume": "int64"})
    actions = bars.loc[(bars["split_ratio"] != 1.0) | (bars["cash"] != 0.0), [DATE, TICKER, "split_ratio", "cash"]]
    returns = total_returns(bars)

    stock_tickers = sorted(set(candidates[TICKER]) & set(available))
    u = cfg["universe"]
    if u["rebalance"] != "monthly":
        raise ValueError(f"unsupported rebalance rule: {u['rebalance']}")
    universe = build_universe(
        bars, stock_tickers, calendar, u["size"], u["liquidity_window_days"], u["liquidity_min_observations"]
    )
    sectors = build_sector_intervals(candidates[[TICKER, "sector"]], changes, start)

    no_data = sorted(set(candidates[TICKER]) - set(available) - set(failed))
    report = render_report(
        QualityInputs(
            prices=prices,
            returns=returns,
            universe=universe,
            candidates=candidates,
            calendar=calendar,
            drops=drops,
            no_data=no_data,
            failed=failed,
            snapshot={
                "Constituent source": f"{constituent_source.name}, revision {c_manifest['revision_id']}, "
                f"retrieved {c_manifest['retrieved']}, digest {c_manifest.get('digest', 'none')[:12]}",
                "Price source": f"{p_manifest['source']}, basis {p_manifest['basis']}, snapshot {p_path.name}, "
                f"digest {p_manifest.get('digest', 'none')[:12]}, bars before {p_manifest['end_exclusive']}",
            },
            max_abs_return=cfg["quality"]["max_abs_daily_return"],
            min_coverage=cfg["quality"]["min_live_coverage"],
            data_start=pd.Timestamp(start),
        )
    )
    return BuildOutputs(candidates, prices, actions, returns, universe, sectors, report, failed)


def write_outputs(out: BuildOutputs, processed: Path, reports: Path) -> None:
    write_parquet(out.candidates, processed / "candidates.parquet", [TICKER])
    write_parquet(out.prices, processed / "prices.parquet", [DATE, TICKER])
    write_parquet(out.actions, processed / "actions.parquet", [DATE, TICKER])
    write_parquet(out.returns, processed / "returns.parquet", [DATE, TICKER])
    write_parquet(out.universe, processed / "universe.parquet", [DATE, TICKER])
    write_parquet(out.sectors, processed / "sectors.parquet", [TICKER, "valid_from"])
    report_path = reports / "phase-00" / "data_quality.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(out.report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--download", action="store_true", help="download new snapshots before building")
    parser.add_argument(
        "--add-hashes", nargs="+", type=Path, metavar="SNAPSHOT",
        help="write file hashes and the digest into complete snapshots whose manifests lack them, print each digest, and stop",
    )
    args = parser.parse_args(argv)

    if args.add_hashes:
        for path in args.add_hashes:
            print(f"{path}: digest {cache.add_hashes(path)}")
        return 0

    root = repo_root()
    cfg = load_config("data", root)
    universe_cfg = load_config("universe", root)
    changes = load_config("sector_changes", root).get("change", [])
    raw_root = raw_store(cfg["paths"]["raw"], root)
    name = cfg["source"]["name"]
    if name not in PRICE_SOURCES:
        raise ValueError(f"unsupported price source: {name}; expected one of {', '.join(PRICE_SOURCES)}")
    constituents = WikipediaConstituents()

    if args.download:
        source = AlpacaSource()  # reads the keys first, so a missing key fails before any request
        today = exchange_today()  # bars before today's New York date only
        c_path = download_constituents(constituents, raw_root, int(universe_cfg["revision_id"]), today)
        tickers = constituents.parse((c_path / "page.html").read_bytes())[TICKER].tolist()
        tickers += [cfg["factors"]["market"], *cfg["factors"]["sectors"]]
        d = cfg["download"]
        download_prices(source, raw_root, sorted(set(tickers)), cfg["dates"]["start"], today, d["pause_seconds"], d["retries"])

    out = build(raw_root, cfg, universe_cfg, changes, constituents, name)
    write_outputs(out, resolve_path(cfg["paths"]["processed"], root), resolve_path(cfg["paths"]["reports"], root))
    _log("build complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
