"""Phase 6 weekly drift report: its measures, comparisons, revision checks and report, on synthetic data."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_CAL
from runner_helpers import market_long, market_settings
from statarb.config import OVERLAY_ENV, repo_root
from statarb.data import cache
from statarb.io import write_parquet
from statarb.paper import drift, ledger
from statarb.paper.config import TRAILING
from statarb.paper.day import (
    backtest_path,
    ledger_day,
    session_inputs,
    strategy_of,
    strategy_panels,
)
from statarb.paper.frozen import FrozenConfigError
from statarb.paper.report import write_drift_report
from test_paper_day import META, first_session

DAYS = 12


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """The no-trade zone run for DAYS sessions through the job's own functions, read back from the ledger on disk."""
    settings, long = market_settings(), market_long()
    strategy = strategy_of(settings, "baseline", "no-trade zone", TRAILING, 500_000)
    first = first_session(settings, long, strategy)
    root = tmp_path_factory.mktemp("ledger")
    carry = ledger.Carry.flat(())
    for date in MARKET_CAL[first : first + DAYS]:
        frame, _ = ledger_day(session_inputs(long, date, MARKET_CAL[first], strategy), carry, META)
        ledger.write_day(root, frame)
        carry = ledger.carry_of(frame)
    return long, strategy, MARKET_CAL[first], MARKET_CAL[first + DAYS - 1], drift.read_ledger(root)


# Daily measures ------------------------------------------------------------------------------------


def test_book_measures_from_the_ledger_equal_the_backtest(run) -> None:
    """Turnover, exposure and net return per dollar of capital, as the backtest's path reports them."""
    long, strategy, first, last, frame = run
    path = backtest_path(strategy_panels(long, last, first, strategy), strategy).daily
    got = drift.book_measures(frame)
    assert list(got.index) == list(path.index)
    cols = ["turnover", "exposure", "net"]
    np.testing.assert_allclose(got[cols], path[cols], rtol=1e-12, atol=1e-15)
    assert got["turnover"].iloc[0] == 0 and got["exposure"].iloc[0] == 0      # the first decision fills at the next open
    assert (got["turnover"] > 0).sum() > 2


def test_signal_measures_pair_the_signal_on_d_with_the_residual_on_d_plus_1() -> None:
    rng = np.random.default_rng(0)
    T, N = 6, 30
    residual = rng.normal(size=(T, N))
    signal = np.vstack([residual[1:], rng.normal(size=(1, N))])          # tomorrow's residual: IC of 1
    members = np.ones((T, N), dtype=bool)
    members[:, :5] = False                                                 # non-members never count
    signal[:, :5] = -signal[:, :5] * 1e6
    dates = pd.bdate_range("2026-11-16", periods=T)
    m = drift.signal_measures(dates, signal, signal * 0.01, np.linspace(-1, 1, T), residual, members)
    np.testing.assert_allclose(m["ic"].iloc[:-1], 1.0)
    assert np.isnan(m["ic"].iloc[-1])
    np.testing.assert_allclose(m["signal_sd"], np.std(signal[:, 5:], axis=1, ddof=1))
    np.testing.assert_allclose(m["forecast_sd"], np.std(signal[:, 5:] * 0.01, axis=1, ddof=1))
    no_members = drift.signal_measures(dates, signal, signal, np.zeros(T), residual, np.zeros((T, N), dtype=bool))
    assert no_members[["signal_sd", "ic"]].isna().all().all()


# Comparison with the reference ---------------------------------------------------------------------


def _measure(stat="mean", band=drift.WINDOW, ramp_up=False):
    return drift.Measure("x", "x", "book", stat, band, ramp_up, "turnover")


def test_a_live_statistic_is_compared_with_windows_of_as_many_days() -> None:
    reference = pd.Series(np.arange(100, dtype="float64"))
    w = drift.windows(reference, 10, "mean")
    assert len(w) == 91 and w[0] == 4.5 and w[-1] == 94.5
    assert drift.windows(reference, 10, "sum")[0] == 45.0
    assert len(drift.windows(reference, 101, "mean")) == 0
    for live, verdict in ((50.0, "within"), (4.0, "below"), (99.0, "above")):
        c = drift.compare(_measure(), pd.Series([live] * 10), reference)
        assert c.verdict == verdict and c.days == 10 and c.windows == 91
    c = drift.compare(_measure(), pd.Series([50.0, np.nan]), reference)       # days without a value are not days
    assert c.days == 1 and c.windows == 100
    assert drift.compare(_measure(), pd.Series([], dtype="float64"), reference).verdict == "no data"


def test_the_pnl_band_is_wider_and_sums_the_days() -> None:
    rng = np.random.default_rng(1)
    reference = pd.Series(rng.normal(0, 0.01, 2000))
    live = pd.Series([0.004] * 20)
    wide = drift.compare(_measure("sum", drift.BAND), live, reference)
    narrow = drift.compare(_measure("sum", drift.WINDOW), live, reference)
    assert wide.live == pytest.approx(0.08)
    assert wide.low < narrow.low < narrow.high < wide.high
    assert narrow.verdict == "above" and wide.verdict == "within"
    band = drift.band_by_day(reference, 20, drift.BAND)
    assert list(band.index) == list(range(1, 21)) and (band["high"].diff().dropna() > 0).mean() > 0.8


def test_turnover_and_exposure_leave_out_the_ramp_up() -> None:
    days = pd.bdate_range("2026-11-16", periods=12)
    live_book = pd.DataFrame({"turnover": [5.0] * 2 + [0.2] * 10, "exposure": 0.6, "net": 0.0}, index=days)
    live_signal = pd.DataFrame({"signal_sd": 0.02, "forecast_sd": 0.001, "slope": 0.03, "ic": 0.01}, index=days)
    ref_days = pd.bdate_range("2016-07-11", periods=500)
    rng = np.random.default_rng(2)
    ref_book = pd.DataFrame(
        {"turnover": rng.normal(0.2, 0.01, 500), "exposure": rng.normal(0.6, 0.01, 500), "net": rng.normal(0, 0.001, 500)}, index=ref_days
    )
    ref_signal = pd.DataFrame(
        {
            "signal_sd": rng.normal(0.02, 0.001, 500),
            "forecast_sd": rng.normal(0.001, 1e-4, 500),
            "slope": rng.normal(0.03, 0.01, 500),
            "ic": rng.normal(0.01, 0.01, 500),
        },
        index=ref_days,
    )
    out = {c.measure.key: c for c in drift.comparisons(live_book, live_signal, ref_book, ref_signal, ramp_up=2)}
    assert out["turnover"].days == 10 and out["turnover"].verdict == "within"
    assert out["net"].days == 12 and out["slope"].days == 12
    assert out["negative"].live == 0.0
    with_ramp = {c.measure.key: c for c in drift.comparisons(live_book, live_signal, ref_book, ref_signal, ramp_up=0)}
    assert with_ramp["turnover"].verdict == "above"


# Revisions -----------------------------------------------------------------------------------------


def _snapshot(raw, name, bars: dict[str, pd.DataFrame], end: str) -> None:
    path = raw / "synthetic" / name
    path.mkdir(parents=True)
    for ticker, frame in bars.items():
        write_parquet(frame, path / f"{ticker}.parquet", ["date"])
    (path / cache.MANIFEST).write_text(json.dumps({"end_exclusive": end, "failed": {"ZZZ": "no data"}}))


def _bars(dates, close, split=1.0) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "date": dates, "open": close, "high": close, "low": close, "close": close,
            "volume": 1e6, "cash": 0.0, "split_ratio": [1.0] * (n - 1) + [split],
        }
    )


def test_bar_changes_find_revisions_and_new_splits(tmp_path) -> None:
    raw = tmp_path / "raw"
    old_days, new_days = pd.bdate_range("2026-11-02", periods=5), pd.bdate_range("2026-11-02", periods=6)
    base = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
    _snapshot(raw, "2026-11-09", {"AAA": _bars(old_days, base), "BBB": _bars(old_days, base), "CCC": _bars(old_days, base)}, "2026-11-09")
    revised = np.append(base, 15.0)
    revised[2] = 12.5                                                      # the source revised one close
    _snapshot(
        raw, "2026-11-10",
        {"AAA": _bars(new_days, np.append(base, 15.0)), "BBB": _bars(new_days, revised), "CCC": _bars(new_days, np.append(base / 2, 7.5), split=2.0)},
        "2026-11-10",
    )
    pairs = drift.snapshot_pairs(raw, "synthetic", "2026-11-09")
    assert [(a.name, b.name) for a, b in pairs] == [("2026-11-09", "2026-11-10")]
    assert drift.snapshot_pairs(raw, "synthetic", "2026-11-10") == []    # nothing before the pinned snapshot counts
    ch = drift.bar_changes(*pairs[0]).set_index("ticker")
    assert sorted(ch.index) == ["BBB", "CCC"]                              # AAA only gained a day
    assert ch.loc["BBB", "rows"] == 1 and ch.loc["BBB", "first"] == old_days[2] and not ch.loc["BBB", "split"]
    assert ch.loc["BBB", "max_price_change"] == pytest.approx(0.5 / 12)
    assert ch.loc["CCC", "rows"] == 5 and ch.loc["CCC", "split"]
    assert drift.source_failures(["2026-11-10", "2026-11-11"], raw, "synthetic") == {"2026-11-10": ["ZZZ"]}


def test_decisions_rebuilt_on_the_same_tables_match_the_ledger(run) -> None:
    """Row d of one set of panels is the decision the job made on the tables cut at d."""
    long, strategy, first, last, frame = run
    dc = drift.decision_changes(frame, strategy_panels(long, last, first, strategy))
    assert len(dc) == DAYS
    assert (dc[["target_names", "move_names"]] == 0).all().all()


def test_a_revision_shows_as_changed_decisions_from_its_date(run) -> None:
    long, strategy, first, last, frame = run
    when = sorted(frame["date"].unique())[6]
    revised = {k: v.copy() for k, v in long.items()}
    r = revised["residuals"]
    r.loc[r["date"] == when, "residual"] += 0.05                          # a revised bar changes that day's residuals
    dc = drift.decision_changes(frame, strategy_panels(revised, last, first, strategy)).set_index("date")
    changed = dc.index[(dc["target_names"] > 0) | (dc["move_names"] > 0)]
    assert len(changed) > 0 and changed.min() == when


# Operations and the report -------------------------------------------------------------------------


def test_run_summary_counts_statuses_and_failed_backups() -> None:
    runs = [
        {"status": "done", "backup": "pushed: abc"},
        {"status": "nothing due", "backup": "failed: git push: denied"},
        {"status": "refused", "message": "ledger", "backup": None},
        {"status": "failed", "message": "boom", "as_of": "x"},
    ]
    s = drift.run_summary(runs)
    assert s["runs"] == 4 and s["by_status"] == {"done": 1, "nothing due": 1, "refused": 1, "failed": 1}
    assert [r["status"] for r in s["trouble"]] == ["refused", "failed"] and len(s["backup_failures"]) == 1


def _drift(run) -> drift.Drift:
    long, strategy, first, last, frame = run
    panels = strategy_panels(long, last, first, strategy)
    every = drift.panel_measures(panels)
    days = sorted(frame["date"].unique())
    live_signal, ref_signal = every.loc[days], every.loc[every.index < first].dropna(subset=["slope"])
    rng = np.random.default_rng(3)
    ref_book = pd.DataFrame({"turnover": rng.normal(0.2, 0.05, 400), "exposure": rng.normal(0.6, 0.1, 400), "net": rng.normal(0, 0.003, 400)})
    live_book = drift.book_measures(frame)
    per_day = frame.groupby("date").first()
    return drift.Drift(
        last=last, first=first, entry="f00dfeedf00dfeed", reference_span=(ref_signal.index[0], ref_signal.index[-1]),
        comparisons=drift.comparisons(live_book, live_signal, ref_book, ref_signal, 2),
        live_book=live_book, live_signal=live_signal, ref_book=ref_book, ref_signal=ref_signal,
        pnl_band=drift.band_by_day(ref_book["net"], len(days), drift.BAND),
        slope_band=tuple(np.nanpercentile(ref_signal["slope"], drift.WINDOW)),
        bars=[("2021-03-01", "2021-03-02", pd.DataFrame(columns=drift.CHANGE_COLUMNS))],
        decisions=drift.decision_changes(frame, panels),
        runs=drift.run_summary([{"status": "done", "backup": "pushed: abc"}, {"status": "failed", "message": "boom", "as_of": "2021-03-02T11:00:00+00:00"}]),
        lagging=[], missing_returns=per_day["missing_returns"].loc[lambda s: s > 0], source_failed={"2021-03-01": ["ZZZ"]},
        config_hashes=sorted(per_day["config_hash"].unique()), dirty_days=[], snapshot="2021-03-02", ramp_up=2,
    )


def test_the_report_states_the_verdicts_and_rewrites_the_same_day(run, tmp_path) -> None:
    d = _drift(run)
    name = f"{d.last:%Y-%m-%d}"
    path = write_drift_report(d, tmp_path / "drift")
    assert path.name == f"{name}.md" and (tmp_path / "drift" / f"{name}.png").exists()
    text = path.read_text()
    assert "- Turnover, signal distributions and IC:" in text and "- P&L:" in text
    assert f"{DAYS} of {DAYS} days are identical" in text and "f00dfeedf00dfeed" in text and "ZZZ" in text and "boom" in text
    assert "—" not in text and "(1st to 99th)" in text and "(5th to 95th)" in text
    first = (path.read_bytes(), (tmp_path / "drift" / f"{name}.png").read_bytes())
    write_drift_report(d, tmp_path / "drift")
    assert (path.read_bytes(), (tmp_path / "drift" / f"{name}.png").read_bytes()) == first
    assert sorted(p.name for p in (tmp_path / "drift").iterdir()) == [f"{name}.md", f"{name}.png"]


def test_nothing_to_report_without_a_ledger_day(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(drift, "load_config", lambda name, root=None: {"paths": {"paper": str(tmp_path), "raw": str(tmp_path / "raw")}})
    monkeypatch.delenv("STATARB_RAW", raising=False)
    assert drift.drift(tmp_path, pd.Timestamp("2027-01-22T12:00", tz="UTC").to_pydatetime()) is None


def _no_reads(monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("the drift report read its config before the frozen check")

    monkeypatch.setattr(drift, "load_config", refuse)


def test_the_report_refuses_with_nothing_frozen(tmp_path, monkeypatch) -> None:
    from test_paper_frozen import _unfrozen

    root = _unfrozen(tmp_path)
    monkeypatch.setattr(drift, "repo_root", lambda: root)
    _no_reads(monkeypatch)
    with pytest.raises(FrozenConfigError, match="waits for the decision record"):
        drift.main([])


def test_the_report_refuses_under_a_config_overlay(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(OVERLAY_ENV, str(tmp_path))
    _no_reads(monkeypatch)
    with pytest.raises(FrozenConfigError, match=OVERLAY_ENV):
        drift.main([])


def test_the_report_refuses_a_config_that_differs_from_the_frozen_record(tmp_path, monkeypatch) -> None:
    from test_paper_frozen import _edit, _freeze

    root = _freeze(tmp_path, "baseline", "no-trade zone")
    _edit(root, "costs", "headline_half_spread_bps = 1.5", "headline_half_spread_bps = 2.0")
    monkeypatch.setattr(drift, "repo_root", lambda: root)
    _no_reads(monkeypatch)
    with pytest.raises(FrozenConfigError, match="headline_half_spread_bps"):
        drift.main([])
    assert repo_root() != root
