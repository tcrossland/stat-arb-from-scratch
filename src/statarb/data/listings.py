"""Each ticker's listing exchange by date, from `config/listings.toml` (docs/plans/auction-closes.md).

The file gives every ticker's exchange when it was read (`[current]`) and each
transfer since 2016 (`[[transfer]]`), with the first session on the new
exchange and a primary source. A ticker's listing is walked back from its
current exchange through its transfers, latest first: each transfer's
`to_exchange` must be the exchange the ticker held next, so a missing or
misordered transfer is refused rather than read as a listing. A ticker whose
listing the auction data contradicts and no source settles goes under
`[[left_out]]` with the reason, and the report leaves it out.

Measurement only: no build or frozen record reads this file.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import pandas as pd

from statarb.data.schema import TICKER

EXCHANGES = ("nyse", "nasdaq", "arca", "american", "bzx", "iex")
VALID_FROM, VALID_TO, EXCHANGE = "valid_from", "valid_to", "exchange"


class ListingError(ValueError):
    pass


@dataclass(frozen=True)
class Transfer:
    ticker: str
    first_day: dt.date         # the first session on the new exchange
    from_exchange: str
    to_exchange: str
    source: str
    note: str = ""


@dataclass(frozen=True)
class Listings:
    current: Mapping[str, str]            # ticker -> exchange when the file was read
    transfers: tuple[Transfer, ...]
    left_out: Mapping[str, str] = MappingProxyType({})   # ticker -> why the report leaves it out


def _exchange(value: str, where: str) -> str:
    if value not in EXCHANGES:
        raise ListingError(f"listings: unknown exchange {value!r} in {where}; expected one of {', '.join(EXCHANGES)}")
    return value


def parse_listings(cfg: Mapping[str, Any]) -> Listings:
    """`config/listings.toml` as listings. Refuses an unknown exchange, a ticker listed twice, a transfer with no
    source or of a ticker with no current listing, a chain of transfers that does not lead to the current one, and a
    ticker left out with no reason."""
    current: dict[str, str] = {}
    for exchange, tickers in cfg["current"].items():
        _exchange(exchange, "[current]")
        for t in tickers:
            if t in current:
                raise ListingError(f"listings: {t} is listed on both {current[t]} and {exchange}")
            current[t] = exchange
    transfers = []
    for e in cfg.get("transfer", []):
        where = f"the transfer of {e.get('ticker')}"
        if not e.get("source"):
            raise ListingError(f"listings: {where} has no source")
        t = Transfer(e["ticker"], e["first_day"], _exchange(e["from_exchange"], where), _exchange(e["to_exchange"], where),
                     e["source"], e.get("note", ""))
        if t.from_exchange == t.to_exchange:
            raise ListingError(f"listings: {where} on {t.first_day} does not change the exchange")
        if t.ticker not in current:
            raise ListingError(f"listings: {where} is of a ticker with no current listing")
        transfers.append(t)
    left_out = {}
    for e in cfg.get("left_out", []):
        if not e.get("reason"):
            raise ListingError(f"listings: {e.get('ticker')} is left out with no reason")
        left_out[e["ticker"]] = e["reason"]
    out = Listings(MappingProxyType(dict(sorted(current.items()))), tuple(sorted(transfers, key=lambda t: (t.ticker, t.first_day))),
                   MappingProxyType(dict(sorted(left_out.items()))))
    intervals(out)      # checks every chain
    return out


def intervals(listings: Listings) -> pd.DataFrame:
    """One row per ticker and exchange held: `valid_from` (NaT before the first transfer), `valid_to` (exclusive,
    NaT for the current listing) and the exchange."""
    by_ticker: dict[str, list[Transfer]] = {}
    for t in listings.transfers:
        by_ticker.setdefault(t.ticker, []).append(t)
    rows = []
    for ticker, exchange in listings.current.items():
        held, until = exchange, pd.NaT
        for t in reversed(by_ticker.get(ticker, [])):
            if t.to_exchange != held:
                raise ListingError(f"listings: {ticker} moved to {t.to_exchange} on {t.first_day}, but held {held} next")
            if not pd.isna(until) and pd.Timestamp(t.first_day) >= until:
                raise ListingError(f"listings: {ticker} has two transfers on {t.first_day}")
            rows.append((ticker, pd.Timestamp(t.first_day), until, held))
            held, until = t.from_exchange, pd.Timestamp(t.first_day)
        rows.append((ticker, pd.NaT, until, held))
    frame = pd.DataFrame(rows, columns=[TICKER, VALID_FROM, VALID_TO, EXCHANGE])
    for c in (VALID_FROM, VALID_TO):
        frame[c] = frame[c].astype("datetime64[ns]")
    return frame.sort_values([TICKER, VALID_FROM], na_position="first", kind="mergesort").reset_index(drop=True)


def exchange_on(table: pd.DataFrame, ticker: str, dates: pd.Series) -> pd.Series:
    """The exchange `ticker` was listed on at each of `dates`, by the intervals of `table`; None where it had no listing."""
    own = table.loc[table[TICKER] == ticker]
    out = pd.Series([None] * len(dates), index=dates.index, dtype="object")
    for row in own.itertuples():
        held = pd.Series(True, index=dates.index)
        if not pd.isna(row.valid_from):
            held &= dates >= row.valid_from
        if not pd.isna(row.valid_to):
            held &= dates < row.valid_to
        out[held] = row.exchange
    return out

