"""The auctions download (docs/plans/auction-closes.md), on synthetic responses."""

from __future__ import annotations

import dataclasses
import datetime as dt
import io
import json

import pandas as pd
import pytest

from auction_helpers import EXCHANGE_TABLE, auction_day, fake_auctions
from statarb.config import load_config, repo_root
from statarb.data import alpaca, auctions, cache
from statarb.data.alpaca import Client
from statarb.data.auction_report import first_session

ROOT = repo_root()
DAYS = pd.bdate_range("2026-11-02", "2026-11-13")


def settings(**changes) -> auctions.Settings:
    s = auctions.parse_settings(load_config("auctions", ROOT), dt.date(2026, 11, 16))
    return dataclasses.replace(s, start=dt.date(2026, 11, 2), pause_seconds=0.0, retries=1, **changes)


def history(symbol_days=DAYS) -> list[dict]:
    return [
        auction_day(d, opens=[("Q", "Q", 10.0 + i, None), ("Q", "O", 10.0 + i, 500.0)],
                    closes=[("Q", "6", 11.0 + i, 900.0), ("Q", "M", 11.0 + i, None), ("P", "M", 11.01 + i, None)])
        for i, d in enumerate(symbol_days)
    ]


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_query_asks_for_sip_auctions_through_the_end_of_the_last_new_york_day() -> None:
    q = auctions.query("XYZ", dt.date(2016, 1, 1), dt.date(2026, 11, 13), dt.date(2026, 11, 16))
    assert q == {"symbols": "XYZ", "feed": "sip", "start": "2016-01-01", "end": "2026-11-13T23:59:59-05:00",
                 "asof": "2026-11-16", "limit": "10000", "sort": "asc"}
    assert auctions.end_of_day(dt.date(2026, 7, 1)) == "2026-07-01T23:59:59-04:00"


def test_prints_are_one_row_each_and_a_day_split_across_pages_stays_whole() -> None:
    get = fake_auctions({"XYZ": history()}, page_size=4)
    frame, after = auctions.AuctionSource(get).fetch("XYZ", dt.date(2026, 11, 2), dt.date(2026, 11, 13), dt.date(2026, 11, 16))
    assert after == 0 and len(get.calls) > len(DAYS) // 2
    assert list(frame.columns) == auctions.PRINT_COLUMNS and len(frame) == 5 * len(DAYS)
    one = frame.loc[frame["date"] == DAYS[0]]
    assert sorted(one["session"]) == ["close"] * 3 + ["open"] * 2
    assert one.loc[one["c"] == "M", "s"].isna().all() and (one.loc[one["c"] == "6", "s"] == 900.0).all()


def test_a_print_after_the_last_date_is_dropped_and_counted() -> None:
    late = history(pd.bdate_range("2026-11-12", "2026-11-17"))
    frame, after = auctions.split_after(auctions.prints([{"auctions": {"XYZ": late}}], "XYZ"), dt.date(2026, 11, 13))
    assert frame["date"].max() == pd.Timestamp("2026-11-13") and after == 5 * 2


def test_a_last_date_on_or_after_the_first_session_is_refused() -> None:
    cfg = load_config("auctions", ROOT)
    for last in (dt.date(2026, 11, 16), dt.date(2026, 11, 20)):
        with pytest.raises(auctions.ForwardDayError):
            auctions.parse_settings({**cfg, "download": {**cfg["download"], "last": last}}, dt.date(2026, 11, 16))


def test_the_configured_last_date_is_before_the_forward_run() -> None:
    s = auctions.parse_settings(load_config("auctions", ROOT), first_session(load_config("paper", ROOT)))
    data = load_config("data", ROOT)
    assert s.last < first_session(load_config("paper", ROOT))
    assert s.asof.isoformat() == data["source"]["snapshot"]     # names map as they did for the pinned bars
    assert s.start == data["dates"]["start"]


def test_a_download_writes_a_snapshot_of_its_own(tmp_path) -> None:
    get = fake_auctions({"AAA": history(), "BBB": history()}, page_size=7, fail=frozenset({"CCC"}))
    sleeps: list[float] = []
    path = auctions.download(get, tmp_path, ["BBB", "AAA", "CCC", "DDD"], settings(), dt.date(2026, 11, 27), "alpaca/2026-11-16",
                             sleep=sleeps.append)
    assert path == tmp_path / auctions.SOURCE / "2026-11-27" and cache.is_complete(path)
    m = cache.read_manifest(path)
    assert m["tickers"] == ["AAA", "BBB", "CCC", "DDD"] and m["no_data"] == ["DDD"] and list(m["failed"]) == ["CCC"]
    assert (m["start"], m["last"], m["asof"], m["of_snapshot"]) == ("2026-11-02", "2026-11-13", "2026-11-16", "alpaca/2026-11-16")
    assert m["requests"] == len(get.calls) and m["dropped_after_last"] == {}
    cache.verify(path, m["digest"])
    assert sorted(p.name for p in (path / auctions.PRINTS_DIR).iterdir()) == ["AAA.parquet", "BBB.parquet"]
    assert auctions.read_meta(path, "exchanges.json") == EXCHANGE_TABLE
    assert {p.name for p in (path / auctions.META_DIR).iterdir()} == {"exchanges.json", "conditions-A.json", "conditions-B.json", "conditions-C.json"}
    assert auctions.read_prints(path, "DDD").empty and len(auctions.read_prints(path, "AAA")) == 5 * len(DAYS)
    with pytest.raises(cache.SnapshotExistsError):
        auctions.download(get, tmp_path, ["AAA"], settings(), dt.date(2026, 11, 27), "alpaca/2026-11-16", sleep=sleeps.append)


def test_a_download_is_the_same_bytes_twice(tmp_path) -> None:
    get = fake_auctions({"AAA": history()}, page_size=3)
    a = auctions.download(get, tmp_path / "a", ["AAA"], settings(), dt.date(2026, 11, 27), "x", sleep=lambda s: None)
    b = auctions.download(get, tmp_path / "b", ["AAA"], settings(), dt.date(2026, 11, 27), "x", sleep=lambda s: None)
    assert cache.read_manifest(a)["digest"] == cache.read_manifest(b)["digest"]


def test_requests_go_only_to_the_market_data_host(tmp_path) -> None:
    seen = []

    def opener(request, timeout):
        seen.append(request)
        path = request.full_url.split("?")[0]
        body = EXCHANGE_TABLE if path.endswith("/exchanges") else {"auctions": {}, "next_page_token": None}
        return Response(json.dumps(body).encode())

    client = Client(keys=("id", "secret"), opener=opener, sleep=lambda s: None)
    auctions.download(client.get, tmp_path, ["XYZ"], settings(), dt.date(2026, 11, 27), "x", sleep=lambda s: None)
    assert len(seen) == 5
    assert all(r.full_url.startswith("https://data.alpaca.markets/") for r in seen)
    assert alpaca.DATA_HOST == "https://data.alpaca.markets"


def test_the_exchange_check_refuses_a_missing_or_misnamed_code() -> None:
    s = settings()
    auctions.check_exchanges(s.exchanges, EXCHANGE_TABLE)
    with pytest.raises(ValueError, match="not in Alpaca"):
        auctions.check_exchanges(s.exchanges, {k: v for k, v in EXCHANGE_TABLE.items() if k != "N"})
    with pytest.raises(ValueError, match="names code 'P'"):
        auctions.check_exchanges(s.exchanges, {**EXCHANGE_TABLE, "P": "Cboe EDGX"})


def test_two_exchanges_with_one_code_are_refused() -> None:
    cfg = load_config("auctions", ROOT)
    exchanges = {**cfg["exchanges"], "arca": {"code": "N", "names": ["Arca"]}}
    with pytest.raises(ValueError, match="share a code"):
        auctions.parse_settings({**cfg, "exchanges": exchanges}, None)
