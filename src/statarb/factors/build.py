"""Residual returns from the phase 0 tables: Model A (phase 1) or Model B (phase 4).

    uv run python -m statarb.factors.build [--model etf|pca]

Reads the tables in `[paths] processed` of config/data.toml, with
config/factors.toml. Model A, the default, writes residuals.parquet beside them
and the diagnostics report and its charts to reports/phase-01/. Model B writes
residuals_pca.parquet and compares itself with Model A, whose table it reads,
in reports/phase-04/model_b.md.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import pandas as pd

from statarb.config import load_config, repo_root, resolve_path
from statarb.data.schema import DATE, TICKER
from statarb.factors.compare import compare_models
from statarb.factors.events import volume_ratio
from statarb.factors.model import EtfFactorModel, EtfModelConfig
from statarb.factors.pca import PcaFactorModel, PcaModelConfig
from statarb.factors.report import diagnostics, save_figure, write_report
from statarb.io import read_parquet, write_parquet

EVENT_KEYS = {"lookback_days", "volume_ratio"}


def stocks_to_model(candidates: pd.DataFrame, returns: pd.DataFrame) -> list[str]:
    """Candidates with any returns; the factor ETFs are not candidates, so they are left out."""
    return sorted(set(candidates[TICKER]) & set(returns[TICKER]))


def market_calendar(returns: pd.DataFrame, market: str) -> pd.DatetimeIndex:
    """The trading days with a market return: the rows of every panel."""
    return pd.DatetimeIndex(sorted(returns.loc[returns[TICKER] == market, DATE].unique()))


def build_residuals(
    returns: pd.DataFrame,
    sectors: pd.DataFrame,
    prices: pd.DataFrame,
    stocks: list[str],
    factors_cfg: dict[str, Any],
    market: str,
) -> pd.DataFrame:
    """Model A's residuals with the event flag, one row per (date, stock) with a residual."""
    events = factors_cfg["events"]
    if set(events) != EVENT_KEYS:
        raise ValueError(f"[events] keys must be {sorted(EVENT_KEYS)}, got {sorted(events)}")
    model = EtfFactorModel(EtfModelConfig.from_config(factors_cfg["model"], factors_cfg["sector_etfs"], market))
    calendar = market_calendar(returns, market)
    out = model.residuals(returns, sectors, stocks, calendar)

    ratio = volume_ratio(prices, returns, sorted(stocks), calendar, events["lookback_days"])
    ratio_long = ratio.stack(future_stack=True).rename("volume_ratio").reset_index()
    ratio_long.columns = [DATE, TICKER, "volume_ratio"]
    out = out.merge(ratio_long, on=[DATE, TICKER], how="left", validate="one_to_one")
    out["event"] = (out["volume_ratio"] >= events["volume_ratio"]).fillna(False).astype(bool)
    return out.sort_values([DATE, TICKER], kind="mergesort").reset_index(drop=True)


def build_pca_residuals(returns: pd.DataFrame, stocks: list[str], factors_cfg: dict[str, Any], market: str) -> pd.DataFrame:
    """Model B's residuals, one row per (date, stock) with a residual, over the same stocks and calendar as Model A."""
    model = PcaFactorModel(PcaModelConfig.from_config(factors_cfg["pca"]))
    out = model.residuals(returns, pd.DataFrame(), stocks, market_calendar(returns, market))
    return out.sort_values([DATE, TICKER], kind="mergesort").reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", choices=["etf", "pca"], default="etf", help="etf: Model A (phase 1); pca: Model B (phase 4)")
    args = parser.parse_args(argv)
    root = repo_root()
    data_cfg = load_config("data", root)
    factors_cfg = load_config("factors", root)
    processed = resolve_path(data_cfg["paths"]["processed"], root)
    reports = resolve_path(data_cfg["paths"]["reports"], root)

    returns = read_parquet(processed / "returns.parquet")
    sectors = read_parquet(processed / "sectors.parquet")
    prices = read_parquet(processed / "prices.parquet")
    stocks = stocks_to_model(read_parquet(processed / "candidates.parquet"), returns)

    if args.model == "pca":
        pca = build_pca_residuals(returns, stocks, factors_cfg, data_cfg["factors"]["market"])
        write_parquet(pca, processed / "residuals_pca.parquet", [DATE, TICKER])
        print(f"residuals_pca: {len(pca)} rows", file=sys.stderr)
        report = compare_models(
            read_parquet(processed / "residuals.parquet"), pca, read_parquet(processed / "universe.parquet"), prices, factors_cfg["report"]
        )
        out_dir = reports / "phase-04"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, fig in report.figures.items():
            save_figure(fig, out_dir / name)
        (out_dir / "model_b.md").write_text(report.text)
        return 0

    residuals = build_residuals(returns, sectors, prices, stocks, factors_cfg, data_cfg["factors"]["market"])
    write_parquet(residuals, processed / "residuals.parquet", [DATE, TICKER])
    print(f"residuals: {len(residuals)} rows", file=sys.stderr)

    report = diagnostics(
        residuals,
        universe=read_parquet(processed / "universe.parquet"),
        sectors=sectors,
        prices=prices,
        cfg=factors_cfg["report"],
    )
    write_report(report, reports / "phase-01")
    return 0


if __name__ == "__main__":
    sys.exit(main())
