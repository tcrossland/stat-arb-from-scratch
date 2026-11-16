"""Model A: each stock's return on the market ETF and its sector's ETF.

For stock i on day t, with betas estimated over the window ending t-1:

    residual = ret - beta_market * market_t - beta_sector * sector_t

where sector_t is the return of the ETF for the stock's GICS sector on t
(minus the market's return with the "excess" factor). The sector series in
each window uses the ETF that applied on each day, so a stock that changes
sector carries a spliced series rather than restarting its window. The
intercept is estimated, so drift does not bias the betas, but it is not
subtracted from the residual.

If the stock's sector has no ETF on t, or too few days in the window have one,
the model falls back to the market alone and marks the row market_only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, fields
from typing import Any, Protocol

import numpy as np
import pandas as pd

from statarb.data.schema import DATE, TICKER
from statarb.factors.rolling import rolling_ols

SECTOR_FACTORS = ("excess", "raw")


class FactorModel(Protocol):
    """A factor model: residual returns for every stock and day it can estimate.

    Model A is the ETF regression below; Model B, statistical factors from
    PCA, joins in phase 4.
    """

    name: str

    def residuals(
        self, returns: pd.DataFrame, sectors: pd.DataFrame, stocks: Sequence[str], calendar: pd.DatetimeIndex
    ) -> pd.DataFrame:
        """One row per (date, stock) with a residual: see docs/data-model.md, residuals."""
        ...


@dataclass(frozen=True)
class EtfModelConfig:
    market: str
    sector_etfs: dict[str, str]
    window_days: int
    min_observations: int
    sector_factor: str

    @classmethod
    def from_config(cls, model: dict[str, Any], sector_etfs: dict[str, str], market: str) -> EtfModelConfig:
        """From `[model]` and `[sector_etfs]` of config/factors.toml; unknown or missing keys fail."""
        expected = {f.name for f in fields(cls)} - {"market", "sector_etfs"}
        if set(model) != expected:
            raise ValueError(f"[model] keys: missing {sorted(expected - set(model))}, unknown {sorted(set(model) - expected)}")
        cfg = cls(market=market, sector_etfs=dict(sector_etfs), **model)
        if cfg.sector_factor not in SECTOR_FACTORS:
            raise ValueError(f"sector_factor must be one of {SECTOR_FACTORS}")
        if not 0 < cfg.min_observations <= cfg.window_days:
            raise ValueError("min_observations must be in 1..window_days")
        return cfg


def wide(frame: pd.DataFrame, values: str, calendar: pd.DatetimeIndex, columns: Sequence[str]) -> pd.DataFrame:
    """Calendar x columns panel from a long frame; NaN where missing."""
    panel = frame.pivot(index=DATE, columns=TICKER, values=values)
    return panel.reindex(index=calendar, columns=list(columns))


def sector_etf_panel(
    sectors: pd.DataFrame, stocks: Sequence[str], calendar: pd.DatetimeIndex, sector_etfs: dict[str, str]
) -> np.ndarray:
    """(dates, stocks) array of the ETF symbol that applied to each stock on each day, or None."""
    out = np.full((len(calendar), len(stocks)), None, dtype=object)
    col = {t: j for j, t in enumerate(stocks)}
    for row in sectors.itertuples(index=False):
        j = col.get(row.ticker)
        if j is None:
            continue
        end = row.valid_to if pd.notna(row.valid_to) else pd.Timestamp.max
        days = (calendar >= row.valid_from) & (calendar < end)
        out[days, j] = sector_etfs.get(row.sector)
    return out


class EtfFactorModel:
    """Model A behind the FactorModel protocol."""

    name = "etf"

    def __init__(self, config: EtfModelConfig) -> None:
        self.config = config

    def residuals(
        self, returns: pd.DataFrame, sectors: pd.DataFrame, stocks: Sequence[str], calendar: pd.DatetimeIndex
    ) -> pd.DataFrame:
        cfg = self.config
        stocks = sorted(stocks)
        etfs = sorted(set(cfg.sector_etfs.values()))
        y = wide(returns, "ret", calendar, stocks).to_numpy()
        market = wide(returns, "ret", calendar, [cfg.market]).to_numpy()[:, 0]
        etf_returns = wide(returns, "ret", calendar, etfs).to_numpy()

        etf_of = sector_etf_panel(sectors, stocks, calendar, cfg.sector_etfs)
        index = {e: k for k, e in enumerate(etfs)}
        k = np.vectorize(lambda e: index.get(e, -1), otypes=[np.int64])(etf_of)
        rows = np.arange(len(calendar))[:, None]
        if etfs:
            sector = np.where(k >= 0, etf_returns[rows, np.maximum(k, 0)], np.nan)
        else:
            sector = np.full(y.shape, np.nan)
        if cfg.sector_factor == "excess":
            sector = sector - market[:, None]
        mkt = np.broadcast_to(market[:, None], y.shape)

        both = rolling_ols(y, [mkt, sector], cfg.window_days, cfg.min_observations)
        alone = rolling_ols(y, [mkt], cfg.window_days, cfg.min_observations)

        use_both = np.isfinite(both.coef[..., 0]) & np.isfinite(sector)
        use_alone = ~use_both & np.isfinite(alone.coef[..., 0])
        alpha = np.where(use_both, both.coef[..., 0], alone.coef[..., 0])
        beta_market = np.where(use_both, both.coef[..., 1], alone.coef[..., 1])
        beta_sector = np.where(use_both, both.coef[..., 2], np.nan)
        n_obs = np.where(use_both, both.n_obs, alone.n_obs)
        fitted = beta_market * mkt + np.where(use_both, beta_sector * sector, 0.0)

        keep = (use_both | use_alone) & np.isfinite(y) & np.isfinite(market)[:, None]
        t_idx, s_idx = np.nonzero(keep)
        out = pd.DataFrame(
            {
                DATE: calendar[t_idx],
                TICKER: np.asarray(stocks, dtype=object)[s_idx],
                "ret": y[t_idx, s_idx],
                "fitted": fitted[t_idx, s_idx],
                "residual": y[t_idx, s_idx] - fitted[t_idx, s_idx],
                "alpha": alpha[t_idx, s_idx],
                "beta_market": beta_market[t_idx, s_idx],
                "beta_sector": beta_sector[t_idx, s_idx],
                "sector_etf": pd.array(np.where(use_both, etf_of, None)[t_idx, s_idx], dtype="str"),
                "n_obs": n_obs[t_idx, s_idx].astype("int64"),
                "market_only": use_alone[t_idx, s_idx],
            }
        )
        return out.astype({DATE: "datetime64[ns]", TICKER: "str"})
