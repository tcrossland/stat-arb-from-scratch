"""Contract every registered signal must pass (phase 2 brief, "The `Signal` interface").

Each signal in `statarb.signals.registry` is built with its config's parameters
and run on a synthetic market. Its score on any day up to a cut-off must not
change when every table it reads is perturbed after the cut-off (no
look-ahead), and no score may change when the tables it does not declare are
perturbed (it reads what it says it reads). Its score up to a cut-off must also
be the same when the tables are cut there, as a live run on that day would load
them, with a member whose residuals start after the cut: perturbation leaves
which rows exist alone, so it cannot see a score that depends on whether a later
row exists (phase 5 brief).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_CAL, MARKET_ETFS, synthetic_market
from models_helpers import market_config
from statarb.signals.registry import SIGNALS, make_signal
from statarb.signals.tables import TABLES, build_tables
from statarb.testing.lookahead import perturb_after, truncate_after

# The values of each table a perturbation changes.
COLUMNS = {
    "returns": ["ret"],
    "prices": ["open", "close", "volume"],
    "residuals": ["residual", "beta_market"],
}


# Parameters for each registered signal, chosen so every part of it runs: a multi-day,
# volatility-scaled reversal and a centred s-score on a window short enough for the fixture.
PARAMS = {
    "residual": {"lookback_days": 3, "vol_scaled": True, "vol_window_days": 60, "vol_min_observations": 45},
    "raw": {"lookback_days": 3, "vol_scaled": True, "vol_window_days": 60, "vol_min_observations": 45},
    "sscore": {"window_days": 30, "max_reversion_days": 30, "centre_means": True, "sector_etfs": MARKET_ETFS},
    "model": {"config": market_config(), "horizon": 3},
}


def _params(name: str) -> dict:
    return PARAMS[name]


def test_every_registered_signal_has_contract_parameters() -> None:
    assert set(PARAMS) == set(SIGNALS)


def _perturbed(long: dict, names: set[str], cutoff, seed: int) -> dict:
    """Copies of the tables with values after `cutoff` changed in those named; membership and
    sectors are reshuffled after it, since they have no values to scale."""
    out = dict(long)
    rng = np.random.default_rng(seed)
    for name in names:
        frame = long[name]
        if name in COLUMNS:
            out[name] = perturb_after(frame, cutoff, COLUMNS[name], seed=seed, scale=1.0)
        elif name == "universe":
            later = frame["date"] > cutoff
            keep = rng.random(len(frame)) < 0.6
            out[name] = frame.loc[~later | keep].reset_index(drop=True)
        elif name == "sectors":
            # Every third stock moves to the other sector on the day after the cut-off.
            move = MARKET_CAL[MARKET_CAL.searchsorted(cutoff, side="right")]
            picked = frame.index % 3 == 0
            ended = frame.assign(valid_to=frame["valid_to"].where(~picked, move))
            other = {"Financials": "Information Technology", "Information Technology": "Financials"}
            moved = frame.loc[picked].assign(sector=frame.loc[picked, "sector"].map(other), valid_from=move)
            out[name] = pd.concat([ended, moved], ignore_index=True)
    return out


def _scores(long: dict, name: str) -> np.ndarray:
    return make_signal(name, **_params(name)).scores(build_tables(*(long[t] for t in TABLES), "SPY", MARKET_ETFS)).score


@pytest.mark.parametrize("name", sorted(SIGNALS))
def test_signal_declares_tables_it_may_read(name: str) -> None:
    reads = make_signal(name, **_params(name)).reads
    assert reads and set(reads) <= set(TABLES)


@pytest.mark.parametrize("name", sorted(SIGNALS))
@pytest.mark.parametrize("cut", [100, 210])
def test_signal_has_no_look_ahead(name: str, cut: int) -> None:
    long = dict(zip(TABLES, synthetic_market(seed=11), strict=True))
    cutoff = MARKET_CAL[cut]
    signal = make_signal(name, **_params(name))
    before = _scores(long, name)
    after = _scores(_perturbed(long, set(signal.reads), cutoff, seed=cut), name)
    upto = cut + 1
    np.testing.assert_array_equal(before[:upto], after[:upto])
    assert not np.array_equal(np.nan_to_num(before[upto:]), np.nan_to_num(after[upto:]))   # the perturbation reached it


@pytest.mark.parametrize("name", sorted(SIGNALS))
def test_signal_reads_only_what_it_declares(name: str) -> None:
    long = dict(zip(TABLES, synthetic_market(seed=12), strict=True))
    signal = make_signal(name, **_params(name))
    others = set(TABLES) - set(signal.reads) - {"prices"}   # prices set the calendar, which every signal shares
    before = _scores(long, name)
    after = _scores(_perturbed(long, others, MARKET_CAL[0], seed=1), name)
    np.testing.assert_array_equal(before, after)


# Signals known to fail the row-removal test, each with the defect, until the fix that opens
# phase 6 (docs/phases/phase-06/brief.md, "From the phase 5 backlog walk"). Strict: a signal that
# starts passing fails the suite, so the entry is removed with the fix.
ROW_REMOVAL_DEFECTS = {
    "raw": "scores a member from its total returns before its first residual, only if it has a residual later",
    "sscore": "fits members from total returns before their first residual, and centres across them",
}
LATE = "S00"                       # a member throughout whose residuals start after the cut-offs below


def _with_late_residuals(long: dict) -> dict:
    r = long["residuals"]
    return {**long, "residuals": r.loc[(r["ticker"] != LATE) | (r["date"] >= MARKET_CAL[230])].reset_index(drop=True)}


def _score_frame(long: dict, name: str) -> pd.DataFrame:
    tables = build_tables(*(long[t] for t in TABLES), "SPY", MARKET_ETFS)
    return pd.DataFrame(make_signal(name, **_params(name)).scores(tables).score, index=tables.dates, columns=tables.stocks)


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(n, marks=pytest.mark.xfail(reason=ROW_REMOVAL_DEFECTS[n], strict=True)) if n in ROW_REMOVAL_DEFECTS else n
        for n in sorted(SIGNALS)
    ],
)
@pytest.mark.parametrize("cut", [100, 210])
def test_signal_unchanged_when_later_rows_are_removed(name: str, cut: int) -> None:
    long = _with_late_residuals(dict(zip(TABLES, synthetic_market(seed=11), strict=True)))
    cutoff = MARKET_CAL[cut]
    whole = _score_frame(long, name).loc[:cutoff]
    live = _score_frame(truncate_after(long, cutoff), name).reindex(columns=whole.columns)   # unknown stocks: no score
    pd.testing.assert_frame_equal(whole, live, check_exact=True, check_freq=False)


def test_row_removal_defects_name_registered_signals() -> None:
    assert set(ROW_REMOVAL_DEFECTS) <= set(SIGNALS)
