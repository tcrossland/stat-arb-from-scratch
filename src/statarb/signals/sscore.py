"""Avellaneda and Lee (2010) s-score, the signal of the phase 2 threshold variant.

Estimation follows the paper's appendix, with our factor set:

1. On each day t, regress each stock's returns over the last `window` days,
   ending at t, on an intercept, SPY and its sector ETF in excess of SPY (the
   paper uses the sector ETF alone). The residuals are in-sample.
2. Cumulate them: X_k = e_1 + ... + e_k. With an intercept, X_window = 0.
3. Fit X_{k+1} = a + b X_k + noise. Then kappa = -252 ln b, m = a / (1 - b) and
   sigma_eq = sqrt(var(noise) / (1 - b^2)).
4. Optionally centre m on the day's average over universe members with a fit
   (their equation 18). s = (X_window - m) / sigma_eq.

Stocks trade only when the mean-reversion time, -1 / ln b trading days, is under
`max_reversion_days`, and only with a sector ETF on every day of the window.

Everything on day t uses returns up to the close of t. The thresholds that open
and close positions belong to a portfolio rule, not to the signal.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from statarb.signals.base import Hedge, Scores
from statarb.signals.tables import Tables, sector_inputs


@dataclass(frozen=True)
class SScoreFit:
    s: np.ndarray            # (dates x stocks) s-score; NaN without a fit
    beta_market: np.ndarray  # in-sample betas from the window ending at t
    beta_sector: np.ndarray
    tradeable: np.ndarray    # bool: fit exists and mean reversion is fast enough
    reversion_days: np.ndarray


def fit_sscores(
    y: np.ndarray,
    market: np.ndarray,
    sector: np.ndarray,
    members: np.ndarray,
    window: int,
    max_reversion_days: float,
    centre_means: bool,
    max_condition: float = 1e10,
) -> SScoreFit:
    """y and sector are (dates x stocks); market is (dates,). sector is the excess sector factor."""
    T, N = y.shape
    shape = (T, N)
    s_out = np.full(shape, np.nan)
    bm_out = np.full(shape, np.nan)
    bs_out = np.full(shape, np.nan)
    rev_out = np.full(shape, np.nan)
    tradeable = np.zeros(shape, dtype=bool)
    b_max = np.exp(-1.0 / max_reversion_days)
    for t in range(window - 1, T):
        rows = slice(t - window + 1, t + 1)
        Y, S, M = y[rows], sector[rows], market[rows]
        if not np.isfinite(M).all():
            continue
        cols = np.flatnonzero(np.isfinite(Y).all(axis=0) & np.isfinite(S).all(axis=0))
        if len(cols) == 0:
            continue
        Y, S = Y[:, cols], S[:, cols]
        ones = np.ones_like(S)
        Mb = np.broadcast_to(M[:, None], S.shape)
        X = np.stack([ones, Mb, S], axis=-1)                      # (window, n, 3)
        xtx = np.einsum("wni,wnj->nij", X, X)
        xty = np.einsum("wni,wn->ni", X, Y)
        good = np.linalg.cond(xtx) < max_condition
        coef = np.full((len(cols), 3), np.nan)
        if good.any():
            coef[good] = np.linalg.solve(xtx[good], xty[good][..., None])[..., 0]
        e = Y - np.einsum("wni,ni->wn", X, coef)
        cum = np.cumsum(e, axis=0)
        x0, x1 = cum[:-1], cum[1:]
        d0 = x0 - x0.mean(axis=0)
        var0 = (d0**2).mean(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            b = (d0 * (x1 - x1.mean(axis=0))).mean(axis=0) / var0
            a = x1.mean(axis=0) - b * x0.mean(axis=0)
            noise = x1 - a - b * x0
            var_noise = (noise**2).mean(axis=0)
            fit = good & (b > 0) & (b < 1) & (var_noise > 0)
            m = np.where(fit, a / (1 - b), np.nan)
            sigma_eq = np.where(fit, np.sqrt(var_noise / (1 - b**2)), np.nan)
        if centre_means:
            ref = fit & members[t, cols]
            if ref.any():
                m = m - m[ref].mean()
        s_out[t, cols] = (cum[-1] - m) / sigma_eq
        bm_out[t, cols] = coef[:, 1]
        bs_out[t, cols] = coef[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            rev_out[t, cols] = np.where(fit, -1.0 / np.log(b), np.nan)
        tradeable[t, cols] = fit & (b < b_max)
    return SScoreFit(s_out, bm_out, bs_out, tradeable, rev_out)


@dataclass(frozen=True)
class SScoreSignal:
    """The s-score as a `Signal`: NaN where the fit is missing or reverts too slowly to trade."""

    window_days: int
    max_reversion_days: float
    centre_means: bool
    sector_etfs: dict[str, str]
    name: str = "sscore"
    source: str = "sscore"

    @property
    def reads(self) -> tuple[str, ...]:
        # Universe membership sets the stocks whose equilibrium means are centred on.
        return ("returns", "sectors", "universe")

    def scores(self, tables: Tables) -> Scores:
        y, market, sector, etf_index = sector_inputs(tables, self.sector_etfs)
        fit = fit_sscores(y, market, sector, tables.members, self.window_days, self.max_reversion_days, self.centre_means)
        return Scores(np.where(fit.tradeable, fit.s, np.nan), Hedge(fit.beta_market, fit.beta_sector, etf_index))
