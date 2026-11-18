"""The forward run's days are a fresh holdout (decision record 0007): no backtest reads them."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from helpers import MARKET_CAL, MARKET_ETFS, synthetic_market
from statarb.config import load_config, repo_root
from statarb.io import write_parquet
from statarb.paper.config import Run, load_paper_config
from statarb.signals.tables import TABLES, build_tables, cut_after, load_tables


def _run(first_session: dt.date | str) -> Run:
    return Run(first_session=first_session, calendar="XNYS", run_time=dt.time(6, 0))


def test_a_backtest_reads_up_to_the_day_before_the_first_session() -> None:
    assert _run(dt.date(2026, 11, 16)).last_before == pd.Timestamp("2026-11-15")
    assert _run("").last_before is None


def test_load_tables_cuts_at_the_last_date(tmp_path) -> None:
    long = dict(zip(TABLES, synthetic_market(seed=3), strict=True))
    for name, frame in long.items():
        keys = [c for c in ("date", "ticker", "valid_from") if c in frame.columns]
        write_parquet(frame, tmp_path / f"{name}.parquet", keys)
    last = MARKET_CAL[200]
    cut = load_tables(tmp_path, "SPY", MARKET_ETFS, last)
    assert cut.dates[-1] == last
    expected = build_tables(*cut_after(long, last).values(), "SPY", MARKET_ETFS)
    pd.testing.assert_frame_equal(cut.residual, expected.residual)
    assert load_tables(tmp_path, "SPY", MARKET_ETFS).dates[-1] == MARKET_CAL[-1]


def test_the_phase_5_holdout_ends_before_the_forward_run_starts() -> None:
    # The model, holdout and choice runners cut their tables at the phase 5 holdout's end, so
    # they read no forward day only while that end comes before the first session.
    first = load_paper_config(repo_root()).run.first
    if first is None:
        pytest.skip("the forward run's first session is not set")
    holdout_end = pd.Timestamp(load_config("models", repo_root())["period"]["holdout_end"])
    assert holdout_end < first
