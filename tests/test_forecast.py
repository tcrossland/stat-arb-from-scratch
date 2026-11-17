"""The model forecast as a signal, and the calibration of a forecast to an expected move."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_CAL, MARKET_ETFS, synthetic_market
from models_helpers import market_config
from statarb.models.forecast import ForecastSignal, calibrated_move
from statarb.models.ic import daily_rank_ic
from statarb.signals.calibration import forward_sum
from statarb.signals.registry import make_signal
from statarb.signals.tables import TABLES, build_tables
from statarb.testing.lookahead import perturb_after, truncate_after

CFG = market_config()
FIRST = 150


def _tables(long):
    return build_tables(*(long[t] for t in TABLES), "SPY", MARKET_ETFS)


def _long(seed: int = 11) -> dict:
    return dict(zip(TABLES, synthetic_market(seed=seed), strict=True))


@pytest.mark.parametrize("horizon", [1, 3])
def test_forecast_covers_member_days_from_the_first_block_on(horizon: int) -> None:
    tables = _tables(_long())
    signal = make_signal("model", config=CFG, horizon=horizon)
    run = signal.run(tables)
    score = run.panel((len(tables.dates), len(tables.stocks)))
    assert np.isnan(score[:FIRST]).all()
    rows = tables.members & np.isfinite(tables.residual.to_numpy())
    assert np.isfinite(score[FIRST:][rows[FIRST:]]).all() and np.isnan(score[FIRST:][~rows[FIRST:]]).all()
    assert len(run.walk.fits) == 5                                        # blocks of 40 from day 150 to day 319
    np.testing.assert_array_equal(score, signal.scores(tables).score)


def test_forecast_finds_the_fixture_reversal_out_of_sample() -> None:
    tables = _tables(_long())
    run = ForecastSignal(CFG, 1).run(tables)
    tested = np.isfinite(run.walk.forecast) & np.isfinite(run.target)
    ic = daily_rank_ic(run.features.day[tested], run.walk.forecast[tested], run.target[tested])
    assert ic.mean() > 0.1


def test_a_horizon_outside_the_config_is_refused() -> None:
    with pytest.raises(ValueError, match="horizon 5"):
        ForecastSignal(CFG, 5)


@pytest.mark.parametrize("cut", [170, 245])
def test_forecast_unchanged_when_later_rows_are_removed_at_the_headline_horizon(cut: int) -> None:
    long = _long()
    cutoff = MARKET_CAL[cut]
    whole = ForecastSignal(CFG, 1).scores(_tables(long)).score[: cut + 1]
    live = ForecastSignal(CFG, 1).scores(_tables(truncate_after(long, cutoff))).score
    np.testing.assert_array_equal(whole, live)


def test_calibrated_forecast_has_no_look_ahead() -> None:
    long = _long()
    cut = 260
    cutoff = MARKET_CAL[cut]
    perturbed = {**long, "residuals": perturb_after(long["residuals"], cutoff, ["residual"], seed=4, scale=1.0),
                 "returns": perturb_after(long["returns"], cutoff, ["ret"], seed=5, scale=1.0)}
    moves = []
    for lg in (long, perturbed):
        t = _tables(lg)
        score = ForecastSignal(CFG, 1).scores(t).score
        moves.append(calibrated_move(score, t.residual.to_numpy(), t.members, 5, 60, 20))
    assert np.isfinite(moves[0][: cut + 1]).any()                         # the calibration has started by the cut
    np.testing.assert_array_equal(moves[0][: cut + 1], moves[1][: cut + 1])
    assert not np.array_equal(np.nan_to_num(moves[0][cut + 1 :]), np.nan_to_num(moves[1][cut + 1 :]))


def test_calibrated_move_is_the_trailing_slope_times_the_demeaned_score() -> None:
    t = _tables(_long())
    res = t.residual.to_numpy()
    score = -pd.DataFrame(res).rolling(3, min_periods=3).sum().to_numpy()
    move = calibrated_move(score, res, t.members, 5, 60, 20)
    d = 200
    outcome = forward_sum(res, 5)
    rows = slice(d - 5 - 60 + 1, d - 5 + 1)                               # pairs whose 5-day outcome is known at d
    s, o = score[rows], outcome[rows]
    ok = t.members[rows] & np.isfinite(s) & np.isfinite(o)
    x = np.where(ok, s - np.nanmean(np.where(ok, s, np.nan), axis=1, keepdims=True), 0.0)
    yv = np.where(ok, o - np.nanmean(np.where(ok, o, np.nan), axis=1, keepdims=True), 0.0)
    slope = (x * yv).sum() / (x**2).sum()
    today = t.members[d] & np.isfinite(score[d])
    expected = (score[d, today] - score[d, today].mean()) * slope
    np.testing.assert_allclose(move[d, today], expected, rtol=1e-10)
