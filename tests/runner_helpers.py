"""The phase 5 runners' settings on the synthetic market: development to day 260, the holdout after it."""

from __future__ import annotations

import dataclasses

import pandas as pd

from helpers import MARKET_CAL, MARKET_ETFS, synthetic_market
from models_helpers import market_config
from portfolio_helpers import backtest_config, cost_config, portfolio_raw
from statarb.models.run import Settings
from statarb.portfolio.config import PortfolioConfig

DEV_END = 260


def market_long() -> dict[str, pd.DataFrame]:
    """The synthetic market's long tables, with a constant sector beta for Model A risk."""
    returns, prices, residuals, universe, sectors = synthetic_market(seed=5)
    return {"returns": returns, "prices": prices, "residuals": residuals.assign(beta_sector=0.5), "universe": universe, "sectors": sectors}


def market_settings(**runs) -> Settings:
    cfg = backtest_config()
    ccfg = cost_config(cfg)
    mc = market_config(first_test=150, block_days=40)
    period = dataclasses.replace(
        mc.period, development_end=MARKET_CAL[DEV_END].date(), holdout_start=MARKET_CAL[DEV_END + 1].date(), holdout_end=MARKET_CAL[-1].date()
    )
    mc = dataclasses.replace(mc, period=period, runs=dataclasses.replace(mc.runs, **runs))
    return Settings(mc, cfg, ccfg, PortfolioConfig.from_dict(portfolio_raw(), ccfg), "SPY", MARKET_ETFS, 3.0)
