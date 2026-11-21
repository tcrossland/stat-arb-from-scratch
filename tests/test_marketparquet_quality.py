"""Tests for the quality report on MarketParquet's day files. Synthetic files and bars; no network, no real data."""

from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from statarb.config import load_config
from statarb.data import marketparquet as mp
from statarb.data import marketparquet_quality as mq

STOCK = "stock_daily"
DAYS = [d.date() for d in pd.bdate_range("2025-12-26", "2026-01-09")]
START, END = DAYS[2], DAYS[-2]     # two days before the sample, two from its end on
MANIFEST = {"source": mp.NAME, "basis": "split_adjusted", "digest": "0" * 64, "assets": [STOCK]}


def bars(rows: list[tuple]) -> pd.DataFrame:
    """Bars from (day, symbol, open, high, low, close, volume), as `read_days` returns them."""
    frame = pd.DataFrame(rows, columns=["date", "ticker", "open", "high", "low", "close", "volume"])
    frame["date"] = pd.to_datetime(frame["date"]).astype("datetime64[ns]")
    frame["asset_type"] = "Stock"
    return frame[mp.DAY_COLUMNS].sort_values(["date", "ticker"]).reset_index(drop=True)


def flat(day: str, symbol: str, price: float = 10.0, volume: float = 100.0) -> tuple:
    return day, symbol, price, price, price, price, volume


def day_file(day: dt.date, symbols: list[str], field: str = "date") -> bytes:
    stamp = pa.array([day] * len(symbols), pa.date32()) if field == "date" else pa.array(
        [dt.datetime.combine(day, dt.time())] * len(symbols), pa.timestamp("us")
    )
    table = pa.table({
        field: stamp, "symbol": symbols, "asset_type": ["Stock"] * len(symbols),
        "open": [10.0] * len(symbols), "high": [11.0] * len(symbols), "low": [9.0] * len(symbols),
        "close": [10.5] * len(symbols), "volume": [100.0] * len(symbols),
    })
    out = io.BytesIO()
    pq.write_table(table, out, compression="snappy")
    return out.getvalue()


def footer_only(data: bytes) -> bytes:
    """The file with everything but its footer zeroed: its schema and row count read, its rows do not."""
    footer = int.from_bytes(data[-8:-4], "little") + 8
    return data[:4] + bytes(len(data) - 4 - footer) + data[-footer:]


def write_snapshot(root: Path, files: dict[dt.date, bytes]) -> Path:
    for day, data in files.items():
        target = root / STOCK / str(day.year) / f"{day.isoformat()}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


def snapshot_files() -> dict[dt.date, bytes]:
    """Day files of which only those inside the sample can be read: earlier ones keep their footer alone,
    and those from the sample's end on are not parquet at all."""
    files = {}
    for day in DAYS:
        whole = day_file(day, ["AAA", f"BBB{mp.SUFFIX}", "CCC"], "timestamp" if day < START else "date")
        files[day] = footer_only(whole) if day < START else whole if day < END else b"not to be opened"
    return files


def report(path: Path, start: dt.date = START, end: dt.date = END) -> str:
    return mq.quality_report(path, MANIFEST, start, end, DAYS, [2, 3], 0.03)


def test_a_file_before_the_sample_gives_its_footer_and_one_from_its_end_on_is_not_opened(tmp_path) -> None:
    path = write_snapshot(tmp_path, snapshot_files())
    text = report(path)
    assert f"- Files: {len(DAYS)}, {DAYS[0]} to {DAYS[-1]}; not opened: 2" in text
    assert f"- In the sample: {3 * (len(DAYS) - 4)} bars of 3 symbols over {len(DAYS) - 4} sessions" in text
    facts = mq.file_facts(path, STOCK, END)
    assert list(facts["date"].dt.date) == DAYS[:-2] and (facts["rows"] == 3).all()
    assert list(mq.schemas(facts)["files"]) == [2, len(DAYS) - 4]       # the two vintages of the day's column
    assert report(path) == text


def test_the_fixture_would_catch_a_read_outside_the_sample(tmp_path) -> None:
    path = write_snapshot(tmp_path, snapshot_files())
    with pytest.raises(Exception):  # noqa: B017  whatever pyarrow raises on rows it cannot read
        report(path, start=DAYS[0])
    with pytest.raises(Exception):  # noqa: B017
        report(path, end=DAYS[-1])


def test_the_config_reads_no_day_of_the_forward_run_and_no_bar_before_2016() -> None:
    sample = load_config("marketparquet")["sample"]
    assert sample["start"] == dt.date(2016, 1, 1)
    assert sample["end"] <= load_config("paper")["run"]["first_session"]


def test_missing_sessions_and_files_on_other_days() -> None:
    missing, extra = mq.missing_sessions([DAYS[0], DAYS[2], dt.date(2026, 1, 3)], DAYS[:3])
    assert missing == [DAYS[1]] and extra == [dt.date(2026, 1, 3)]


def test_rows_by_year() -> None:
    facts = pd.DataFrame({"date": pd.to_datetime(["2025-12-30", "2025-12-31", "2026-01-02"]), "rows": [2, 5, 7], "schema": "s"})
    assert mq.rows_by_year(facts).to_dict("list") == {
        "year": [2025, 2026], "sessions": [2, 1], "fewest": [2, 7], "mean": [4, 7], "most": [5, 7],
    }


def test_suffix_share_counts_a_symbol_once_a_year_and_its_days() -> None:
    dead = f"BBB{mp.SUFFIX}"
    table = bars([flat("2025-12-30", "AAA"), flat("2025-12-31", "AAA"), flat("2025-12-31", dead), flat("2026-01-02", "AAA")])
    got = mq.suffix_share(table).set_index("year")
    assert got.loc[2025, ["symbols", "suffixed", "symbol_days", "suffixed_days"]].tolist() == [2, 1, 3, 1]
    assert got.loc[2025, "share_of_symbols"] == 0.5 and got.loc[2026, "share_of_symbol_days"] == 0.0


def test_bad_bars_counts_each_fault() -> None:
    table = bars([
        ("2026-01-02", "OK", 10.0, 11.0, 9.0, 10.5, 100.0),
        ("2026-01-02", "OPEN", 12.0, 11.0, 9.0, 10.5, 100.0),
        ("2026-01-02", "CLOSE", 10.0, 11.0, 9.0, 8.0, 0.0),
        ("2026-01-02", "RANGE", 10.0, 9.0, 11.0, 10.0, -1.0),
        ("2026-01-02", "NONE", float("nan"), 11.0, 9.0, 10.0, float("nan")),
        ("2026-01-02", "ZERO", 0.0, 11.0, 0.0, 10.0, 100.0),
    ])
    got = mq.bad_bars(table).iloc[0].to_dict()
    assert got == {
        "year": 2026, "bars": 6, "price_missing": 1, "price_not_positive": 1, "high_below_low": 1,
        "open_outside_range": 2, "close_outside_range": 2, "volume_zero": 1, "volume_missing_or_negative": 2,
    }


def test_a_move_is_from_a_symbols_previous_bar_and_is_sized_against_each_ratio() -> None:
    table = bars([
        flat("2026-01-02", "HALF", 10.0), flat("2026-01-05", "HALF", 5.1),       # a fall to about a half
        flat("2026-01-02", "TRIPLE", 10.0), flat("2026-01-06", "TRIPLE", 29.5),  # a rise to about three, across a gap
        flat("2026-01-02", "CALM", 10.0), flat("2026-01-05", "CALM", 10.4),
        flat("2026-01-02", "NEAR", 10.0), flat("2026-01-05", "NEAR", 5.4),       # outside the tolerance
    ])
    moves = mq.overnight_moves(table)
    assert len(moves) == 4 and set(moves["ticker"]) == {"HALF", "TRIPLE", "CALM", "NEAR"}
    sized = mq.split_sized(moves, [2, 3], 0.03)
    assert sorted(zip(sized["ticker"], sized["ratio"], sized["direction"], strict=True)) == [
        ("HALF", 2.0, "fall"), ("TRIPLE", 3.0, "rise"),
    ]
    assert mq.split_sized_by_ratio(sized, [2, 3]).to_dict("list") == {"ratio": ["2", "3"], "falls": [1, 0], "rises": [0, 1]}
    assert mq.split_sized_by_year(moves, sized).to_dict("list") == {"year": [2026], "moves": [4], "falls": [1], "rises": [1], "symbols": [2]}


def test_a_later_bar_changes_no_earlier_move() -> None:
    rows = [flat("2026-01-02", "AAA", 10.0), flat("2026-01-05", "AAA", 5.0), flat("2026-01-06", "AAA", 7.0)]
    changed = [*rows[:2], flat("2026-01-06", "AAA", 70.0)]
    first = mq.overnight_moves(bars(rows))
    assert mq.overnight_moves(bars(changed)).iloc[:1].equals(first.iloc[:1])


def test_absences_are_counted_in_the_tables_own_sessions() -> None:
    days = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    table = bars([
        *(flat(day, "ALWAYS") for day in days),
        flat(days[0], "ONE"), flat(days[2], "ONE"),                      # absent one session
        flat(days[0], f"ONE{mp.SUFFIX}"), flat(days[1], f"ONE{mp.SUFFIX}"),   # another security: no absence
        flat(days[0], "LONG"), flat(days[4], "LONG"),                    # absent three
        flat(days[3], "LATE"), flat(days[4], "LATE"),                    # listed late: no absence
    ])
    gone = mq.absences(table).sort_values("ticker").reset_index(drop=True)
    assert gone["ticker"].tolist() == ["LONG", "ONE"] and gone["sessions"].tolist() == [3, 1]
    assert (gone["left"] == pd.Timestamp(days[0])).all()
    by_length = mq.absences_by_length(gone).set_index("sessions_absent")
    assert by_length["absences"].to_dict() == {"1": 1, "2 to 5": 1, "6 to 20": 0, "21 to 250": 0, "over 250": 0}
    assert mq.absences_by_year(gone).to_dict("list") == {"year": [2026], "absences": [2], "symbols": [2]}


def test_calendar_sessions_are_the_exchanges_in_a_half_open_range() -> None:
    got = mq.calendar_sessions("XNYS", dt.date(2025, 12, 24), dt.date(2025, 12, 30))
    assert got == [dt.date(2025, 12, 24), dt.date(2025, 12, 26), dt.date(2025, 12, 29)]
