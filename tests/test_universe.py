from __future__ import annotations

import pandas as pd

from statarb.data.universe import build_universe, month_end_rebalance_dates
from statarb.testing.lookahead import assert_unchanged_through, perturb_after

CAL = pd.DatetimeIndex(pd.bdate_range("2021-01-01", "2021-06-30"))


def _panel(volumes: dict[str, float]) -> pd.DataFrame:
    frames = [
        pd.DataFrame({"date": CAL, "ticker": t, "close": 10.0, "volume": v + 0.001 * pd.RangeIndex(len(CAL))})
        for t, v in volumes.items()
    ]
    return pd.concat(frames, ignore_index=True)


def test_month_end_rebalance_dates() -> None:
    days = month_end_rebalance_dates(CAL)
    assert days[0] == pd.Timestamp("2021-01-29") and days[-1] == pd.Timestamp("2021-06-30")
    assert len(days) == 6


def test_top_names_by_dollar_volume_from_next_day() -> None:
    bars = _panel({"A": 300.0, "B": 200.0, "C": 100.0})
    u = build_universe(bars, ["A", "B", "C"], CAL, size=2, window=20, min_obs=20)
    assert u["date"].min() == pd.Timestamp("2021-02-01")           # first day after the January rebalance
    assert set(u.loc[u["date"] == pd.Timestamp("2021-02-01"), "ticker"]) == {"A", "B"}
    assert u["rebalanced_on"].min() == pd.Timestamp("2021-01-29")


def test_names_without_enough_history_are_not_ranked() -> None:
    bars = _panel({"A": 300.0, "B": 200.0})
    late = bars.loc[(bars["ticker"] == "A") | (bars["date"] >= pd.Timestamp("2021-01-25"))]
    u = build_universe(late, ["A", "B"], CAL, size=2, window=20, min_obs=20)
    assert set(u.loc[u["date"] == pd.Timestamp("2021-02-01"), "ticker"]) == {"A"}


def test_only_listed_tickers_are_ranked() -> None:
    bars = _panel({"A": 300.0, "SPY": 1e9})
    u = build_universe(bars, ["A"], CAL, size=2, window=20, min_obs=20)
    assert set(u["ticker"]) == {"A"}


def test_membership_has_no_look_ahead() -> None:
    """Perturbing prices and volumes after a cut-off leaves membership up to the cut-off unchanged."""
    bars = _panel({t: 100.0 * (i + 1) for i, t in enumerate("ABCDEFGH")})
    cutoff = pd.Timestamp("2021-04-15")
    base = build_universe(bars, list("ABCDEFGH"), CAL, size=4, window=20, min_obs=18)
    for seed in range(5):
        noisy = perturb_after(bars, cutoff, ["close", "volume"], seed=seed, scale=2.0)
        moved = build_universe(noisy, list("ABCDEFGH"), CAL, size=4, window=20, min_obs=18)
        assert_unchanged_through(base, moved, cutoff)
    # The perturbation is strong enough to change later membership.
    assert not base.loc[base["date"] > cutoff].reset_index(drop=True).equals(
        moved.loc[moved["date"] > cutoff].reset_index(drop=True)
    )
