"""Effective bid-ask spread estimators from daily prices, each implemented from its paper.

Each returns the relative spread (0.001 = 10 bps, round trip, so a one-way
trade pays half of it) over a window of days. Inputs are (days x names) arrays
of open, high, low and close on one price basis within the window; the
estimators use log price differences across consecutive days, so unadjusted
prices are made split-consistent first (`statarb.backtest.costs.split_consistent`).

- "edge": Ardia, Guidotti and Kroencke (2024), "Efficient estimation of
  bid-ask spreads from open, high, low, and close prices", Journal of
  Financial Economics 161. Two moment conditions on the open, high, low and
  close, combined with weights inverse to their variances.
- "ar": Abdi and Ranaldo (2017), from close, high and low: the squared-spread
  term of each pair of days averaged over the window before the square root.
- "cs": Corwin and Schultz (2012), from high and low over two-day periods with
  their adjustment for overnight moves, averaged over the window.

All three return a signed estimate: negative when the window's data imply a
negative squared spread. Callers decide how to floor it.

Each reads negative serial covariance of prices as bid-ask bounce. Daily
reversal is negative serial covariance too, so an estimate can rise with the
very effect a reversal strategy trades (decision record 0005).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

ESTIMATORS = ("edge", "ar", "cs")


def _lag(x: np.ndarray) -> np.ndarray:
    out = np.full_like(x, np.nan)
    out[1:] = x[:-1]
    return out


def _nanmean(x: np.ndarray) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(x, axis=0)


def _signed_root(s2: np.ndarray) -> np.ndarray:
    return np.sign(s2) * np.sqrt(np.abs(s2))


@dataclass(frozen=True)
class Terms:
    """Per-day terms of the three estimators, computed once on the full panel."""

    r1: np.ndarray      # EDGE: mid-range less open
    r2: np.ndarray      # open less the previous mid-range
    r3: np.ndarray      # mid-range less the previous close
    r4: np.ndarray      # previous close less the previous mid-range
    r5: np.ndarray      # open less the previous close
    tau: np.ndarray     # 1 on a day with a price range or a move from the previous close
    po1: np.ndarray     # open differs from the high, on such days
    po2: np.ndarray     # open differs from the low
    pc1: np.ndarray     # previous close differs from the previous high
    pc2: np.ndarray     # previous close differs from the previous low
    ar: np.ndarray      # Abdi and Ranaldo's squared-spread term for the pair (t-1, t)
    cs: np.ndarray      # Corwin and Schultz's two-day spread


def terms(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Terms:
    with np.errstate(divide="ignore", invalid="ignore"):
        o, h, l, c = (np.log(np.where(x > 0, x, np.nan)) for x in (open_, high, low, close))
    m = (h + l) / 2
    h1, l1, c1, m1 = _lag(h), _lag(l), _lag(c), _lag(m)

    valid = np.isfinite(h) & np.isfinite(l) & np.isfinite(c1)
    tau = np.where(valid, ((h != l) | (l != c1)).astype(float), np.nan)

    # Corwin and Schultz: shift day t's range by any overnight gap from the close of t-1.
    gap = np.maximum(0.0, c1 - h) + np.minimum(0.0, c1 - l)
    ah, al = h + gap, l + gap
    beta = (h - l) ** 2 + (h1 - l1) ** 2
    gamma = (np.maximum(ah, h1) - np.minimum(al, l1)) ** 2
    k = 3 - 2 * np.sqrt(2)
    with np.errstate(invalid="ignore"):
        alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)

    return Terms(
        r1=m - o,
        r2=o - m1,
        r3=m - c1,
        r4=c1 - m1,
        r5=o - c1,
        tau=tau,
        po1=tau * (o != h),
        po2=tau * (o != l),
        pc1=tau * (c1 != h1),
        pc2=tau * (c1 != l1),
        ar=4 * (c1 - m1) * (c1 - m),
        cs=2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha)),
    )


def _edge_window(t: Terms, rows: slice, min_observations: int) -> np.ndarray:
    tau = t.tau[rows]
    pt = _nanmean(tau)
    po = _nanmean(t.po1[rows]) + _nanmean(t.po2[rows])
    pc = _nanmean(t.pc1[rows]) + _nanmean(t.pc2[rows])
    nt = np.nansum(tau, axis=0)
    r1, r2, r3, r4, r5 = (x[rows] for x in (t.r1, t.r2, t.r3, t.r4, t.r5))
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = r1 - _nanmean(r1) / pt * tau
        d3 = r3 - _nanmean(r3) / pt * tau
        d5 = r5 - _nanmean(r5) / pt * tau
        x1 = -4.0 / po * d1 * r2 + -4.0 / pc * d3 * r4
        x2 = -4.0 / po * d1 * r5 + -4.0 / pc * d5 * r4
        e1, e2 = _nanmean(x1), _nanmean(x2)
        v1 = _nanmean(x1**2) - e1**2
        v2 = _nanmean(x2**2) - e2**2
        vt = v1 + v2
        s2 = np.where(np.isfinite(vt) & (vt > 0), (v2 * e1 + v1 * e2) / vt, (e1 + e2) / 2)
    ok = (nt >= max(min_observations, 2)) & (po > 0) & (pc > 0)
    return np.where(ok, _signed_root(s2), np.nan)


def rolling_spread(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    method: str,
    window: int,
    min_observations: int,
) -> np.ndarray:
    """Signed spread over the `window` days ending at each row (inclusive), per name.

    Row t uses prices up to and including day t, plus the close, high and low of
    the day before the window for the lagged terms. NaN where fewer than
    `min_observations` usable days fall in the window.
    """
    if method not in ESTIMATORS:
        raise ValueError(f"unknown spread estimator {method!r}; expected one of {ESTIMATORS}")
    t = terms(open_, high, low, close)
    T, N = close.shape
    out = np.full((T, N), np.nan)
    if method == "edge":
        for end in range(T):
            out[end] = _edge_window(t, slice(max(0, end - window + 1), end + 1), min_observations)
        return out
    per_day = t.ar if method == "ar" else t.cs
    valid = np.isfinite(per_day)
    csum = np.vstack([np.zeros((1, N)), np.cumsum(np.where(valid, per_day, 0.0), axis=0)])
    ccount = np.vstack([np.zeros((1, N)), np.cumsum(valid, axis=0)])
    for end in range(T):
        start = max(0, end - window + 1)
        n = ccount[end + 1] - ccount[start]
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = (csum[end + 1] - csum[start]) / n
        out[end] = np.where(n >= min_observations, mean, np.nan)
    return _signed_root(out) if method == "ar" else out


def window_spread(
    open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, method: str, min_observations: int = 2
) -> np.ndarray:
    """One signed estimate per name over all rows of the input."""
    return rolling_spread(open_, high, low, close, method, len(close), min_observations)[-1]


def pooled(signed: np.ndarray) -> float:
    """One spread from many signed estimates: the root of their mean signed square, floored at zero.

    Averaging signed squares rather than roots keeps the average unbiased when
    single estimates are noisy enough to be negative.
    """
    sq = np.sign(signed) * signed**2
    return float(np.sqrt(max(np.nanmean(sq), 0.0)))
