"""Alpaca adapter rules (decision record 0004), on synthetic responses."""

from __future__ import annotations

import datetime as dt
import io
import json
import urllib.error

import pandas as pd
import pytest

from helpers import fake_alpaca, synthetic_truth
from statarb.data import alpaca
from statarb.data.alpaca import (
    AlpacaSource,
    Client,
    MissingCredentialsError,
    WithholdingError,
)
from statarb.data.build import download_prices
from statarb.data.snapshot import PriceSnapshot

DATES = pd.bdate_range("2025-01-02", "2025-02-28")
START, END = dt.date(2025, 1, 1), dt.date(2025, 3, 1)


def source(get) -> AlpacaSource:
    return AlpacaSource(get=get)


def truth(seed: int = 1, **kwargs) -> pd.DataFrame:
    return synthetic_truth(DATES, seed, **kwargs)


def div(symbol: str, ex: str, rate: float, foreign: bool = False, rid: str | None = None, **extra) -> tuple[str, dict]:
    processed = (dt.date.fromisoformat(ex) + dt.timedelta(days=20)).isoformat()
    rec = {"id": rid or f"{symbol}-{ex}-{rate}", "symbol": symbol, "ex_date": ex, "process_date": processed,
           "rate": rate, "foreign": foreign, **extra}
    return "cash_dividends", rec


def cash_on(bars: pd.DataFrame, day: str) -> float:
    return float(bars.loc[bars["date"] == pd.Timestamp(day), "cash"].iloc[0])


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# Bars and requests -------------------------------------------------------------------------------------


def test_bars_are_on_new_york_dates_in_window_and_paged() -> None:
    get = fake_alpaca({"XYZ": truth()}, page_size=7)
    bars = source(get).fetch("XYZ", dt.date(2025, 1, 6), dt.date(2025, 2, 3))
    assert bars["date"].min() == pd.Timestamp("2025-01-06") and bars["date"].max() == pd.Timestamp("2025-01-31")
    bar_calls = [p for path, p in get.calls if path == alpaca.BARS]
    assert len(bar_calls) > 1 and bar_calls[0]["adjustment"] == "raw" and bar_calls[0]["feed"] == "sip"
    assert bar_calls[0]["end"] == "2025-02-02"   # Alpaca's end is inclusive


def test_a_bar_with_no_volume_is_missing() -> None:
    # A day with no trade on the consolidated tape: Alpaca repeats the last close on zero volume.
    t = truth()
    t.loc[t["date"] == pd.Timestamp("2025-01-15"), "volume"] = 0.0
    bars = source(fake_alpaca({"XYZ": t})).fetch("XYZ", START, END)
    assert pd.Timestamp("2025-01-15") not in set(bars["date"]) and len(bars) == len(t) - 1


def test_unknown_symbol_is_empty() -> None:
    bars = source(fake_alpaca({})).fetch("NONE", START, END)
    assert bars.empty and list(bars.columns) == alpaca.BAR_COLUMNS


def test_action_query_reaches_past_the_window_and_keeps_by_ex_date() -> None:
    # Processed 20 days after its ex-date: a query ending at the window's end would miss it.
    late = div("XYZ", "2025-02-27", 0.5)
    after = div("XYZ", "2025-03-03", 0.7)
    get = fake_alpaca({"XYZ": truth()}, extra=[late, after])
    bars = source(get).fetch("XYZ", START, END)
    assert cash_on(bars, "2025-02-27") == 0.5
    assert bars["cash"].sum() == 0.5
    action_call = next(p for path, p in get.calls if path == alpaca.ACTIONS)
    assert action_call["end"] == (END + alpaca.ACTION_MARGIN).isoformat()


def test_requests_go_only_to_the_market_data_host() -> None:
    seen = []

    def opener(request, timeout):
        seen.append(request)
        return Response(json.dumps({"bars": {}, "next_page_token": None}).encode())

    client = Client(keys=("id", "secret"), opener=opener, sleep=lambda s: None)
    source(client.get).fetch("XYZ", START, END)
    assert seen and all(r.full_url.startswith(alpaca.DATA_HOST + "/") for r in seen)
    assert seen[0].get_header("Apca-api-key-id") == "id"
    assert alpaca.request_url("/v2/x", {"a": "1"}).startswith("https://data.alpaca.markets/v2/x?")


def test_client_paces_requests_and_retries_rate_limits() -> None:
    sleeps: list[float] = []
    calls = {"n": 0}

    def opener(request, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, io.BytesIO(b""))
        return Response(b"{}")

    client = Client(keys=("id", "secret"), opener=opener, clock=lambda: 100.0, sleep=sleeps.append, min_interval=0.5)
    assert client.get("/v2/x", {}) == {}
    assert sleeps == [10.0, 0.5]


def test_keys_come_from_the_environment() -> None:
    assert alpaca.keys_from_env({"APCA_API_KEY_ID": "a", "APCA_API_SECRET_KEY": "b"}) == ("a", "b")
    with pytest.raises(MissingCredentialsError, match="APCA_API_SECRET_KEY"):
        alpaca.keys_from_env({"APCA_API_KEY_ID": "a"})


# Actions -----------------------------------------------------------------------------------------------


def test_reverse_split_ratio() -> None:
    rec = ("reverse_splits", {"id": "r", "symbol": "XYZ", "ex_date": "2025-02-03", "process_date": "2025-02-03",
                              "old_rate": 5, "new_rate": 1})
    bars = source(fake_alpaca({"XYZ": truth()}, extra=[rec])).fetch("XYZ", START, END)
    assert bars.loc[bars["split_ratio"] != 1.0, "split_ratio"].tolist() == [0.2]


def test_stock_dividends_are_not_applied() -> None:
    rec = ("stock_dividends", {"id": "s", "symbol": "XYZ", "ex_date": "2025-02-03", "process_date": "2025-02-03", "rate": 1.3})
    bars = source(fake_alpaca({"XYZ": truth()}, extra=[rec])).fetch("XYZ", START, END)
    assert (bars["split_ratio"] == 1.0).all()


def test_action_on_a_date_without_a_bar_fails() -> None:
    sparse = truth().drop(index=[5])
    missing = sparse["date"].min() + pd.tseries.offsets.BDay(5)
    rec = div("XYZ", missing.date().isoformat(), 0.4)
    with pytest.raises(alpaca.ActionDateError):
        source(fake_alpaca({"XYZ": sparse}, extra=[rec])).fetch("XYZ", START, END)


# Withholding -------------------------------------------------------------------------------------------


def test_a_foreign_dividend_fails_its_ticker() -> None:
    rec = div("XYZ", "2025-02-10", 0.75, foreign=True)
    with pytest.raises(WithholdingError, match="withholding"):
        source(fake_alpaca({"XYZ": truth()}, extra=[rec])).fetch("XYZ", START, END)


# Raw snapshots: the download keeps what Alpaca returned, the build applies the rules ----------------------


def _raw_snapshot(tmp_path, truths, extra, tickers):
    src = source(fake_alpaca(truths, extra=extra))
    path = download_prices(src, tmp_path / "raw", tickers, START, END, 0.0, 0)
    return src, PriceSnapshot.open(path)


def test_a_raw_snapshot_reads_as_the_adapter_fetches(tmp_path) -> None:
    truths = {"NEW": truth(1, cash={pd.Timestamp("2025-02-10"): 0.5})}
    extra = [div("OTHER", "2025-01-08", 0.3)]
    src, snap = _raw_snapshot(tmp_path, truths, extra, ["NEW"])
    assert snap.raw and snap.tickers() == ["NEW"]
    stored = json.loads((snap.path / "actions" / "NEW.json").read_text())
    assert sorted(stored["actions"]) == ["NEW"]
    pd.testing.assert_frame_equal(snap.bars("NEW"), src.fetch("NEW", START, END))


def test_a_rule_failure_leaves_the_ticker_out_of_the_build_not_the_download(tmp_path) -> None:
    truths = {"AAA": truth(1), "BBB": truth(2)}
    _, snap = _raw_snapshot(tmp_path, truths, [div("BBB", "2025-02-10", 0.5, foreign=True)], ["AAA", "BBB"])
    assert snap.tickers() == ["AAA", "BBB"] and snap.manifest["failed"] == {}
    bars, failed = snap.read_all()
    assert sorted(bars) == ["AAA"] and failed["BBB"].startswith("WithholdingError")
