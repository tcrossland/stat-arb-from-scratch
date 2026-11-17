"""Phase 5 features and target, one row per universe member and day.

Every feature on day t uses data up to the close of t and nothing later
(docs/time-discipline.md). Features are computed as wide (dates x stocks)
panels from the signal tables and returned long, with explicit `date` and
`ticker` columns, for the member-days that have a residual on t. They are
recomputed in each run, not stored. Values are left on their natural scale: a
tree splits on order, and the regime features let it condition on the level.

    res_sum_n        residual return summed over the last n days
    res_vol_w        residual standard deviation over the last w days
    volume_ratio     volume on t over its median of the previous 20 days, split-consistent (phase 1)
    range            (high - low) / close on t
    from_high_w      total-return index on t over its high of the last w days, minus 1 (at most 0)
    from_low_w       total-return index on t over its low of the last w days, minus 1 (at least 0)
    market_vol       SPY daily return standard deviation over the last 20 days, the same for every stock on t
    dispersion       cross-sectional standard deviation of total returns on t over the members that have had a
                     residual on or before t, the same for every stock on t
    sector           GICS sector on t, coded by its position in `[features] sectors` (categorical)

The phase 1 event flag is volume_ratio of at least 3; the tree can split there
itself, so it is not a separate feature. Highs and lows for the distances are
of the close-to-close total-return index, not intraday prices, so splits and
dividends do not register as moves.

A feature across stocks counts only the stocks known on t. The stock axis of
the tables is every stock with a residual anywhere in the loaded tables, so a
cross-section over the whole axis would depend on whether a stock has a
residual later: a member before its first residual would count on t in a
backtest and not in a live run on t. Dispersion counts the members with a
residual on or before t. For the same reason the sector codes come from config,
not from the sectors present in the table.

The target for horizon H is the residual return over t+1 to t+H, known at the
close of t+H, ranked across the members that have one on t and scaled to
[-0.5, 0.5]. It is the one value here that is not known on t.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from statarb.data.schema import DATE, TICKER
from statarb.factors.events import volume_ratio
from statarb.factors.model import sector_etf_panel, wide
from statarb.models.config import Features
from statarb.signals.calibration import forward_sum
from statarb.signals.tables import Tables

SECTOR = "sector"


def feature_names(cfg: Features) -> list[str]:
    return [
        *(f"res_sum_{n}" for n in cfg.residual_sums),
        *(f"res_vol_{w}" for w in cfg.volatility_windows),
        "volume_ratio",
        "range",
        *(f"from_{side}_{w}" for w in cfg.extreme_windows for side in ("high", "low")),
        "market_vol",
        "dispersion",
        SECTOR,
    ]


@dataclass(frozen=True)
class FeatureSet:
    """Feature rows in (date, ticker) order, with each row's position in the date and stock axes of `Tables`."""

    frame: pd.DataFrame          # date, ticker, then one column per feature
    names: list[str]
    day: np.ndarray              # row -> index into dates
    col: np.ndarray              # row -> index into stocks

    def matrix(self) -> np.ndarray:
        return self.frame[self.names].to_numpy(dtype="float64")

    def values_of(self, panel: np.ndarray) -> np.ndarray:
        """A (dates x stocks) panel read at each row."""
        return panel[self.day, self.col]

    def to_panel(self, values: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
        """Row values back to a (dates x stocks) panel, NaN elsewhere."""
        out = np.full(shape, np.nan)
        out[self.day, self.col] = values
        return out


def _min_periods(window: int, fraction: float) -> int:
    return max(2, int(np.ceil(window * fraction)))


def known_on(residual: np.ndarray) -> np.ndarray:
    """(dates x stocks) True from a stock's first residual on: what a live run on t knows of the stock."""
    return np.maximum.accumulate(np.isfinite(residual), axis=0)


def dispersion(raw: np.ndarray, counted: np.ndarray) -> np.ndarray:
    """(dates,) standard deviation of total returns across the stocks counted on each day; NaN below two."""
    return pd.DataFrame(np.where(counted, raw, np.nan)).std(axis=1, ddof=1).to_numpy()


def sector_codes(tables: Tables, sectors: tuple[str, ...]) -> np.ndarray:
    """(dates x stocks) position of each stock's sector on each day in `sectors`; NaN without one."""
    unknown = sorted(set(tables.sectors["sector"].dropna()) - set(sectors))
    if unknown:
        raise ValueError(f"sectors not in [features] sectors: {unknown}")
    code = {s: float(k) for k, s in enumerate(sectors)}
    sector_of = sector_etf_panel(tables.sectors, tables.stocks, tables.dates, {s: s for s in sectors})
    return np.vectorize(lambda s: code.get(s, np.nan), otypes=[np.float64])(sector_of)


def feature_panels(tables: Tables, cfg: Features) -> dict[str, np.ndarray]:
    """Each feature as a (dates x stocks) panel."""
    dates, stocks = tables.dates, tables.stocks
    N = len(stocks)
    residual = tables.residual
    raw = tables.raw
    out: dict[str, np.ndarray] = {}
    for n in cfg.residual_sums:
        out[f"res_sum_{n}"] = residual.rolling(n, min_periods=n).sum().to_numpy()
    for w in cfg.volatility_windows:
        out[f"res_vol_{w}"] = residual.rolling(w, min_periods=_min_periods(w, cfg.volatility_min_fraction)).std().to_numpy()
    out["volume_ratio"] = volume_ratio(tables.prices, tables.returns, stocks, dates, cfg.volume_window_days).to_numpy()
    high = wide(tables.prices, "high", dates, stocks).to_numpy()
    low = wide(tables.prices, "low", dates, stocks).to_numpy()
    close = wide(tables.prices, "close", dates, stocks).to_numpy()
    out["range"] = np.where(close > 0, (high - low) / close, np.nan)
    r = raw.to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        log_index = pd.DataFrame(np.where(r > -1, np.log1p(r), np.nan), index=dates, columns=stocks)
    level = log_index.fillna(0.0).cumsum().where(log_index.notna())
    for w in cfg.extreme_windows:
        mp = _min_periods(w, cfg.volatility_min_fraction)
        top = level.rolling(w, min_periods=mp).max()
        bottom = level.rolling(w, min_periods=mp).min()
        out[f"from_high_{w}"] = np.expm1(level - top).to_numpy()
        out[f"from_low_{w}"] = np.expm1(level - bottom).to_numpy()
    market = wide(tables.returns, "ret", dates, [tables.market]).iloc[:, 0]
    mv = cfg.market_volatility_days
    out["market_vol"] = np.repeat(market.rolling(mv, min_periods=mv).std().to_numpy()[:, None], N, axis=1)
    counted = tables.members & known_on(residual.to_numpy())
    out["dispersion"] = np.repeat(dispersion(r, counted)[:, None], N, axis=1)
    out[SECTOR] = sector_codes(tables, cfg.sectors)
    return out


def build_features(tables: Tables, cfg: Features) -> FeatureSet:
    """Feature rows for every member-day with a residual on t."""
    panels = feature_panels(tables, cfg)
    names = feature_names(cfg)
    rows = tables.members & np.isfinite(tables.residual.to_numpy())
    day, col = np.nonzero(rows)                 # row-major: date order, then stock (ticker) order
    frame = pd.DataFrame({DATE: tables.dates[day], TICKER: np.asarray(tables.stocks, dtype=object)[col]})
    for name in names:
        frame[name] = panels[name][day, col]
    return FeatureSet(frame, names, day, col)


def ranked_target(residual: np.ndarray, members: np.ndarray, horizon: int) -> np.ndarray:
    """(dates x stocks) residual return over t+1..t+H, ranked across members each day to [-0.5, 0.5]."""
    move = np.where(members, forward_sum(residual, horizon), np.nan)
    ranks = pd.DataFrame(move).rank(axis=1, method="average").to_numpy()
    n = np.isfinite(move).sum(axis=1)[:, None]
    with np.errstate(invalid="ignore", divide="ignore"):
        scaled = np.where(n > 1, (ranks - 1.0) / (n - 1.0) - 0.5, 0.0)
    return np.where(np.isfinite(move), scaled, np.nan)
