"""Dated GICS sector mapping: current sector plus known reclassifications.

Each change in config/sector_changes.toml moves a ticker from one sector to
another with effect from a date. Intervals are [valid_from, valid_to), with
valid_to missing for the current sector.
"""

from __future__ import annotations

import datetime as dt
import itertools
from collections.abc import Iterable
from typing import Any

import pandas as pd

from statarb.data.schema import FORMER_GICS_SECTORS, GICS_SECTORS, TICKER


class SectorChangeError(ValueError):
    pass


def build_sector_intervals(
    current: pd.DataFrame, changes: Iterable[dict[str, Any]], start: dt.date
) -> pd.DataFrame:
    """current: columns ticker, sector. changes: dicts with ticker, from, to, effective."""
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    known = set(current[TICKER])
    for change in changes:
        for key in ("ticker", "from", "to", "effective"):
            if key not in change:
                raise SectorChangeError(f"change missing {key!r}: {change}")
        if change["ticker"] not in known:
            raise SectorChangeError(f"change for unknown ticker {change['ticker']!r}")
        for key in ("from", "to"):
            if change[key] not in GICS_SECTORS | FORMER_GICS_SECTORS:
                raise SectorChangeError(f"unknown sector {change[key]!r} in {change}")
        by_ticker.setdefault(change["ticker"], []).append(change)

    rows = []
    for ticker, sector in zip(current[TICKER], current["sector"], strict=True):
        if sector not in GICS_SECTORS:
            raise SectorChangeError(f"unknown current sector {sector!r} for {ticker}")
        history = sorted(by_ticker.get(ticker, []), key=lambda c: c["effective"])
        if history and history[-1]["to"] != sector:
            raise SectorChangeError(f"{ticker}: last change ends in {history[-1]['to']!r}, current is {sector!r}")
        for earlier, later in itertools.pairwise(history):
            if earlier["to"] != later["from"]:
                raise SectorChangeError(f"{ticker}: changes do not chain at {later['effective']}")
        valid_from = pd.Timestamp(start)
        for change in history:
            effective = pd.Timestamp(change["effective"])
            rows.append((ticker, change["from"], valid_from, effective))
            valid_from = effective
        rows.append((ticker, sector, valid_from, pd.NaT))
    return pd.DataFrame(rows, columns=[TICKER, "sector", "valid_from", "valid_to"]).astype(
        {"valid_from": "datetime64[ns]", "valid_to": "datetime64[ns]"}
    )
