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
    Corrections,
    MissingCredentialsError,
    NetPeriod,
    Rules,
    Withholding,
    WithholdingError,
    parse_withholding,
)
from statarb.data.build import download_prices
from statarb.data.snapshot import PriceSnapshot

DATES = pd.bdate_range("2025-01-02", "2025-02-28")
START, END = dt.date(2025, 1, 1), dt.date(2025, 3, 1)
NONE = Withholding({}, frozenset())


NO_CORRECTIONS = Corrections()


def source(get, withholding: Withholding = NONE, corrections: Corrections = NO_CORRECTIONS) -> AlpacaSource:
    return AlpacaSource(Rules(withholding, corrections), get=get)


def truth(seed: int = 1, **kwargs) -> pd.DataFrame:
    return synthetic_truth(DATES, seed, **kwargs)


def div(symbol: str, ex: str, rate: float, foreign: bool = False, rid: str | None = None, **extra) -> tuple[str, dict]:
    processed = (dt.date.fromisoformat(ex) + dt.timedelta(days=20)).isoformat()
    rec = {"id": rid or f"{symbol}-{ex}-{rate}", "symbol": symbol, "ex_date": ex, "process_date": processed,
           "rate": rate, "foreign": foreign, **extra}
    return "cash_dividends", rec


def rename(old: str, new: str, day: str) -> tuple[str, dict]:
    return "name_changes", {"id": f"{old}-{new}", "old_symbol": old, "new_symbol": new, "process_date": day}


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


def _spin(parent: str, child: str, ex: str, rate: float, source_rate: float = 1, **extra) -> tuple[str, dict]:
    return "spin_offs", {"id": f"{parent}-{child}", "source_symbol": parent, "source_rate": source_rate, "new_symbol": child,
                         "new_rate": rate, "ex_date": ex, "process_date": ex, **extra}


def test_spin_off_is_cash_at_the_new_security_close() -> None:
    parent, child = truth(1), truth(2, price=20.0)
    bars = source(fake_alpaca({"PAR": parent, "KID": child}, extra=[_spin("PAR", "KID", "2025-02-03", 0.5)])).fetch("PAR", START, END)
    kid_close = float(child.loc[child["date"] == pd.Timestamp("2025-02-03"), "close"].iloc[0])
    assert cash_on(bars, "2025-02-03") == pytest.approx(0.5 * kid_close)


def test_spin_off_uses_first_close_after_ex_date_and_fails_without_one() -> None:
    child = truth(2, price=20.0)
    child = child.loc[child["date"] >= pd.Timestamp("2025-02-05")]
    spin = _spin("PAR", "KID", "2025-02-03", 1, source_rate=2)
    bars = source(fake_alpaca({"PAR": truth(1), "KID": child}, extra=[spin])).fetch("PAR", START, END)
    assert cash_on(bars, "2025-02-03") == pytest.approx(0.5 * float(child["close"].iloc[0]))
    with pytest.raises(alpaca.SpinOffPriceError):
        source(fake_alpaca({"PAR": truth(1)}, extra=[spin])).fetch("PAR", START, END)


def test_spin_off_with_a_split_on_its_ex_date_is_per_share_before_the_split() -> None:
    # 0.5 of a new security per share held at the record date, and a one-for-two reverse split the same day.
    parent, child = truth(1), truth(2, price=20.0)
    split = ("reverse_splits", {"id": "rs", "symbol": "PAR", "ex_date": "2025-02-03", "process_date": "2025-02-03",
                                "old_rate": 2, "new_rate": 1})
    get = fake_alpaca({"PAR": parent, "KID": child}, extra=[_spin("PAR", "KID", "2025-02-03", 0.5), split])
    bars = source(get).fetch("PAR", START, END)
    kid_close = float(child.loc[child["date"] == pd.Timestamp("2025-02-03"), "close"].iloc[0])
    day = bars.loc[bars["date"] == pd.Timestamp("2025-02-03")].iloc[0]
    assert day["split_ratio"] == 0.5
    # One old share is half a new share plus 0.5 KID: split_ratio * (close + cash) must equal that.
    assert day["split_ratio"] * (day["close"] + day["cash"]) == pytest.approx(0.5 * day["close"] + 0.5 * kid_close)


def test_spin_off_search_reaches_past_the_payable_date() -> None:
    # Ex-date on the record date, distribution 17 days later, and no when-issued trading.
    child = truth(2, price=20.0)
    child = child.loc[child["date"] >= pd.Timestamp("2025-02-20")]
    spin = _spin("PAR", "KID", "2025-02-03", 0.5, payable_date="2025-02-20")
    bars = source(fake_alpaca({"PAR": truth(1), "KID": child}, extra=[spin])).fetch("PAR", START, END)
    assert cash_on(bars, "2025-02-03") == pytest.approx(0.5 * float(child["close"].iloc[0]))


def test_action_on_a_date_without_a_bar_fails() -> None:
    sparse = truth().drop(index=[5])
    missing = sparse["date"].min() + pd.tseries.offsets.BDay(5)
    rec = div("XYZ", missing.date().isoformat(), 0.4)
    with pytest.raises(alpaca.ActionDateError):
        source(fake_alpaca({"XYZ": sparse}, extra=[rec])).fetch("XYZ", START, END)


def test_repeated_records_are_kept_once() -> None:
    same_id = div("XYZ", "2025-02-03", 0.4, rid="one")
    regular, special = div("XYZ", "2025-02-10", 90.0, rid="a", special=False), div("XYZ", "2025-02-10", 90.0, rid="b", special=True)
    bars = source(fake_alpaca({"XYZ": truth()}, extra=[same_id, same_id, regular, special])).fetch("XYZ", START, END)
    assert cash_on(bars, "2025-02-03") == 0.4 and cash_on(bars, "2025-02-10") == 90.0


def test_a_dividend_filed_under_two_cusips_is_kept_once() -> None:
    old, new = div("XYZ", "2025-02-10", 1.06, rid="a", cusip="111"), div("XYZ", "2025-02-10", 1.06, rid="b", cusip="222")
    bars = source(fake_alpaca({"XYZ": truth()}, extra=[old, new])).fetch("XYZ", START, END)
    assert cash_on(bars, "2025-02-10") == 1.06


def test_actions_follow_renames_and_drop_a_reused_symbol() -> None:
    # The ticker took NEW on 2025-02-01. Before that, NEW was another security's symbol, and the ticker's
    # actions were filed under OLD; after it, OLD's actions belong to no one we hold.
    recs = [
        rename("OLD", "NEW", "2025-02-01"),
        div("OLD", "2025-01-15", 0.3),
        div("OLD", "2025-02-12", 9.9),
        div("NEW", "2025-01-20", 0.05),
        div("NEW", "2025-02-14", 0.35),
    ]
    bars = source(fake_alpaca({"NEW": truth()}, extra=recs)).fetch("NEW", START, END)
    paid = bars.loc[bars["cash"] > 0, ["date", "cash"]]
    assert paid["date"].dt.strftime("%Y-%m-%d").tolist() == ["2025-01-15", "2025-02-14"]
    assert paid["cash"].tolist() == [0.3, 0.35]


def test_a_ticker_can_hold_a_symbol_twice() -> None:
    # XYZ became ABC on 2025-02-01 and took XYZ back on 2025-02-15.
    recs = [
        rename("XYZ", "ABC", "2025-02-01"),
        rename("ABC", "XYZ", "2025-02-15"),
        div("XYZ", "2025-01-15", 0.1),
        div("ABC", "2025-02-05", 0.2),
        div("XYZ", "2025-02-20", 0.3),
    ]
    bars = source(fake_alpaca({"XYZ": truth()}, extra=recs)).fetch("XYZ", START, END)
    assert bars.loc[bars["cash"] > 0, "cash"].tolist() == [0.1, 0.2, 0.3]


# Withholding -------------------------------------------------------------------------------------------


def test_foreign_dividends_are_grossed_up_only_in_net_periods() -> None:
    w = Withholding({"XYZ": (NetPeriod(0.25, dt.date(2025, 2, 1), None, frozenset({dt.date(2025, 2, 20)})),)}, frozenset())
    recs = [div("XYZ", "2025-01-15", 1.0, foreign=True), div("XYZ", "2025-02-10", 0.75, foreign=True),
            div("XYZ", "2025-02-20", 1.0, foreign=True), div("XYZ", "2025-02-24", 0.5)]
    bars = source(fake_alpaca({"XYZ": truth()}, extra=recs), w).fetch("XYZ", START, END)
    assert [cash_on(bars, d) for d in ["2025-01-15", "2025-02-10", "2025-02-20", "2025-02-24"]] == [1.0, 1.0, 1.0, 0.5]


def test_foreign_dividend_for_an_unlisted_ticker_fails() -> None:
    rec = div("XYZ", "2025-02-10", 0.75, foreign=True)
    with pytest.raises(WithholdingError, match="alpaca.toml"):
        source(fake_alpaca({"XYZ": truth()}, extra=[rec])).fetch("XYZ", START, END)
    gross = Withholding({}, frozenset({"XYZ"}))
    bars = source(fake_alpaca({"XYZ": truth()}, extra=[rec]), gross).fetch("XYZ", START, END)
    assert cash_on(bars, "2025-02-10") == 0.75


def test_parse_withholding_validates() -> None:
    entry = {"ticker": "XYZ", "country": "Ireland", "rate": 0.25, "start": dt.date(2023, 1, 1), "source": "s"}
    parsed = parse_withholding({"net": [entry], "gross": ["ABC"]})
    assert parsed.net["XYZ"][0].rate == 0.25 and parsed.gross == frozenset({"ABC"})
    with pytest.raises(ValueError, match="lacks"):
        parse_withholding({"net": [{k: v for k, v in entry.items() if k != "source"}]})
    with pytest.raises(ValueError, match="both"):
        parse_withholding({"net": [entry], "gross": ["XYZ"]})
    with pytest.raises(ValueError, match="overlap"):
        parse_withholding({"net": [entry, {**entry, "start": dt.date(2024, 1, 1)}]})
    with pytest.raises(ValueError, match="rate"):
        parse_withholding({"net": [{**entry, "rate": 1.0}]})


def test_repository_rules_parse_and_cite_their_sources() -> None:
    from statarb.config import load_config

    cfg = load_config("alpaca")
    rules = alpaca.parse_rules(cfg)
    assert "ACN" in rules.withholding.net and "LIN" in rules.withholding.gross
    assert ("F", dt.date(2025, 2, 18)) in rules.corrections.repeats
    assert rules.corrections.drops and rules.corrections.added
    for section in ("net", "repeat", "drop", "add"):
        for entry in cfg.get(section, []):
            assert entry["source"].startswith("https://"), (section, entry)


def test_listed_repeats_are_separate_dividends() -> None:
    regular, supplemental = div("XYZ", "2025-02-10", 0.15, rid="a", special=False), div("XYZ", "2025-02-10", 0.15, rid="b", special=True)
    get = fake_alpaca({"XYZ": truth()}, extra=[regular, supplemental])
    listed = source(get, corrections=Corrections(repeats=frozenset({("XYZ", dt.date(2025, 2, 10))}))).fetch("XYZ", START, END)
    assert cash_on(listed, "2025-02-10") == pytest.approx(0.30)
    assert cash_on(source(get).fetch("XYZ", START, END), "2025-02-10") == 0.15
    with pytest.raises(ValueError, match="lacks"):
        alpaca.parse_repeats({"repeat": [{"symbol": "F", "ex_date": dt.date(2025, 2, 18)}]})


# Hand-listed corrections -------------------------------------------------------------------------------

SOURCE = {"note": "n", "source": "s"}


def corrections(**sections) -> Corrections:
    return alpaca.parse_corrections(sections)


def test_listed_drops_remove_only_the_matching_record() -> None:
    recs = [div("XYZ", "2025-02-10", 0.5), div("XYZ", "2025-02-10", 1.0625, rid="pref"), div("XYZ", "2025-02-20", 1.0625)]
    fixes = corrections(drop=[{"symbol": "XYZ", "kind": "cash_dividends", "ex_date": dt.date(2025, 2, 10), "rate": 1.0625, **SOURCE}])
    bars = source(fake_alpaca({"XYZ": truth()}, extra=recs), corrections=fixes).fetch("XYZ", START, END)
    assert cash_on(bars, "2025-02-10") == 0.5 and cash_on(bars, "2025-02-20") == 1.0625


def test_one_entry_can_correct_several_ex_dates() -> None:
    # A base and a variable part: the source files the base alone on one date and beside the total on another.
    recs = [div("XYZ", "2025-02-03", 0.075), div("XYZ", "2025-02-10", 0.075, rid="b"), div("XYZ", "2025-02-10", 0.15)]
    days = [dt.date(2025, 2, 3), dt.date(2025, 2, 10)]
    fixes = corrections(
        drop=[{"symbol": "XYZ", "kind": "cash_dividends", "ex_dates": days, "rate": 0.075, **SOURCE}],
        add=[{"symbol": "XYZ", "kind": "cash_dividends", "ex_dates": days[:1], "rate": 0.15, **SOURCE}],
    )
    bars = source(fake_alpaca({"XYZ": truth()}, extra=recs), corrections=fixes).fetch("XYZ", START, END)
    assert cash_on(bars, "2025-02-03") == 0.15 and cash_on(bars, "2025-02-10") == 0.15


def test_listed_dividends_are_added_gross_under_the_symbol_of_their_time() -> None:
    fixes = corrections(
        add=[{"symbol": "OLD", "kind": "cash_dividends", "ex_date": dt.date(2025, 1, 15), "rate": 4.0, **SOURCE}],
    )
    get = fake_alpaca({"XYZ": truth()}, extra=[rename("OLD", "XYZ", "2025-02-01")])
    bars = source(get, corrections=fixes).fetch("XYZ", START, END)
    assert cash_on(bars, "2025-01-15") == 4.0


def test_listed_spin_off_is_cash_from_the_parents_basis_share() -> None:
    parent = truth(1)
    fixes = corrections(add=[{"symbol": "PAR", "kind": "spin_offs", "ex_date": dt.date(2025, 2, 3), "parent_basis": 0.8, **SOURCE}])
    bars = source(fake_alpaca({"PAR": parent}), corrections=fixes).fetch("PAR", START, END)
    close = float(parent.loc[parent["date"] == pd.Timestamp("2025-02-03"), "close"].iloc[0])
    assert cash_on(bars, "2025-02-03") == pytest.approx(close * 0.25)


def test_listed_spin_off_without_a_basis_share_is_valued_at_the_new_security_close() -> None:
    parent, child = truth(1), truth(2, price=20.0)
    fixes = corrections(add=[{"symbol": "PAR", "kind": "spin_offs", "ex_date": dt.date(2025, 2, 3),
                              "new_symbol": "KID", "new_rate": 0.1, **SOURCE}])
    bars = source(fake_alpaca({"PAR": parent, "KID": child}), corrections=fixes).fetch("PAR", START, END)
    kid_close = float(child.loc[child["date"] == pd.Timestamp("2025-02-03"), "close"].iloc[0])
    assert cash_on(bars, "2025-02-03") == pytest.approx(0.1 * kid_close)


def test_parse_corrections_validates() -> None:
    entry = {"symbol": "XYZ", "kind": "cash_dividends", "ex_date": dt.date(2025, 2, 10), "rate": 0.5, **SOURCE}
    with pytest.raises(ValueError, match="lacks"):
        corrections(add=[{k: v for k, v in entry.items() if k != "source"}])
    with pytest.raises(ValueError, match="lacks"):
        corrections(add=[{k: v for k, v in entry.items() if k != "rate"}])
    with pytest.raises(ValueError, match="kind"):
        corrections(add=[{**entry, "kind": "forward_splits"}])
    with pytest.raises(ValueError, match="parent_basis"):
        corrections(add=[{**entry, "kind": "spin_offs", "parent_basis": 1.2}])
    with pytest.raises(ValueError, match="exactly one"):
        corrections(drop=[{"symbol": "XYZ", "kind": "cash_dividends", **SOURCE}])
    with pytest.raises(ValueError, match="exactly one"):
        corrections(add=[{**entry, "ex_dates": [dt.date(2025, 2, 11)]}])


# Raw snapshots: the download keeps what Alpaca returned, the build applies the rules ----------------------


def _raw_snapshot(tmp_path, truths, extra, tickers):
    src = source(fake_alpaca(truths, extra=extra))
    path = download_prices(src, tmp_path / "raw", tickers, START, END, 0.0, 0)
    return src, PriceSnapshot.open(path)


def test_a_raw_snapshot_reads_as_the_adapter_fetches(tmp_path) -> None:
    truths = {"NEW": truth(1, cash={pd.Timestamp("2025-02-10"): 0.5}), "KID": truth(2, price=20.0)}
    extra = [rename("OLD", "NEW", "2025-01-20"), div("OLD", "2025-01-08", 0.3), _spin("NEW", "KID", "2025-02-03", 0.25)]
    src, snap = _raw_snapshot(tmp_path, truths, extra, ["NEW"])
    assert snap.raw and snap.tickers() == ["NEW"]
    stored = json.loads((snap.path / "actions" / "NEW.json").read_text())
    assert sorted(stored["actions"]) == ["NEW", "OLD"]                    # every symbol the ticker has held
    assert [f["symbol"] for f in stored["spin_off_bars"]] == ["KID"]
    pd.testing.assert_frame_equal(snap.bars("NEW", Rules(NONE)), src.fetch("NEW", START, END))


def test_a_correction_listed_after_the_download_needs_only_a_rebuild(tmp_path) -> None:
    truths = {"XYZ": truth(1, cash={pd.Timestamp("2025-02-10"): 0.5})}
    _, snap = _raw_snapshot(tmp_path, truths, [], ["XYZ"])
    rules = Rules(NONE, corrections(drop=[{"symbol": "XYZ", "kind": "cash_dividends", "ex_date": dt.date(2025, 2, 10), **SOURCE}],
                                    add=[{"symbol": "XYZ", "kind": "cash_dividends", "ex_date": dt.date(2025, 2, 11), "rate": 0.4, **SOURCE}]))
    bars = snap.bars("XYZ", rules)
    assert cash_on(bars, "2025-02-10") == 0.0 and cash_on(bars, "2025-02-11") == 0.4


def test_a_spin_off_listed_after_the_download_fails_the_ticker_until_the_next(tmp_path) -> None:
    truths = {"XYZ": truth(1), "KID": truth(2, price=20.0)}
    _, snap = _raw_snapshot(tmp_path, truths, [], ["XYZ"])
    spun = Rules(NONE, corrections(add=[{"symbol": "XYZ", "kind": "spin_offs", "ex_date": dt.date(2025, 2, 3),
                                         "new_symbol": "KID", "new_rate": 0.1, **SOURCE}]))
    bars, failed = snap.read_all(spun)
    assert bars == {} and failed["XYZ"].startswith("MissingRawError")


def test_a_rule_failure_leaves_the_ticker_out_of_the_build_not_the_download(tmp_path) -> None:
    truths = {"AAA": truth(1), "BBB": truth(2)}
    _, snap = _raw_snapshot(tmp_path, truths, [div("BBB", "2025-02-10", 0.5, foreign=True)], ["AAA", "BBB"])
    assert snap.tickers() == ["AAA", "BBB"] and snap.manifest["failed"] == {}
    bars, failed = snap.read_all(Rules(NONE))
    assert sorted(bars) == ["AAA"] and failed["BBB"].startswith("WithholdingError")
    gross = Withholding({}, frozenset({"BBB"}))
    assert sorted(snap.read_all(Rules(gross))[0]) == ["AAA", "BBB"]
