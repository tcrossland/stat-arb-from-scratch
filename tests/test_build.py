"""The build end to end on synthetic snapshots: deliverables, exact rebuilds and returns that a later download leaves alone."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from helpers import (
    SplitAdjustedSource,
    constituents_html,
    fake_wikipedia_api,
    synthetic_truth,
)
from statarb.data import build as b
from statarb.data import cache
from statarb.data.wikipedia import WikipediaConstituents
from statarb.io import read_parquet

START = dt.date(2019, 7, 1)
FIRST, LATER = dt.date(2020, 3, 2), dt.date(2020, 6, 1)
DAYS = pd.bdate_range("2019-06-03", "2020-05-29")
TRUTHS = {
    "SPY": synthetic_truth(DAYS, seed=1, price=300.0, volume=5e7),
    "AAA": synthetic_truth(DAYS, seed=2, splits={pd.Timestamp("2019-11-04"): 3.0}, cash={pd.Timestamp("2019-09-16"): 0.5}),
    "BRK.B": synthetic_truth(DAYS, seed=3, price=200.0, volume=3e6),
    "CCC": synthetic_truth(DAYS, seed=4, volume=2e5, splits={pd.Timestamp("2020-04-01"): 2.0}),   # after FIRST
    "DDD": synthetic_truth(DAYS, seed=5, volume=5e5, cash={pd.Timestamp("2020-04-15"): 0.3}),
}   # EEE, on the constituent page, has no prices
CFG = {
    "dates": {"start": START},
    "source": {"name": "synthetic", "snapshot": ""},
    "universe": {"size": 3, "liquidity_window_days": 20, "liquidity_min_observations": 18, "rebalance": "monthly"},
    "factors": {"market": "SPY", "sectors": []},
    "quality": {"max_abs_daily_return": 0.25, "min_live_coverage": 0.95},
}
UNIVERSE_CFG = {"revision_id": 123456, "retrieved": "2020-03-01"}


def _constituents() -> WikipediaConstituents:
    return WikipediaConstituents(api=fake_wikipedia_api(constituents_html(), revid=123456))


def _download(raw_root, today: dt.date) -> None:
    source = SplitAdjustedSource(TRUTHS)
    tickers = ["AAA", "BRK.B", "CCC", "DDD", "EEE", "SPY"]
    b.download_prices(source, raw_root, tickers, START, today, pause=0.0, retries=0)


@pytest.fixture
def raw_root(tmp_path):
    root = tmp_path / "raw"
    b.download_constituents(_constituents(), root, 123456, FIRST)
    _download(root, FIRST)
    return root


def _build(raw_root, snapshot: str = "", digest: str = ""):
    cfg = {**CFG, "source": {**CFG["source"], "snapshot": snapshot, "digest": digest}}
    return b.build(raw_root, cfg, UNIVERSE_CFG, [], _constituents(), "synthetic")


@pytest.mark.parametrize("pin_hint", [True, False])
def test_the_hint_to_pin_a_price_snapshot_can_be_left_out(tmp_path, capsys, pin_hint) -> None:
    b.download_prices(SplitAdjustedSource(TRUTHS), tmp_path / "raw", ["AAA", "SPY"], START, FIRST, 0.0, 0, pin_hint=pin_hint)
    err = capsys.readouterr().err
    assert "prices: saved to" in err and ("set in [source] of config/data.toml" in err) is pin_hint


def test_build_writes_every_deliverable(raw_root, tmp_path) -> None:
    out = _build(raw_root)
    b.write_outputs(out, tmp_path / "processed", tmp_path / "reports")
    names = {p.name for p in (tmp_path / "processed").glob("*.parquet")}
    assert names == {f"{t}.parquet" for t in ("candidates", "prices", "actions", "returns", "universe", "sectors")}
    assert (tmp_path / "reports" / "phase-00" / "data_quality.md").is_file()
    assert set(read_parquet(tmp_path / "processed" / "universe.parquet")["ticker"]) <= {"AAA", "BRK.B", "CCC", "DDD"}
    assert out.prices["date"].max() < pd.Timestamp(FIRST)


def test_rebuild_is_byte_identical(raw_root, tmp_path) -> None:
    for name in ("a", "b"):
        b.write_outputs(_build(raw_root), tmp_path / name / "processed", tmp_path / name / "reports")
    for path in sorted((tmp_path / "a").rglob("*.*")):
        twin = tmp_path / "b" / path.relative_to(tmp_path / "a")
        assert path.read_bytes() == twin.read_bytes(), path.name


def test_split_days_are_not_jumps(raw_root) -> None:
    returns = _build(raw_root).returns
    split_days = returns.loc[returns["split_ratio"] != 1.0]
    assert len(split_days) == 1
    assert (returns["ret"].abs() < 0.25).all()


def test_missing_ticker_is_reported(raw_root) -> None:
    out = _build(raw_root)
    section = out.report.split("## Tickers with no data", 1)[1].split("##", 1)[0]
    assert "EEE" in section


def test_a_later_snapshot_leaves_earlier_returns_unchanged(raw_root) -> None:
    """A later download is split-adjusted to a later date (CCC splits in between), yet history is unchanged."""
    first = _build(raw_root).returns
    _download(raw_root, LATER)
    later = _build(raw_root).returns
    assert later["date"].max() > first["date"].max()
    overlap = later.loc[later["date"] <= first["date"].max()].reset_index(drop=True)
    pd.testing.assert_frame_equal(overlap, first.reset_index(drop=True), check_exact=False, rtol=1e-12, atol=1e-12)


def test_pinned_snapshot_is_used_and_checked(raw_root) -> None:
    _download(raw_root, LATER)
    pinned = raw_root / "synthetic" / FIRST.isoformat()
    good = cache.read_manifest(pinned)["digest"]
    assert _build(raw_root, FIRST.isoformat(), good).prices["date"].max() < pd.Timestamp(FIRST)
    with pytest.raises(cache.SnapshotDigestError, match="pin its digest"):
        _build(raw_root, FIRST.isoformat())
    with pytest.raises(cache.SnapshotDigestError, match="not the pinned"):
        _build(raw_root, FIRST.isoformat(), "0" * 64)


def test_the_build_refuses_a_pinned_snapshot_whose_files_changed(raw_root) -> None:
    pinned = raw_root / "synthetic" / FIRST.isoformat()
    good = cache.read_manifest(pinned)["digest"]
    victim = pinned / "AAA.parquet"
    victim.chmod(0o644)
    victim.write_bytes(victim.read_bytes() + b"x")
    with pytest.raises(cache.SnapshotDigestError, match="AAA.parquet"):
        _build(raw_root, FIRST.isoformat(), good)


def test_todays_constituent_snapshot_of_the_pinned_revision_is_reused(raw_root) -> None:
    api = fake_wikipedia_api(constituents_html(), revid=123456)
    path = b.download_constituents(WikipediaConstituents(api=api), raw_root, 123456, FIRST)
    assert path.name == FIRST.isoformat() and api.calls == []
