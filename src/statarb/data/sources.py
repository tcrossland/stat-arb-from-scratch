"""Source interfaces. Adapters fetch; shared code converts and derives.

See docs/phases/phase-00/brief.md, "Source interfaces".
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import pandas as pd


class PriceBasis(StrEnum):
    """The basis an adapter's bars are on."""

    UNADJUSTED = "unadjusted"
    # Adjusted for splits as of the download date, not for dividends.
    # Cash and volume are on the same basis.
    SPLIT_ADJUSTED = "split_adjusted"
    # Adjusted for splits and dividends. Not eligible: see IneligibleSourceError.
    FULLY_ADJUSTED = "fully_adjusted"


class IneligibleSourceError(ValueError):
    """Raised for a source whose data cannot be converted to unadjusted form."""


class PriceSource(Protocol):
    name: str
    basis: PriceBasis

    def source_symbol(self, ticker: str) -> str:
        """Map a project ticker (S&P style, e.g. BRK.B) to the source's symbol."""
        ...

    def fetch(self, ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        """Daily bars for trading dates in [start, end), with schema.BAR_COLUMNS.

        Dates are tz-naive exchange trading dates. Returns an empty frame with
        the same columns when the source has no data.
        """
        ...


@dataclass(frozen=True)
class ConstituentSnapshot:
    raw: bytes
    revision_id: int


class ConstituentSource(Protocol):
    name: str

    def fetch(self, revision_id: int | None) -> ConstituentSnapshot:
        """Fetch the pinned revision, or the latest when revision_id is None."""
        ...

    def parse(self, raw: bytes) -> pd.DataFrame:
        """Parse a raw snapshot into columns ticker, security, sector,
        sub_industry, date_added, cik. Tickers are in project (S&P) format."""
        ...
