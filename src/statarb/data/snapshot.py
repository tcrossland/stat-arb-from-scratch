"""A price snapshot read as bars, whatever its layout.

A snapshot of a source with `layout = "raw"` (Alpaca, decision record 0004)
keeps what the source returned: `bars/<ticker>.parquet` with the source's own
bar fields, and `actions/<ticker>.json` with the action records under each
symbol the ticker has held and the bars of the securities it spun off. Its
bars are made here, by the source's rules as they stand in config, so a
changed rule or correction needs a rebuild, not a download. A ticker whose
raw data fails a rule is left out and reported, as a failed download is.

A snapshot of a source with no rules to apply (`layout = "bars"`, such as the
synthetic sources of the tests) keeps `<ticker>.parquet` with
`schema.BAR_COLUMNS` already made, and is read as it is.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from statarb.data import alpaca, cache
from statarb.io import read_parquet

RAW = "raw"
BARS_DIR, ACTIONS_DIR = "bars", "actions"


def write_raw(writer: cache.SnapshotWriter, ticker: str, raw: alpaca.RawTicker) -> None:
    writer.write_frame(f"{BARS_DIR}/{ticker}", pd.DataFrame(list(raw.bars)), sort_by=["t"])
    writer.write_bytes(f"{ACTIONS_DIR}/{ticker}.json", alpaca.raw_actions_json(raw))


@dataclass(frozen=True)
class PriceSnapshot:
    path: Path
    manifest: dict[str, Any]

    @classmethod
    def open(cls, path: Path) -> PriceSnapshot:
        return cls(path, cache.read_manifest(path))

    @property
    def raw(self) -> bool:
        return self.manifest.get("layout") == RAW

    def tickers(self) -> list[str]:
        """The tickers with bars, in order."""
        found = (self.path / BARS_DIR).glob("*.parquet") if self.raw else self.path.glob("*.parquet")
        return sorted(p.stem for p in found)

    def bars(self, ticker: str, rules: alpaca.Rules | None) -> pd.DataFrame:
        """One ticker's bars (schema.BAR_COLUMNS) on the snapshot's basis. Raises alpaca.RuleError for a raw
        snapshot whose data fails a rule."""
        if not self.raw:
            return cache.read_frame(self.path, ticker)
        if self.manifest.get("source") != alpaca.AlpacaSource.name:
            raise ValueError(f"no rules for a raw {self.manifest.get('source')} snapshot: {self.path}")
        if rules is None:
            raise ValueError(f"a raw snapshot needs the rules of config/alpaca.toml: {self.path}")
        bars = read_parquet(self.path / BARS_DIR / f"{ticker}.parquet").to_dict("records")
        raw = alpaca.raw_from(bars, (self.path / ACTIONS_DIR / f"{ticker}.json").read_bytes())
        start = dt.date.fromisoformat(self.manifest["start"])
        end = dt.date.fromisoformat(self.manifest["end_exclusive"])
        return alpaca.apply_rules(raw, ticker, rules, start, end)

    def read_all(self, rules: alpaca.Rules | None) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
        """(bars by ticker, reason by ticker that fails a rule). Tickers with no bars are left out of both."""
        bars, failed = {}, {}
        for ticker in self.tickers():
            try:
                frame = self.bars(ticker, rules)
            except alpaca.RuleError as exc:
                failed[ticker] = f"{type(exc).__name__}: {exc}"
                continue
            if not frame.empty:
                bars[ticker] = frame
        return bars, failed
