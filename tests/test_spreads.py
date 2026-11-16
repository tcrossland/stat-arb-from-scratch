"""The daily-price spread estimators on simulated prices with a known spread.

Each estimator recovers a large spread on prices with no other structure, and
overstates a small one when the prices also reverse or the open is noisy
(decision record 0005).
"""

from __future__ import annotations

import numpy as np
import pytest

from statarb.backtest.spreads import pooled, rolling_spread, window_spread
from statarb.testing.prices import simulate_ohlc


@pytest.mark.parametrize("method, tolerance", [("edge", 0.05), ("ar", 0.15), ("cs", 0.15)])
def test_estimators_recover_a_large_known_spread(method: str, tolerance: float) -> None:
    # 390 trades a day: Corwin and Schultz assume near-continuous trading and understate spreads with fewer.
    prices = simulate_ohlc(500, 20, spread=0.01, vol=0.02, seed=1, steps=390)
    assert pooled(window_spread(*prices, method)) == pytest.approx(0.01, rel=tolerance)


@pytest.mark.parametrize("method", ["edge", "ar", "cs"])
def test_estimators_rise_with_reversal_at_a_fixed_spread(method: str) -> None:
    # Decision record 0005: the true spread stays 2 bps, and each estimate grows with the
    # share of each day's move that reverses the next day, the effect the strategy trades.
    estimates = [pooled(window_spread(*simulate_ohlc(252, 40, 0.0002, 0.015, rho=r, seed=2), method)) for r in (0.0, -0.1, -0.2)]
    assert estimates[0] < 0.0005
    assert estimates[0] < estimates[1] < estimates[2]
    assert estimates[2] > 0.0010            # at least five times the true spread


def test_a_noisy_open_inflates_edge() -> None:
    clean = pooled(window_spread(*simulate_ohlc(252, 40, 0.0002, 0.015, seed=2), "edge"))
    noisy = pooled(window_spread(*simulate_ohlc(252, 40, 0.0002, 0.015, open_noise=0.002, seed=2), "edge"))
    assert clean < 0.0005 and noisy > 0.001


def test_rolling_spread_uses_only_the_window_ending_on_each_day() -> None:
    o, h, l, c = simulate_ohlc(60, 3, spread=0.01, vol=0.02, seed=3)
    for method in ("edge", "ar", "cs"):
        full = rolling_spread(o, h, l, c, method, 20, 15)
        cut = rolling_spread(o[:40], h[:40], l[:40], c[:40], method, 20, 15)
        np.testing.assert_array_equal(full[:40], cut)
        assert np.isnan(full[:13]).all() and np.isfinite(full[20:]).all()
    with pytest.raises(ValueError, match="unknown"):
        rolling_spread(o, h, l, c, "roll", 20, 15)
