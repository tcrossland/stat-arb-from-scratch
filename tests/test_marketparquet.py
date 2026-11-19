"""MarketParquet adapter (decision record 0008), on synthetic day files with the network blocked."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import threading
import time
import urllib.error
import urllib.parse
from email.message import Message

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from statarb.config import load_config
from statarb.data import cache, marketparquet_build
from statarb.data import marketparquet as mp
from statarb.data.snapshot import PriceSnapshot
from statarb.paper import frozen

STOCK, ETF = "stock_daily", "etf_daily"
DAYS = [d.date() for d in pd.bdate_range("2025-12-29", "2026-01-07")]   # spans a year end
START, END = DAYS[0], DAYS[-1]
TODAY = END + dt.timedelta(days=1)
STORAGE = "https://files.example.invalid"
LONG_AGO = dt.datetime(2026, 1, 8, 3, 0, tzinfo=dt.UTC)


def day_bytes(day: dt.date, symbols: list[str], kind: str = "Stock", field: str = "date") -> bytes:
    """A synthetic day file in the archive's schema, with the day in the column of either vintage."""
    rng = np.random.default_rng(day.toordinal())
    close = rng.uniform(10, 100, len(symbols))
    stamp = pa.array([day] * len(symbols), pa.date32()) if field == "date" else pa.array(
        [dt.datetime.combine(day, dt.time())] * len(symbols), pa.timestamp("us")
    )
    table = pa.table({
        field: stamp,
        "symbol": symbols,
        "asset_type": [kind] * len(symbols),
        "open": close * 0.99,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "volume": rng.integers(1_000, 9_000, len(symbols)).astype("float64"),
    })
    out = io.BytesIO()
    pq.write_table(table, out, compression="snappy")
    return out.getvalue()


SYMBOLS = {STOCK: ["AAA", "BBB-DELISTED", "BRK.B"], ETF: ["SPY", "XLK"]}
KINDS = {STOCK: "Stock", ETF: "ETF"}
# The stock files change vintage part way through, as the archive's do.
FILES = {
    (asset, day): day_bytes(day, SYMBOLS[asset], KINDS[asset], "timestamp" if day.year == 2025 else "date")
    for asset in (STOCK, ETF)
    for day in DAYS
}


class FakeArchive:
    """Serves `files` as the archive does: a list per dataset and range, and each file at its address."""

    def __init__(self, files: dict[tuple[str, dt.date], bytes], sizes: dict[tuple[str, dt.date], int] | None = None) -> None:
        self.files, self.sizes = files, sizes or {}
        self.listings: list[tuple[str, dt.date, dt.date]] = []
        self.fetched: list[str] = []
        self.modified: dict[tuple[str, dt.date], dt.datetime] = {}
        self.etags: dict[tuple[str, dt.date], str | None] = {}      # where not the file's MD5

    def listing(self, asset: str, start: dt.date, end: dt.date) -> dict:
        self.listings.append((asset, start, end))
        found = sorted(day for a, day in self.files if a == asset and start <= day <= end)
        return {
            "asset_type": asset,
            "file_count": len(found),
            "files": [
                {
                    "date": day.isoformat(),
                    "filename": f"{asset}_{day}.parquet",
                    "file_size_bytes": self.sizes.get((asset, day), len(self.files[asset, day])),
                    "download_url": f"{STORAGE}/{asset}/{day}.parquet?signature=x",
                }
                for day in found
            ],
        }

    def file(self, url: str) -> mp.Served:
        self.fetched.append(url)
        asset, name = urllib.parse.urlsplit(url).path.strip("/").split("/")
        key = asset, dt.date.fromisoformat(name.removesuffix(".parquet"))
        etag = self.etags.get(key, hashlib.md5(self.files[key]).hexdigest())
        return mp.Served(self.files[key], etag, self.modified.get(key, LONG_AGO))


class Response(io.BytesIO):
    def __init__(self, body: bytes, **headers: str) -> None:
        super().__init__(body)
        self.headers = Message()
        for name, value in headers.items():
            self.headers[name.replace("_", "-")] = value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code: int, retry_after: str | None = None, detail: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    body = None if detail is None else io.BytesIO(json.dumps({"detail": detail}).encode())
    return urllib.error.HTTPError("https://x", code, "error", headers, body)


def snapshot(tmp_path, files=FILES, **kwargs) -> tuple:
    archive = FakeArchive(files, **kwargs)
    return archive, mp.download(archive, tmp_path, [STOCK, ETF], START, END, TODAY)


# Requests ----------------------------------------------------------------------------------------------


def test_file_list_address_is_on_the_api_host() -> None:
    url = urllib.parse.urlsplit(mp.manifest_url(STOCK, dt.date(2024, 1, 1), dt.date(2024, 12, 31)))
    assert (url.scheme, url.netloc, url.path) == ("https", "marketparquet.com", "/api/v1/manifest/stock_daily")
    assert urllib.parse.parse_qs(url.query) == {"start": ["2024-01-01"], "end": ["2024-12-31"]}


@pytest.mark.parametrize("asset", ["stock_1min", "etf_30min", "futures_daily", "stock_daily/../futures_daily"])
def test_only_the_daily_stock_and_etf_datasets_are_ever_asked_for(asset: str) -> None:
    with pytest.raises(ValueError, match="decision record 0008"):
        mp.manifest_url(asset, START, END)


def test_configured_datasets_are_the_ones_the_adapter_allows() -> None:
    assert set(load_config("marketparquet")["source"]["assets"]) <= set(mp.ASSETS)


def test_the_source_config_is_outside_the_frozen_record() -> None:
    assert mp.NAME not in frozen.FILES


def test_missing_key_fails_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(mp.MissingCredentialsError, match=mp.KEY_ENV):
        mp.key_from_env({})
    monkeypatch.delenv(mp.KEY_ENV, raising=False)
    with pytest.raises(mp.MissingCredentialsError):
        mp.Client(opener=lambda *a, **k: pytest.fail("no request expected"))


def test_the_key_goes_to_the_api_and_never_to_a_file_address() -> None:
    seen = []

    def opener(request, timeout):
        seen.append(request)
        body = json.dumps({"asset_type": STOCK, "file_count": 0, "files": []}).encode() if "api/v1" in request.full_url else b"bytes"
        return Response(body)

    client = mp.Client(key="test-key", opener=opener, clock=lambda: 0.0, sleep=lambda s: None, min_interval=0.0)
    client.listing(STOCK, START, END)
    assert client.file(f"{STORAGE}/a.parquet?signature=x").data == b"bytes"
    api, storage = seen
    assert api.full_url.startswith(mp.HOST + mp.MANIFEST) and api.get_header("Authorization") == "Bearer test-key"
    assert storage.get_header("Authorization") is None and "test-key" not in storage.full_url
    assert all(r.get_header("User-agent") == mp.USER_AGENT for r in seen)


def test_a_file_comes_with_what_the_storage_host_said_of_it() -> None:
    def client(**headers: str) -> mp.Client:
        return mp.Client(key="k", opener=lambda r, timeout: Response(b"x", **headers), clock=lambda: 0.0, sleep=lambda s: None)

    got = client(ETag='"0123abcd"', Last_Modified="Wed, 18 Nov 2026 03:12:45 GMT").file(f"{STORAGE}/a")
    assert got == mp.Served(b"x", "0123abcd", dt.datetime(2026, 11, 18, 3, 12, 45, tzinfo=dt.UTC))
    assert client().file(f"{STORAGE}/a") == mp.Served(b"x", None, None)
    assert client(Last_Modified="yesterday").file(f"{STORAGE}/a").modified is None


def test_a_file_address_must_be_https() -> None:
    client = mp.Client(key="k", opener=lambda *a, **k: pytest.fail("no request expected"))
    with pytest.raises(mp.ArchiveError):
        client.file("http://files.example.invalid/a.parquet")


def test_requests_are_paced_and_a_rate_limit_waits_as_long_as_asked() -> None:
    now, slept, answers = [0.0], [], [http_error(429, "7"), http_error(503), Response(b"ok"), Response(b"ok")]

    def opener(request, timeout):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    client = mp.Client(key="k", opener=opener, clock=lambda: now[0], sleep=sleep, min_interval=0.5)
    assert client.file(f"{STORAGE}/a").data == b"ok" and client.file(f"{STORAGE}/b").data == b"ok"
    assert slept == [7.0, 20.0, 0.5]     # the wait the server names, a growing one when it names none, then the pace


def test_requests_from_several_threads_share_one_pace() -> None:
    slept: list[float] = []
    client = mp.Client(key="k", opener=lambda r, timeout: Response(b"ok"), clock=lambda: 0.0, sleep=slept.append, min_interval=0.5)
    threads = [threading.Thread(target=client.file, args=(f"{STORAGE}/{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(slept) == [0.5, 1.0, 1.5]     # at one instant, each request after the first waits for its own slot


def refusing(code: int, detail: str | None) -> tuple[mp.Client, list]:
    calls = []

    def opener(request, timeout):
        calls.append(request)
        raise http_error(code, detail=detail)

    return mp.Client(key="k", opener=opener, clock=lambda: 0.0, sleep=lambda s: None, min_interval=0.0), calls


@pytest.mark.parametrize(("code", "detail", "said"), [
    (401, "Not authenticated", "HTTP 401: Not authenticated"),
    (403, "Requested range is entirely outside your plan's access window.", "HTTP 403: Requested range"),
    (404, "Not Found", "HTTP 404: Not Found"),
    (403, None, "HTTP 403: error"),
])
def test_a_refusal_is_not_retried_and_says_why(code: int, detail: str | None, said: str) -> None:
    client, calls = refusing(code, detail)
    with pytest.raises(mp.RefusedError, match=said):
        client.listing(STOCK, START, END)
    assert len(calls) == 1


def test_a_range_with_no_session_is_an_empty_list() -> None:
    client, _ = refusing(404, mp.NO_FILES)
    holiday = dt.date(2026, 1, 1)
    assert mp.day_files(client.listing(STOCK, holiday, holiday), STOCK, holiday, holiday) == []


def test_a_range_is_cut_into_calendar_years() -> None:
    assert mp.year_ranges(dt.date(2024, 3, 5), dt.date(2026, 2, 10)) == [
        (dt.date(2024, 3, 5), dt.date(2024, 12, 31)),
        (dt.date(2025, 1, 1), dt.date(2025, 12, 31)),
        (dt.date(2026, 1, 1), dt.date(2026, 2, 10)),
    ]


def _listing(**changes) -> dict:
    return {**FakeArchive(FILES).listing(STOCK, START, END), **changes}


def test_a_file_list_that_is_not_what_was_asked_for_is_refused() -> None:
    good = _listing()
    assert [f.day for f in mp.day_files(good, STOCK, START, END)] == DAYS
    entry = good["files"][0]
    for bad in (
        _listing(asset_type="stock_1min"),
        _listing(file_count=len(DAYS) + 1),
        _listing(files=[*good["files"][1:], good["files"][1]]),
        _listing(files=[{**entry, "date": "2025-12-01"}, *good["files"][1:]]),
        _listing(files=[{**entry, "download_url": "http://files.example.invalid/x"}, *good["files"][1:]]),
        _listing(file_count=mp.MAX_FILES, files=[entry] * mp.MAX_FILES),
    ):
        with pytest.raises(mp.ArchiveError):
            mp.day_files(bad, STOCK, START, END)


# Download ----------------------------------------------------------------------------------------------


def test_a_download_keeps_every_file_as_served_and_asks_once_a_year(tmp_path) -> None:
    lines: list[str] = []
    archive = FakeArchive(FILES)
    path = mp.download(archive, tmp_path, [STOCK, ETF], START, END, TODAY, log=lines.append)
    assert path == tmp_path / "marketparquet" / TODAY.isoformat() and cache.is_complete(path)
    assert [line.split(":")[0] for line in lines] == [
        f"1/4 {STOCK} 2025", f"2/4 {STOCK} 2026", f"3/4 {ETF} 2025", f"4/4 {ETF} 2026"
    ]
    assert lines[0].endswith(f"{sum(d.year == 2025 for d in DAYS)} files, 0.0 MB")
    for (asset, day), data in FILES.items():
        assert (path / asset / str(day.year) / f"{day}.parquet").read_bytes() == data
    assert archive.listings == [(a, *r) for a in (STOCK, ETF) for r in mp.year_ranges(START, END)]
    assert len(archive.fetched) == len(FILES)
    manifest = cache.read_manifest(path)
    assert (manifest["source"], manifest["layout"], manifest["basis"]) == ("marketparquet", "days", "split_adjusted")
    assert (manifest["start"], manifest["end_exclusive"]) == (START.isoformat(), TODAY.isoformat())
    assert manifest["days"][STOCK] == {"files": len(DAYS), "first": START.isoformat(), "last": END.isoformat()}
    assert len(manifest["files"]) == len(FILES)
    assert cache.select_snapshot(tmp_path, mp.NAME, TODAY.isoformat(), manifest["digest"]) == path


class CountingArchive(FakeArchive):
    """Records how many fetches were under way at once."""

    def __init__(self, files) -> None:
        super().__init__(files)
        self.lock, self.under_way, self.most = threading.Lock(), 0, 0

    def file(self, url: str) -> mp.Served:
        with self.lock:
            self.under_way += 1
            self.most = max(self.most, self.under_way)
        time.sleep(0.05)     # long enough for the other workers to start theirs
        with self.lock:
            self.under_way -= 1
        return super().file(url)


@pytest.mark.parametrize("workers", [1, 3])
def test_files_are_fetched_as_many_at_once_as_asked_and_kept_in_place(tmp_path, workers: int) -> None:
    archive = CountingArchive(FILES)
    path = mp.download(archive, tmp_path, [STOCK, ETF], START, END, TODAY, workers=workers)
    assert archive.most == workers
    for (asset, day), data in FILES.items():
        assert (path / asset / str(day.year) / f"{day}.parquet").read_bytes() == data


def test_a_failed_fetch_stops_the_rest(tmp_path) -> None:
    class Failing(FakeArchive):
        def file(self, url: str) -> mp.Served:
            super().file(url)
            raise mp.RefusedError(403, "Request has expired")

    archive = Failing(FILES)
    with pytest.raises(mp.RefusedError, match="expired"):
        mp.download(archive, tmp_path, [STOCK, ETF], START, END, TODAY, workers=1)
    assert len(archive.fetched) <= 2 and cache.complete_snapshots(tmp_path, mp.NAME) == []


def test_the_manifest_keeps_each_files_etag_and_lists_those_modified_during_the_download(tmp_path) -> None:
    archive = FakeArchive(FILES)
    late = (ETF, DAYS[3])
    archive.modified[late] = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
    path = mp.download(archive, tmp_path, [STOCK, ETF], START, END, TODAY, workers=2)
    manifest = cache.read_manifest(path)
    assert set(manifest["served"]) == set(manifest["files"])
    name = f"{STOCK}/{START.year}/{START}.parquet"
    assert manifest["served"][name] == {
        "etag": hashlib.md5(FILES[STOCK, START]).hexdigest(), "last_modified": LONG_AGO.isoformat(), "md5_checked": True,
    }
    assert manifest["modified_during_download"] == [f"{ETF}/{DAYS[3].year}/{DAYS[3]}.parquet"]
    assert manifest["started_at"] <= manifest["downloaded_at"]
    assert "warning: the archive modified 1 files" in marketparquet_build.describe(path)


def test_a_file_whose_bytes_are_not_those_of_its_etag_fails_the_download(tmp_path) -> None:
    archive = FakeArchive(FILES)
    archive.etags[STOCK, DAYS[1]] = hashlib.md5(b"what the host holds").hexdigest()
    with pytest.raises(mp.ArchiveError, match="MD5"):
        mp.download(archive, tmp_path, [STOCK, ETF], START, END, TODAY, retries=2)
    assert sum(url.startswith(f"{STORAGE}/{STOCK}/{DAYS[1]}") for url in archive.fetched) == 3
    assert cache.complete_snapshots(tmp_path, mp.NAME) == []


def test_an_etag_that_is_not_an_md5_is_recorded_and_not_checked(tmp_path) -> None:
    assert mp.Served(b"x", hashlib.md5(b"x").hexdigest()).intact is True
    assert mp.Served(b"x", hashlib.md5(b"y").hexdigest()).intact is False
    assert mp.Served(b"x", "0123456789abcdef0123456789abcdef-4").intact is None and mp.Served(b"x").intact is None
    archive = FakeArchive(FILES)
    archive.etags[ETF, DAYS[0]] = "0123456789abcdef0123456789abcdef-4"      # the form of an upload in parts
    archive.etags[ETF, DAYS[1]] = None
    path = mp.download(archive, tmp_path, [STOCK, ETF], START, END, TODAY)
    served = cache.read_manifest(path)["served"]
    assert [name for name, s in served.items() if not s["md5_checked"]] == [
        f"{ETF}/{d.year}/{d}.parquet" for d in DAYS[:2]
    ]
    assert f"2 of {len(FILES)} files had no MD5" in marketparquet_build.describe(path)


def test_a_still_archive_gives_no_warning(tmp_path) -> None:
    _, path = snapshot(tmp_path)
    assert cache.read_manifest(path)["modified_during_download"] == []
    assert "warning" not in marketparquet_build.describe(path)


def test_a_file_of_the_wrong_size_fails_the_download_and_leaves_no_snapshot(tmp_path) -> None:
    sizes = {(ETF, DAYS[2]): 1}
    archive = FakeArchive(FILES, sizes)
    with pytest.raises(mp.ArchiveError, match="bytes served"):
        mp.download(archive, tmp_path, [STOCK, ETF], START, END, TODAY, retries=2)
    assert sum(url.startswith(f"{STORAGE}/{ETF}/{DAYS[2]}") for url in archive.fetched) == 3
    assert cache.complete_snapshots(tmp_path, mp.NAME) == []


def test_no_snapshot_before_the_archive_holds_the_last_session(tmp_path) -> None:
    short = {key: data for key, data in FILES.items() if key != (ETF, END)}
    with pytest.raises(mp.ArchiveError, match="last file"):
        mp.download(FakeArchive(short), tmp_path, [STOCK, ETF], START, END, TODAY)
    with pytest.raises(ValueError, match="not before the download date"):
        mp.download(FakeArchive(FILES), tmp_path, [STOCK], START, END, END)
    assert cache.complete_snapshots(tmp_path, mp.NAME) == []


def test_the_runner_downloads_what_the_config_names(tmp_path) -> None:
    cfg = {"source": {"assets": [ETF]}, "dates": {"start": START, "end": END, "calendar": "XNYS"}, "download": {"retries": 0, "workers": 2}}
    path = marketparquet_build.download_snapshot(FakeArchive(FILES), tmp_path, cfg, TODAY)
    assert mp.snapshot_days(path, ETF) == DAYS and mp.snapshot_days(path, STOCK) == []
    assert f"{ETF}: {len(DAYS)} files, {START} to {END}" in marketparquet_build.describe(path)


def test_the_runner_takes_another_period_in_place_of_the_configured_one(tmp_path) -> None:
    cfg = {"source": {"assets": [ETF]}, "dates": {"start": START, "end": END, "calendar": "XNYS"}, "download": {"retries": 0, "workers": 2}}
    path = marketparquet_build.download_snapshot(FakeArchive(FILES), tmp_path, cfg, TODAY, start=DAYS[2], end=DAYS[4])
    assert mp.snapshot_days(path, ETF) == DAYS[2:5]
    manifest = cache.read_manifest(path)
    assert (manifest["start"], manifest["end_exclusive"]) == (DAYS[2].isoformat(), (DAYS[4] + dt.timedelta(days=1)).isoformat())
    assert marketparquet_build.period(cfg, None, DAYS[4]) == (START, DAYS[4])


def test_the_end_of_a_period_moves_back_to_the_last_session() -> None:
    cfg = {"dates": {"start": dt.date(2025, 1, 2), "end": dt.date(2025, 1, 5), "calendar": "XNYS"}}
    friday = dt.date(2025, 1, 3)
    assert marketparquet_build.period(cfg, None, None) == (dt.date(2025, 1, 2), friday)        # the 5th is a Sunday
    assert marketparquet_build.period(cfg, None, friday)[1] == friday
    assert marketparquet_build.period(cfg, dt.date(2024, 12, 2), dt.date(2025, 1, 1))[1] == dt.date(2024, 12, 31)   # a holiday
    assert marketparquet_build.period(cfg, dt.date(2000, 1, 1), dt.date(2000, 1, 3))[1] == dt.date(2000, 1, 3)
    for start, end in ((dt.date(2025, 1, 4), dt.date(2025, 1, 5)), (dt.date(2025, 2, 1), dt.date(2025, 1, 10))):
        with pytest.raises(mp.ArchiveError, match="no session"):
            marketparquet_build.period(cfg, start, end)


def test_the_configured_end_is_a_session() -> None:
    cfg = load_config("marketparquet")
    assert marketparquet_build.period(cfg, None, None) == (cfg["dates"]["start"], cfg["dates"]["end"])


def test_a_period_without_a_download_is_refused() -> None:
    with pytest.raises(SystemExit):
        marketparquet_build.main(["--start", "2024-01-02"])


# Reading -----------------------------------------------------------------------------------------------


def test_both_vintages_of_day_file_read_alike() -> None:
    day = DAYS[0]
    old, new = (mp.read_day(day_bytes(day, SYMBOLS[STOCK], field=f), day) for f in ("timestamp", "date"))
    pd.testing.assert_frame_equal(old, new)
    assert list(new.columns) == mp.DAY_COLUMNS and new["date"].dtype == "datetime64[ns]"
    assert (new["date"] == pd.Timestamp(day)).all()


def test_a_symbol_is_kept_as_served_with_its_suffix() -> None:
    assert mp.read_day(FILES[STOCK, DAYS[0]], DAYS[0])["ticker"].tolist() == SYMBOLS[STOCK]


def test_a_day_file_of_another_day_or_with_a_repeated_symbol_is_refused() -> None:
    with pytest.raises(mp.ArchiveError, match="another day"):
        mp.read_day(FILES[STOCK, DAYS[0]], DAYS[1])
    with pytest.raises(mp.ArchiveError, match="twice"):
        mp.read_day(day_bytes(DAYS[0], ["AAA", "AAA"]), DAYS[0])
    table = pq.read_table(io.BytesIO(FILES[STOCK, DAYS[-1]])).drop_columns(["volume"])
    out = io.BytesIO()
    pq.write_table(table, out)
    with pytest.raises(mp.ArchiveError, match="schema"):
        mp.read_day(out.getvalue(), DAYS[-1])


def test_a_window_reads_its_days_and_opens_no_file_outside_it(tmp_path) -> None:
    # The first and last files are not parquet at all, so opening either would raise.
    files = {**FILES, (STOCK, DAYS[0]): b"not parquet", (STOCK, DAYS[-1]): b"not parquet"}
    _, path = snapshot(tmp_path, files)
    bars = mp.read_days(path, STOCK, DAYS[1], DAYS[-1])
    assert sorted(bars["date"].dt.date.unique()) == DAYS[1:-1]
    assert len(bars) == len(DAYS[1:-1]) * len(SYMBOLS[STOCK])
    assert bars[["date", "ticker"]].equals(bars[["date", "ticker"]].sort_values(["date", "ticker"]).reset_index(drop=True))
    empty = mp.read_days(path, STOCK, dt.date(2030, 1, 1), dt.date(2030, 2, 1))
    assert empty.empty and list(empty.columns) == mp.DAY_COLUMNS and empty.dtypes.equals(bars.dtypes)


def test_the_by_ticker_reader_refuses_a_snapshot_of_day_files(tmp_path) -> None:
    _, path = snapshot(tmp_path)
    with pytest.raises(ValueError, match="read_days"):
        PriceSnapshot.open(path)


# The runner's failures -----------------------------------------------------------------------------------


@pytest.mark.parametrize("failure", [
    mp.MissingCredentialsError("set the key"),
    mp.RefusedError(401, "Not authenticated"),
    mp.ArchiveError("the archive's last file is 2026-11-18"),
    cache.SnapshotDigestError("digest differs"),
    FileNotFoundError("no complete snapshot"),
    urllib.error.URLError("no route"),
])
def test_an_expected_failure_is_one_line_and_exit_code_1(failure, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def fail(argv):
        raise failure

    monkeypatch.setattr(marketparquet_build, "run", fail)
    assert marketparquet_build.main([]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ") and err.count("\n") == 1 and "Traceback" not in err


def test_a_bug_keeps_its_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(argv):
        raise ValueError("a bug")

    monkeypatch.setattr(marketparquet_build, "run", fail)
    with pytest.raises(ValueError, match="a bug"):
        marketparquet_build.main([])
