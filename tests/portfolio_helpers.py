"""A phase 4 lab on the synthetic market of `helpers.synthetic_market`: no real data."""

from __future__ import annotations

import numpy as np

from helpers import MARKET_CAL, MARKET_ETFS, PCA, model_b, synthetic_market
from statarb.backtest.config import BacktestConfig, CostConfig
from statarb.backtest.cost_run import build_lab
from statarb.config import load_config
from statarb.portfolio.config import PortfolioConfig
from statarb.portfolio.run import PortfolioLab, build_portfolio_lab
from statarb.signals.tables import build_tables

BOOKS = (500_000, 5_000_000)


def backtest_config() -> BacktestConfig:
    raw = load_config("backtest")
    raw["period"]["start"] = MARKET_CAL[60].date()
    raw["sscore"]["window_days"] = 30
    raw["signals"] = [{"name": n, "lookbacks": [1, 3], "vol_scaled": [False]} for n in ("residual", "raw")]
    raw["headline"] = {"signal": "residual", "lookback_days": 1, "vol_scaled": False, "holding_days": 1}
    raw["sweep"]["holding_days"] = [1, 2]
    return BacktestConfig.from_dict(raw)


def cost_config(cfg: BacktestConfig) -> CostConfig:
    raw = load_config("costs")
    raw["variants"] = [
        {"name": "baseline", "signal": "residual", "lookback_days": 1, "vol_scaled": False, "holding_days": 2},
        {"name": "three-day lookback", "signal": "residual", "lookback_days": 3, "vol_scaled": False, "holding_days": 2},
    ]
    raw["run"] = {"fill": "open_t1", "book_sizes": list(BOOKS), "headline_book": BOOKS[0]}
    raw["spread"] = {**raw["spread"], "window_days": 40, "min_observations": 30}
    raw["impact"] = {**raw["impact"], "volatility_window_days": 20, "volatility_min_observations": 15, "volume_window_days": 10, "volume_min_observations": 8}
    raw["no_trade"] = {"calibration_window_days": 60, "calibration_min_days": 20}
    return CostConfig.from_dict(raw, cfg)


def portfolio_raw() -> dict:
    raw = load_config("portfolio")
    raw["run"] = {**raw["run"], "book_sizes": list(BOOKS)}
    raw["optimiser"] = {**raw["optimiser"], "horizon_days": 2}
    raw["risk"] = {**raw["risk"], "factor_window_days": 40, "factor_min_observations": 30, "specific_window_days": 20, "specific_min_observations": 10}
    return raw


def synthetic_lab(long=None, raw: dict | None = None) -> PortfolioLab:
    """The lab on the synthetic market (or the given long tables), with Model B fitted on its returns."""
    returns, prices, residuals, universe, sectors = long or synthetic_market(seed=5)
    residuals = residuals.assign(beta_sector=0.5)
    tables = build_tables(returns, prices, residuals, universe, sectors, "SPY", MARKET_ETFS)
    cfg = backtest_config()
    ccfg = cost_config(cfg)
    pc = PortfolioConfig.from_dict(raw or portfolio_raw(), ccfg)
    lab = build_lab(tables, cfg, ccfg, MARKET_ETFS)
    return build_portfolio_lab(lab, pc, residuals, model_b(returns, tables.stocks), MARKET_ETFS, PCA.factors)


def first_decision(plab: PortfolioLab) -> int:
    move = plab.moves[(plab.pc.run.variant, "etf")]
    return int(np.flatnonzero(np.isfinite(move).any(axis=1) & (np.arange(len(move)) >= plab.lab.start))[0])
