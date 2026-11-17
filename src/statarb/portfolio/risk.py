"""Risk models for the optimiser: each stock's factor loadings, the factor covariance and specific variance, per day.

Two implementations behind `RiskModel`, chosen by name in config. Row t of
every panel uses data up to the close of t only (docs/time-discipline.md):

- Model A (`EtfRisk`): the loadings are the market beta and the sector beta on
  the residual row for t, estimated to t-1. The factors are the market and each
  sector ETF's return less the market's; their covariance comes from the
  trailing window of factor returns ending t.
- Model B (`PcaRisk`): the loadings are the betas on the eigenportfolios on the
  residual row for t, and the factor covariance is diag(eigenvalues), which is
  exact over the window the eigenportfolios were fitted on
  (`statarb.factors.pca`).

Specific variance is each stock's residual variance over a trailing window
ending t, filled with the day's median where a stock's history is too short.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from statarb.backtest.costs import fill_missing_by_row
from statarb.factors.model import wide
from statarb.factors.pca import beta_columns, eigenvalue_columns
from statarb.signals.tables import Tables, sector_inputs


@dataclass(frozen=True)
class DayRisk:
    loadings: np.ndarray        # (stocks, factors); NaN rows for stocks without loadings
    factor_cov: np.ndarray      # (factors, factors), daily
    specific_var: np.ndarray    # (stocks,), daily


class RiskModel(Protocol):
    """The daily covariance of the stocks as loadings, factor covariance and specific variance."""

    name: str

    def day(self, t: int) -> DayRisk | None:
        """Risk as known at the close of day t, or None if the model has none that day."""
        ...


def rolling_specific_var(residual: np.ndarray, window: int, min_obs: int) -> np.ndarray:
    """Residual variance over rows t-window+1 to t, NaN filled with the row's median."""
    var = pd.DataFrame(residual).rolling(window, min_periods=min_obs).var().to_numpy()
    return fill_missing_by_row(var)


@dataclass(frozen=True)
class EtfRisk:
    """Model A risk: the market plus one excess-return factor per sector ETF."""

    factors: np.ndarray          # (dates, 1 + sector ETFs): market, then each ETF less the market
    beta_market: np.ndarray      # (dates, stocks)
    beta_sector: np.ndarray      # (dates, stocks)
    etf_index: np.ndarray        # (dates, stocks): the column of each stock's sector ETF, -1 for none
    specific: np.ndarray         # (dates, stocks)
    window: int
    min_obs: int
    name: str = "etf"

    def day(self, t: int) -> DayRisk | None:
        lo = max(0, t - self.window + 1)
        f = self.factors[lo : t + 1]
        f = f[np.isfinite(f[:, 0])]
        if len(f) < self.min_obs:
            return None
        # A sector ETF that did not trade yet (XLC, XLRE) has no rows: its covariance comes from
        # the rows it has, and it has zero variance with none.
        cov = pd.DataFrame(f).cov(min_periods=2).fillna(0.0).to_numpy()
        N, K = self.beta_market.shape[1], self.factors.shape[1]
        X = np.zeros((N, K))
        X[:, 0] = self.beta_market[t]
        k = self.etf_index[t]
        has = (k >= 0) & np.isfinite(self.beta_sector[t])
        X[np.flatnonzero(has), 1 + k[has]] = self.beta_sector[t][has]
        X[~np.isfinite(self.beta_market[t])] = np.nan
        return DayRisk(X, cov, self.specific[t])


def etf_risk(tables: Tables, sector_etfs: dict[str, str], beta_sector: np.ndarray, window: int, min_obs: int, spec_window: int, spec_min: int) -> EtfRisk:
    """Model A risk from the tables and the sector betas of Model A's residual table (dates x stocks)."""
    _, market, _, etf_index = sector_inputs(tables, sector_etfs)
    etfs = tables.hedges[:-1]
    etf_ret = wide(tables.returns, "ret", tables.dates, etfs).to_numpy()
    return EtfRisk(
        factors=np.column_stack([market, etf_ret - market[:, None]]),
        beta_market=tables.beta_market.to_numpy(),
        beta_sector=beta_sector,
        etf_index=etf_index,
        specific=rolling_specific_var(tables.residual.to_numpy(), spec_window, spec_min),
        window=window,
        min_obs=min_obs,
    )


@dataclass(frozen=True)
class PcaRisk:
    """Model B risk: the eigenportfolios as factors, with a diagonal factor covariance."""

    betas: np.ndarray            # (dates, stocks, factors)
    eigenvalues: np.ndarray      # (dates, factors)
    specific: np.ndarray         # (dates, stocks)
    name: str = "pca"

    def day(self, t: int) -> DayRisk | None:
        ev = self.eigenvalues[t]
        if not np.isfinite(ev).all():
            return None
        return DayRisk(self.betas[t], np.diag(ev), self.specific[t])


def pca_risk(residuals_pca: pd.DataFrame, dates: pd.DatetimeIndex, stocks: list[str], k: int, spec_window: int, spec_min: int) -> PcaRisk:
    """Model B risk from its residual table, on the given calendar and stocks."""
    betas = np.stack([wide(residuals_pca, c, dates, stocks).to_numpy() for c in beta_columns(k)], axis=-1)
    eig = residuals_pca.groupby("date")[eigenvalue_columns(k)].first().reindex(dates).to_numpy()
    specific = rolling_specific_var(wide(residuals_pca, "residual", dates, stocks).to_numpy(), spec_window, spec_min)
    return PcaRisk(betas, eig, specific)
