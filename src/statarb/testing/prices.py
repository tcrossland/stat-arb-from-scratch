"""Simulated daily prices with a known spread, for checking spread estimators.

Used by the tests and by the phase 3 report's check of what the estimators
measure. No real data enters.
"""

from __future__ import annotations

import numpy as np


def simulate_ohlc(
    days: int,
    names: int,
    spread: float,
    vol: float,
    rho: float = 0.0,
    open_noise: float = 0.0,
    seed: int = 0,
    steps: int = 78,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Daily open, high, low and close from an efficient log price traded at random sides of a known relative spread.

    Each day the efficient price takes `steps` normal steps with daily volatility
    `vol`, and each trade prints half the round-trip `spread` above or below it.
    `rho` adds to each day's path a drift of `rho` times the previous day's
    efficient move, so a negative value makes part of every move reverse over
    the next day. `open_noise` moves the opening print away from the efficient
    price by a normal amount with that standard deviation in log terms.
    """
    rng = np.random.default_rng(seed)
    o, h, l, c = (np.empty((days, names)) for _ in range(4))
    level, prev = np.zeros(names), np.zeros(names)
    for d in range(days):
        path = level + np.cumsum(rng.normal(0, vol / np.sqrt(steps), (steps, names)) + rho * prev / steps, axis=0)
        p = path + rng.choice([-1.0, 1.0], (steps, names)) * spread / 2
        p[0] = path[0] + rng.normal(0, open_noise, names) if open_noise else p[0]
        o[d], h[d], l[d], c[d] = p[0], p.max(axis=0), p.min(axis=0), p[-1]
        prev, level = path[-1] - level, path[-1]
    return tuple(np.exp(x) for x in (o, h, l, c))
