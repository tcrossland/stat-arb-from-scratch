"""The tables a signal or a backtest reads, as dates-by-tickers panels.

Built from the phase 0 and 1 tables in long format. Every panel is indexed by
the trading calendar of the market ETF, and a value on a date is what was known
after the close of that date (docs/time-discipline.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from statarb.data.schema import DATE, TICKER
from statarb.factors.model import EtfModelConfig, sector_etf_panel, wide
from statarb.io import read_parquet

# The stored tables a signal may declare it reads (docs/data-model.md).
TABLES = ("returns", "prices", "residuals", "universe", "sectors")


@dataclass(frozen=True)
class Tables:
    dates: pd.DatetimeIndex
    stocks: list[str]            # stocks with residuals, in column order
    hedges: list[str]            # sector ETFs then the market, for the s-score's hedges
    market: str
    residual: pd.DataFrame       # dates x stocks
    beta_market: pd.DataFrame    # dates x stocks, Model A's market beta
    raw: pd.DataFrame            # dates x stocks, total returns
    members: np.ndarray          # dates x stocks, universe membership on each date
    returns: pd.DataFrame        # the long phase 0 tables, for the fill grids and attribution
    prices: pd.DataFrame
    sectors: pd.DataFrame

    @property
    def tickers(self) -> list[str]:
        """Engine columns: stocks, then hedge instruments."""
        return self.stocks + self.hedges


def build_tables(
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    residuals: pd.DataFrame,
    universe: pd.DataFrame,
    sectors: pd.DataFrame,
    market: str,
    sector_etfs: dict[str, str],
) -> Tables:
    dates = pd.DatetimeIndex(sorted(prices.loc[prices[TICKER] == market, DATE].unique()))
    stocks = sorted(residuals[TICKER].unique())
    hedges = sorted(set(sector_etfs.values())) + [market]
    members = (
        universe.assign(member=True)
        .pivot(index=DATE, columns=TICKER, values="member")
        .reindex(index=dates, columns=stocks)
        .fillna(False)
        .to_numpy(dtype=bool)
    )
    return Tables(
        dates=dates,
        stocks=stocks,
        hedges=hedges,
        market=market,
        residual=wide(residuals, "residual", dates, stocks),
        beta_market=wide(residuals, "beta_market", dates, stocks),
        raw=wide(returns, "ret", dates, stocks),
        members=members,
        returns=returns,
        prices=prices,
        sectors=sectors,
    )


def sector_inputs(tables: Tables, sector_etfs: dict[str, str]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Stock returns, market returns, the excess sector factor and each stock's hedge-column index.

    The sector factor is the return of the ETF of the stock's sector on each day
    minus the market's, as in Model A; NaN where the sector has no ETF, where the
    index is -1.
    """
    cfg = EtfModelConfig(tables.market, sector_etfs, 1, 1, "excess")
    etfs = tables.hedges[:-1]
    market = wide(tables.returns, "ret", tables.dates, [tables.market]).to_numpy()[:, 0]
    etf_ret = wide(tables.returns, "ret", tables.dates, etfs).to_numpy()
    etf_of = sector_etf_panel(tables.sectors, tables.stocks, tables.dates, cfg.sector_etfs)
    index = {e: k for k, e in enumerate(etfs)}
    k = np.vectorize(lambda e: index.get(e, -1), otypes=[np.int64])(etf_of)
    rows = np.arange(len(tables.dates))[:, None]
    sector = np.where(k >= 0, etf_ret[rows, np.maximum(k, 0)], np.nan) - market[:, None]
    y = tables.raw.to_numpy()
    return y, market, sector, k


def load_tables(processed: Path, market: str, sector_etfs: dict[str, str]) -> Tables:
    return build_tables(*(read_parquet(processed / f"{name}.parquet") for name in TABLES), market, sector_etfs)
