"""Phase 8 momentum signals: the window, the skip month and the warm-up, on synthetic series.

The look-ahead contract on the registered signals, with short windows, is in
tests/contract/; the last tests here run it at the default window and skip.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_CAL, MARKET_ETFS, synthetic_market
from statarb.data import marketparquet as mp
from statarb.signals.momentum import MomentumSignal, momentum_signal
from statarb.signals.registry import make_signal
from statarb.signals.tables import TABLES, build_tables
from statarb.testing.lookahead import perturb_after, truncate_after

WINDOW, SKIP = 252, 21                                       # the defaults
T = 320                                                      # a day with a full window
SOURCES = ("raw", "residual")


def _series(days: int = 600, names: int = 3, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=days)
    return pd.DataFrame(rng.normal(0, 0.02, (days, names)), index=dates, columns=[f"S{i}" for i in range(names)])


def _shocked(series: pd.DataFrame, row: int) -> pd.DataFrame:
    out = series.copy()
    out.iloc[row, 0] += 0.5
    return out


def test_total_return_momentum_compounds_the_window_ending_skip_days_before() -> None:
    series = _series()
    out = momentum_signal(series, "raw", WINDOW, SKIP)
    t = T
    rows = series.iloc[t - SKIP - WINDOW + 1 : t - SKIP + 1]
    assert len(rows) == WINDOW
    np.testing.assert_allclose(out.iloc[t], (1 + rows).prod() - 1, rtol=1e-12)


def test_residual_momentum_is_the_window_sum_over_its_standard_deviation() -> None:
    series = _series()
    out = momentum_signal(series, "residual", WINDOW, SKIP)
    t = T
    rows = series.iloc[t - SKIP - WINDOW + 1 : t - SKIP + 1]
    np.testing.assert_allclose(out.iloc[t], rows.sum() / rows.std(), rtol=1e-12)


@pytest.mark.parametrize("source", SOURCES)
def test_a_shock_in_the_skip_month_leaves_the_score_unchanged(source: str) -> None:
    series = _series()
    t = T
    base = momentum_signal(series, source, WINDOW, SKIP).iloc[t]
    for row in range(t - SKIP + 1, t + 1):                    # the last SKIP days, day t included
        assert momentum_signal(_shocked(series, row), source, WINDOW, SKIP).iloc[t].equals(base)
    moved = momentum_signal(_shocked(series, t - SKIP), source, WINDOW, SKIP).iloc[t]
    assert moved["S0"] != base["S0"] and moved.drop("S0").equals(base.drop("S0"))


@pytest.mark.parametrize("source", SOURCES)
def test_the_window_is_window_days_long(source: str) -> None:
    series = _series()
    t = T
    first = t - SKIP - WINDOW + 1                             # the earliest day in the window
    base = momentum_signal(series, source, WINDOW, SKIP).iloc[t]
    assert momentum_signal(_shocked(series, first), source, WINDOW, SKIP).iloc[t]["S0"] != base["S0"]
    # The shock left the rolling sums before day t, which can leave rounding behind.
    np.testing.assert_allclose(momentum_signal(_shocked(series, first - 1), source, WINDOW, SKIP).iloc[t], base, rtol=1e-12)


def test_a_total_loss_scores_minus_one_and_an_impossible_return_counts_as_missing() -> None:
    series = _series()
    series.iloc[300, 1] = -1.0                                # S1 loses everything on row 300
    series.iloc[300, 2] = -1.5                                # S2 has a return no share can have
    with np.errstate(all="raise"):                            # no log of zero or of a negative number
        out = momentum_signal(series, "raw", WINDOW, SKIP)
    held = slice(300 + SKIP, 300 + SKIP + WINDOW)             # the rows whose window holds row 300
    assert (out["S1"].iloc[held] == -1.0).all() and out["S2"].iloc[held].isna().all()
    clean = momentum_signal(series.drop(columns=["S1", "S2"]), "raw", WINDOW, SKIP)
    pd.testing.assert_series_equal(out["S0"], clean["S0"])
    for name in ("S1", "S2"):                                 # before and after those windows, scored as usual
        rest = out[name].drop(out.index[held]).iloc[WINDOW + SKIP - 1 :]
        assert rest.notna().all() and (rest > -1.0).all()


@pytest.mark.parametrize("source", SOURCES)
def test_a_symbol_with_too_little_history_scores_nan(source: str) -> None:
    series = _series()
    series.iloc[:20, 1] = np.nan                              # S1 lists on row 20
    series.iloc[30, 2] = np.nan                               # S2 misses a day
    out = momentum_signal(series, source, WINDOW, SKIP)
    warm = WINDOW + SKIP - 1                                  # the first row with a full window
    assert out.iloc[:warm].isna().all().all() and out.iloc[warm:]["S0"].notna().all()
    assert out["S1"].iloc[: 20 + warm].isna().all() and out["S1"].iloc[20 + warm :].notna().all()
    missing = out["S2"].isna()
    assert missing.iloc[30 + SKIP : 30 + SKIP + WINDOW].all()  # every window over the missing day
    assert not missing.iloc[30 + SKIP + WINDOW :].any()


def test_momentum_rejects_an_unsorted_series_and_bad_parameters() -> None:
    series = _series()
    with pytest.raises(ValueError, match="sorted"):
        momentum_signal(series.iloc[::-1], "raw", WINDOW, SKIP)
    with pytest.raises(ValueError):
        momentum_signal(series, "prices", WINDOW, SKIP)
    with pytest.raises(ValueError):
        MomentumSignal("momentum", "raw", window_days=1)
    with pytest.raises(ValueError):
        MomentumSignal("momentum", "raw", skip_days=-1)


def test_the_registered_signals_default_to_252_days_skipping_21() -> None:
    for name, source in (("momentum", "raw"), ("residual_momentum", "residual")):
        signal = make_signal(name)
        assert (signal.name, signal.source, signal.window_days, signal.skip_days) == (name, source, 252, 21)


# The look-ahead contract at the default window and skip. The synthetic market has 320 days and
# residuals from row 20, so residual momentum scores from row 292 (total-return momentum, scored
# from a stock's first residual, from row 273), and a value after row 298 reaches no score: the
# cut-off sits between the two.
CUT = 295


def _long(seed: int = 11) -> dict[str, pd.DataFrame]:
    return dict(zip(TABLES, synthetic_market(seed=seed), strict=True))


def _frame(long: dict[str, pd.DataFrame], name: str) -> pd.DataFrame:
    tables = build_tables(*(long[t] for t in TABLES), "SPY", MARKET_ETFS)
    return pd.DataFrame(make_signal(name).scores(tables).score, index=tables.dates, columns=tables.stocks)


@pytest.mark.parametrize("name", ["momentum", "residual_momentum"])
def test_default_momentum_has_no_look_ahead_when_later_values_change(name: str) -> None:
    long = _long()
    cutoff = MARKET_CAL[CUT]
    column = {"momentum": ("returns", "ret"), "residual_momentum": ("residuals", "residual")}[name]
    perturbed = {**long, column[0]: perturb_after(long[column[0]], cutoff, [column[1]], seed=3)}
    before, after = _frame(long, name), _frame(perturbed, name)
    assert before.loc[:cutoff].notna().any().any()
    pd.testing.assert_frame_equal(before.loc[:cutoff], after.loc[:cutoff], check_exact=True, check_freq=False)
    assert not before.equals(after)                           # the perturbation reached the later scores


@pytest.mark.parametrize("name", ["momentum", "residual_momentum"])
def test_default_momentum_has_no_look_ahead_when_later_rows_are_removed(name: str) -> None:
    long = _long()
    cutoff = MARKET_CAL[CUT]
    whole = _frame(long, name).loc[:cutoff]
    live = _frame(truncate_after(long, cutoff), name).reindex(columns=whole.columns)
    assert whole.notna().any().any()
    pd.testing.assert_frame_equal(whole, live, check_exact=True, check_freq=False)


DEAD = [f"S{i:02d}" for i in (3, 8, 13, 21)]      # carry the suffix in every table


def _suffixed(suffix: str) -> dict[str, pd.DataFrame]:
    names = {t: f"{t}{suffix}" for t in DEAD}
    return {name: frame.assign(ticker=frame["ticker"].replace(names)) for name, frame in _long().items()}


@pytest.mark.parametrize("name", ["momentum", "residual_momentum"])
def test_the_suffix_decides_no_momentum_score(name: str) -> None:
    """Decision record 0008, point 8, as phase 7 checks it: with every suffix replaced by a label that
    means nothing, each security has the same scores on the same days."""
    plain = _frame(_suffixed(mp.SUFFIX), name)
    other = _frame(_suffixed("~7"), name)
    back = other.rename(columns=lambda t: t.replace("~7", mp.SUFFIX))
    pd.testing.assert_frame_equal(plain, back[plain.columns], check_exact=True, check_freq=False)
    assert plain.loc[:, plain.columns.str.endswith(mp.SUFFIX)].notna().any().all()   # the suffixed names are scored
