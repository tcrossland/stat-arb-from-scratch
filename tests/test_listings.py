"""Listing exchanges by date (docs/plans/auction-closes.md): the intervals and the refusals."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from statarb.config import load_config, repo_root
from statarb.data import listings
from statarb.data.listings import ListingError, exchange_on, intervals, parse_listings

ROOT = repo_root()


def transfer(ticker: str, day: str, frm: str, to: str, source: str = "https://www.sec.gov/x") -> dict:
    return {"ticker": ticker, "first_day": dt.date.fromisoformat(day), "from_exchange": frm, "to_exchange": to, "source": source}


def cfg(*transfers: dict) -> dict:
    return {"current": {"nyse": ["AAA", "CCC"], "nasdaq": ["BBB"], "arca": ["SPY"]}, "transfer": list(transfers)}


def test_a_ticker_is_walked_back_from_its_current_exchange() -> None:
    table = intervals(parse_listings(cfg(transfer("BBB", "2018-03-01", "nyse", "nasdaq"), transfer("BBB", "2021-06-01", "nasdaq", "iex"),
                                         transfer("BBB", "2022-01-03", "iex", "nasdaq"))))
    dates = pd.Series(pd.to_datetime(["2017-01-03", "2018-02-28", "2018-03-01", "2021-05-28", "2021-06-01", "2022-01-03", "2026-11-13"]))
    assert list(exchange_on(table, "BBB", dates)) == ["nyse", "nyse", "nasdaq", "nasdaq", "iex", "nasdaq", "nasdaq"]
    assert list(exchange_on(table, "AAA", dates)) == ["nyse"] * len(dates)
    assert list(exchange_on(table, "ZZZ", dates)) == [None] * len(dates)


def test_a_ticker_left_out_keeps_its_reason() -> None:
    parsed = parse_listings({**cfg(), "left_out": [{"ticker": "CCC", "reason": "listing contradicted by the data"}]})
    assert dict(parsed.left_out) == {"CCC": "listing contradicted by the data"}


def test_a_chain_that_does_not_reach_the_current_listing_is_refused() -> None:
    with pytest.raises(ListingError, match="held nyse next"):
        parse_listings(cfg(transfer("AAA", "2019-01-02", "nyse", "nasdaq")))
    with pytest.raises(ListingError, match="held nyse next"):
        parse_listings(cfg(transfer("BBB", "2018-03-01", "nyse", "nasdaq"), transfer("BBB", "2020-03-02", "nyse", "nasdaq")))


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"current": {"nyse": ["AAA"], "nasdaq": ["AAA"]}}, "both nyse and nasdaq"),
        ({"current": {"lse": ["AAA"]}}, "unknown exchange"),
        (cfg(transfer("AAA", "2019-01-02", "nasdaq", "nyse", source="")), "no source"),
        (cfg(transfer("ZZZ", "2019-01-02", "nasdaq", "nyse")), "no current listing"),
        (cfg(transfer("AAA", "2019-01-02", "nyse", "nyse")), "does not change"),
        (cfg(transfer("BBB", "2019-01-02", "nyse", "iex"), transfer("BBB", "2019-01-02", "iex", "nasdaq")), "two transfers"),
        ({**cfg(), "left_out": [{"ticker": "AAA"}]}, "no reason"),
    ],
)
def test_bad_listings_are_refused(config: dict, message: str) -> None:
    with pytest.raises(ListingError, match=message):
        parse_listings(config)


def test_the_listings_file_parses_and_lists_the_factor_etfs_on_arca() -> None:
    parsed = parse_listings(load_config("listings", ROOT))
    data = load_config("data", ROOT)
    for etf in (data["factors"]["market"], *data["factors"]["sectors"]):
        assert parsed.current[etf] == "arca"
    assert all(t.source.startswith("https://") for t in parsed.transfers)
    assert all(t.first_day >= dt.date(2016, 1, 1) for t in parsed.transfers)
    assert set(listings.EXCHANGES) >= set(parsed.current.values())
