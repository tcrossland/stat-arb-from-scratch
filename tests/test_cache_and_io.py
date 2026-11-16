from __future__ import annotations

import datetime as dt
import json
import stat

import pandas as pd
import pytest

from statarb.config import RAW_ENV, raw_store, repo_root
from statarb.data import cache
from statarb.io import read_parquet, write_parquet
from statarb.testing.lookahead import assert_unchanged_through, perturb_after

DAY = dt.date(2026, 11, 14)


def test_incomplete_snapshot_is_never_selected(tmp_path) -> None:
    writer = cache.SnapshotWriter(tmp_path, "src", DAY)
    writer.write_bytes("x", b"1")
    with pytest.raises(FileNotFoundError):
        cache.select_snapshot(tmp_path, "src")


def test_complete_snapshot_is_never_overwritten(tmp_path) -> None:
    writer = cache.SnapshotWriter(tmp_path, "src", DAY)
    writer.commit({"a": 1})
    with pytest.raises(cache.SnapshotExistsError):
        cache.SnapshotWriter(tmp_path, "src", DAY)
    assert cache.select_snapshot(tmp_path, "src") == tmp_path / "src" / DAY.isoformat()


def test_incomplete_snapshot_is_cleared_on_retry(tmp_path) -> None:
    first = cache.SnapshotWriter(tmp_path, "src", DAY)
    first.write_bytes("stale", b"1")
    second = cache.SnapshotWriter(tmp_path, "src", DAY)
    assert not (second.path / "stale").exists()


def test_latest_or_pinned_snapshot(tmp_path) -> None:
    for day in (dt.date(2026, 1, 1), dt.date(2026, 2, 1)):
        cache.SnapshotWriter(tmp_path, "src", day).commit({})
    assert cache.select_snapshot(tmp_path, "src").name == "2026-02-01"
    pinned = tmp_path / "src" / "2026-01-01"
    assert cache.select_snapshot(tmp_path, "src", "2026-01-01", cache.read_manifest(pinned)["digest"]) == pinned
    with pytest.raises(FileNotFoundError):
        cache.select_snapshot(tmp_path, "src", "2025-01-01")


def test_parquet_writes_are_byte_identical_and_order_independent(tmp_path) -> None:
    frame = pd.DataFrame({"date": pd.bdate_range("2021-01-01", periods=4).repeat(2), "ticker": ["B", "A"] * 4, "x": range(8)})
    write_parquet(frame, tmp_path / "a.parquet", ["date", "ticker"])
    write_parquet(frame.sample(frac=1, random_state=1), tmp_path / "b.parquet", ["date", "ticker"])
    assert (tmp_path / "a.parquet").read_bytes() == (tmp_path / "b.parquet").read_bytes()
    assert not list(tmp_path.glob("*.tmp"))
    assert read_parquet(tmp_path / "a.parquet")["ticker"].tolist()[:2] == ["A", "B"]


def test_perturb_after_changes_only_later_rows() -> None:
    frame = pd.DataFrame({"date": pd.bdate_range("2021-01-01", periods=10), "ticker": "A", "close": 100.0})
    cutoff = pd.Timestamp("2021-01-08")
    noisy = perturb_after(frame, cutoff, ["close"], seed=3)
    assert_unchanged_through(frame, noisy, cutoff)
    assert (noisy.loc[noisy["date"] > cutoff, "close"] != 100.0).all()
    assert (noisy["close"] > 0).all()


def test_commit_records_hashes_and_digest_and_makes_the_snapshot_read_only(tmp_path) -> None:
    writer = cache.SnapshotWriter(tmp_path, "src", DAY)
    writer.write_bytes("a/x.bin", b"1")
    writer.write_bytes("y.bin", b"2")
    path = writer.commit({"source": "src"})
    manifest = cache.read_manifest(path)
    assert set(manifest["files"]) == {"a/x.bin", "y.bin"}
    assert manifest["digest"] == cache.digest(cache.file_hashes(path))
    assert not (path / "y.bin").stat().st_mode & stat.S_IWUSR
    assert not path.stat().st_mode & stat.S_IWUSR
    cache.verify(path, manifest["digest"])


def test_digest_depends_on_every_path_and_hash() -> None:
    base = {"a": "1" * 64, "b": "2" * 64}
    assert cache.digest(base) == cache.digest(dict(reversed(base.items())))
    assert cache.digest(base) != cache.digest({**base, "b": "3" * 64})
    assert cache.digest(base) != cache.digest({"a": "1" * 64, "c": "2" * 64})


def test_add_hashes_changes_the_manifest_only(tmp_path) -> None:
    path = tmp_path / "src" / DAY.isoformat()
    (path / "bars").mkdir(parents=True)
    (path / "bars" / "x.parquet").write_bytes(b"data")
    (path / "manifest.json").write_text(json.dumps({"source": "src"}))
    before = {p: p.read_bytes() for p in path.rglob("*") if p.is_file() and p.name != "manifest.json"}
    found = cache.add_hashes(path)
    assert {p: p.read_bytes() for p in path.rglob("*") if p.is_file() and p.name != "manifest.json"} == before
    manifest = cache.read_manifest(path)
    assert manifest["source"] == "src" and manifest["digest"] == found
    assert cache.add_hashes(path) == found          # a second run checks and changes nothing


def test_raw_store_comes_from_the_environment_when_set(tmp_path) -> None:
    assert raw_store("data/raw", repo_root(), {}) == repo_root() / "data/raw"
    assert raw_store("data/raw", repo_root(), {RAW_ENV: str(tmp_path)}) == tmp_path
    with pytest.raises(ValueError, match="absolute"):
        raw_store("data/raw", repo_root(), {RAW_ENV: "relative/raw"})
