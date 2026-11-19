"""Phase 7: the snapshot of MarketParquet's archive.

    uv run python -m statarb.data.marketparquet_build              # check the pinned snapshot
    uv run python -m statarb.data.marketparquet_build --download   # download a new snapshot first
    uv run python -m statarb.data.marketparquet_build --download --start 2024-01-02 --end 2024-12-31

`--start` and `--end` (YYYY-MM-DD, both inclusive) replace `[dates]` of the
config for that download; the snapshot's manifest records the period it holds.

A download needs MARKETPARQUET_API_KEY in the environment. It writes a new
dated snapshot of the day files as served and never modifies an existing one
(statarb.data.marketparquet). Without `--download` nothing touches the network:
the snapshot pinned in config/marketparquet.toml is checked against its digest,
or the latest complete one is found when none is pinned.

A failure the runner expects ends it with one line on standard error and exit
code 1: a missing key, a refusal or an unexpected answer from the archive, a
network that stays down, or a snapshot that is missing, already there or not
the pinned one. Anything else is a bug and keeps its traceback.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
import urllib.error
from pathlib import Path
from typing import Any

from statarb.config import load_config, raw_store, repo_root
from statarb.data import cache, marketparquet
from statarb.data.schema import exchange_today


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def period(cfg: dict[str, Any], start: dt.date | None, end: dt.date | None) -> tuple[dt.date, dt.date]:
    """The first and last session a download asks for: the config's, each replaced by the one given."""
    first, last = start or cfg["dates"]["start"], end or cfg["dates"]["end"]
    if first > last:
        raise marketparquet.ArchiveError(f"the first session asked for, {first}, is after the last, {last}")
    return first, last


def download_snapshot(
    archive: marketparquet.Archive,
    raw_root: Path,
    cfg: dict[str, Any],
    today: dt.date,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> Path:
    """A new snapshot of the configured datasets, over the configured dates or those given, named by `today`."""
    first, last = period(cfg, start, end)
    began = time.monotonic()

    def progress(message: str) -> None:
        minutes, seconds = divmod(int(time.monotonic() - began), 60)
        _log(f"[{minutes:02d}:{seconds:02d}] {message}")

    _log(f"downloading {', '.join(cfg['source']['assets'])} from {first} to {last}")
    path = marketparquet.download(
        archive,
        raw_root,
        cfg["source"]["assets"],
        first,
        last,
        today,
        cfg["download"]["retries"],
        cfg["download"]["workers"],
        progress,
    )
    _log(f"saved to {path}")
    _log(f"to read it, set in [source] of config/marketparquet.toml: snapshot = \"{today}\", "
         f"digest = \"{cache.read_manifest(path)['digest']}\"")
    return path


def describe(path: Path) -> str:
    """One line per dataset of a snapshot: its files and the days they span, from the manifest."""
    manifest = cache.read_manifest(path)
    lines = [f"{path.name}, digest {manifest['digest'][:12]}"]
    lines += [f"{asset}: {d['files']} files, {d['first']} to {d['last']}" for asset, d in manifest["days"].items()]
    return "\n".join(lines)


# What can go wrong without anything being wrong with the code.
EXPECTED = (
    marketparquet.MissingCredentialsError,
    marketparquet.ArchiveError,
    cache.SnapshotExistsError,
    cache.SnapshotDigestError,
    FileNotFoundError,
    urllib.error.URLError,
    TimeoutError,
)


def main(argv: list[str] | None = None) -> int:
    """Run, turning an expected failure into one line and exit code 1."""
    try:
        return run(argv)
    except EXPECTED as exc:
        _log(f"error: {exc}")
        return 1


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--download", action="store_true", help="download a new snapshot before checking")
    parser.add_argument("--start", type=dt.date.fromisoformat, metavar="YYYY-MM-DD",
                        help="with --download: the first session to ask for, in place of [dates] start")
    parser.add_argument("--end", type=dt.date.fromisoformat, metavar="YYYY-MM-DD",
                        help="with --download: the last session to ask for, in place of [dates] end")
    args = parser.parse_args(argv)
    if (args.start or args.end) and not args.download:
        parser.error("--start and --end apply only with --download")

    root = repo_root()
    cfg = load_config("marketparquet", root)
    raw_root = raw_store(load_config("data", root)["paths"]["raw"], root)
    source = cfg["source"]
    if source["name"] != marketparquet.NAME:
        raise ValueError(f"unsupported source: {source['name']}; expected {marketparquet.NAME}")

    if args.download:
        client = marketparquet.Client()  # reads the key first, so a missing key fails before any request
        download_snapshot(client, raw_root, cfg, exchange_today(), args.start, args.end)

    path = cache.select_snapshot(raw_root, marketparquet.NAME, source["snapshot"], source["digest"])
    _log(describe(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
