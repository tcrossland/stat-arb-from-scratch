"""Trading cost models behind one interface, chosen in config.

Phase 2 has a flat cost per dollar traded. Phase 3 adds `TradingCost`: the
half-spread, square-root market impact and a per-order commission, plus the
borrow rates and the no-trade zone that use the same inputs.

Every input to the cost of a fill at grid time s is taken from the trading day
before s (row s-1 of the inputs), so the same estimate could have been used to
decide the trade. The fill price itself, used only to count shares for the
commission, is the price at s.

`book_size` is the capital in US dollars, and the engine's weights are
fractions of it: a decile book has gross exposure equal to the capital, and an
s-score book whatever its open positions add up to. Costs are computed in
dollars and returned per unit of capital. A book that holds fewer names than
its targets, as under the no-trade zone, deploys less capital; it is not
scaled up.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from statarb.backtest.spreads import ESTIMATORS, rolling_spread
from statarb.data.schema import DATE, TICKER


class CostModel(Protocol):
    """Trading cost per day by component, in the engine's weight units.

    `trades` is the (dates x tickers) panel of weights traded and `gross` the
    gross exposure per day that the day's returns are measured on, so a model
    that works in dollars can scale the book to a stated size and back.
    """

    def components(self, trades: np.ndarray, gross: np.ndarray) -> dict[str, np.ndarray]: ...


@dataclass(frozen=True)
class FlatCost:
    """A flat one-way cost per dollar traded, in basis points."""

    bps: float

    def components(self, trades: np.ndarray, gross: np.ndarray) -> dict[str, np.ndarray]:
        return {"flat": self.bps * 1e-4 * np.abs(trades).sum(axis=1)}


# Inputs ----------------------------------------------------------------------------


def _wide(frame: pd.DataFrame, column: str, dates: pd.DatetimeIndex, tickers: list[str]) -> np.ndarray:
    return frame.pivot(index=DATE, columns=TICKER, values=column).reindex(index=dates, columns=tickers).to_numpy(dtype="float64")


def before(panel: np.ndarray) -> np.ndarray:
    """Row s holds the value of row s-1: what was known before grid time s."""
    out = np.full_like(panel, np.nan, dtype="float64")
    out[1:] = panel[:-1]
    return out


def fill_missing_by_row(panel: np.ndarray) -> np.ndarray:
    """Replace NaN with the median of the same row; rows with no values stay NaN."""
    out = panel.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(panel, axis=1)
    rows, cols = np.nonzero(~np.isfinite(out))
    out[rows, cols] = med[rows]
    return out


def split_consistent(prices: np.ndarray, split_ratio: np.ndarray) -> np.ndarray:
    """Unadjusted prices times the cumulative split ratio up to each day.

    A split of r new shares per old share going ex on day d divides prices from
    d on by r; multiplying them back by r makes consecutive days comparable.
    Uses only splits up to each day. Dividends are not adjusted for: an ex-date
    gap of a quarterly dividend is small next to the daily range.
    """
    factor = np.cumprod(np.where(np.isfinite(split_ratio), split_ratio, 1.0), axis=0)
    return prices * factor


def size_groups(dollar_volume: np.ndarray, is_stock: np.ndarray, groups: int) -> np.ndarray:
    """Group per name and day: 0 to groups-1 for stock quantiles of dollar volume (0 smallest), `groups` for ETFs, -1 if none."""
    dv = pd.DataFrame(np.where(is_stock[None, :], dollar_volume, np.nan))
    pct = dv.rank(axis=1, pct=True).to_numpy()
    out = np.where(np.isfinite(pct), np.clip(np.ceil(pct * groups) - 1, 0, groups - 1), -1).astype(np.int64)
    etf = ~is_stock[None, :] & np.isfinite(dollar_volume)
    return np.where(etf, groups, out)


def pooled_spread(signed: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Average each group's signed squared spread across its names each day, floor at zero, take the root.

    Every name gets its group's value; names with no group get NaN. Averaging
    the signed squares rather than the roots keeps the average unbiased when
    single estimates are noisy enough to be negative.
    """
    sq = np.sign(signed) * signed**2
    out = np.full(signed.shape, np.nan)
    for g in np.unique(groups[groups >= 0]):
        in_g = (groups == g) & np.isfinite(sq)
        n = in_g.sum(axis=1)
        mean = np.where(n > 0, np.where(in_g, sq, 0.0).sum(axis=1) / np.maximum(n, 1), np.nan)
        root = np.sqrt(np.maximum(mean, 0.0))
        out = np.where(groups == g, root[:, None], out)
    return out


@dataclass(frozen=True)
class CostInputs:
    """Market data for the cost model on a (dates x tickers) grid; row t uses data up to the close of t."""

    dates: pd.DatetimeIndex
    tickers: tuple[str, ...]
    name_spread: dict[str, np.ndarray]   # signed per-name relative spread by estimator, trailing window
    spread: dict[str, np.ndarray]        # pooled by group, round trip, never negative
    groups: np.ndarray                   # size group per name and day (see size_groups)
    volatility: np.ndarray               # trailing std of daily close-to-close total returns
    dollar_volume: np.ndarray            # trailing mean of close x volume, unadjusted
    open: np.ndarray                     # unadjusted prices on t, for counting shares
    close: np.ndarray


def build_cost_inputs(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    dates: pd.DatetimeIndex,
    tickers: list[str],
    spread_window: int,
    spread_min_observations: int,
    volatility_window: int,
    volatility_min_observations: int,
    volume_window: int,
    volume_min_observations: int,
    is_stock: np.ndarray,
    groups: int,
    estimators: tuple[str, ...] = ESTIMATORS,
) -> CostInputs:
    ohlc = {c: _wide(prices, c, dates, tickers) for c in ("open", "high", "low", "close", "volume")}
    split = _wide(returns, "split_ratio", dates, tickers)
    adj = {c: split_consistent(ohlc[c], split) for c in ("open", "high", "low", "close")}
    name_spread = {
        m: rolling_spread(adj["open"], adj["high"], adj["low"], adj["close"], m, spread_window, spread_min_observations)
        for m in estimators
    }
    ret = pd.DataFrame(_wide(returns, "ret", dates, tickers))
    vol = ret.rolling(volatility_window, min_periods=volatility_min_observations).std().to_numpy()
    dv = pd.DataFrame(ohlc["close"] * ohlc["volume"])
    adv = dv.rolling(volume_window, min_periods=volume_min_observations).mean().to_numpy()
    group = size_groups(adv, is_stock, groups)
    spread = {m: pooled_spread(v, group) for m, v in name_spread.items()}
    return CostInputs(dates, tuple(tickers), name_spread, spread, group, vol, adv, ohlc["open"], ohlc["close"])


# Components --------------------------------------------------------------------------


@dataclass(frozen=True)
class CommissionSchedule:
    """Per-share commission with a minimum and a maximum per order, in US dollars."""

    name: str
    per_share: float
    min_per_order: float
    max_fraction: float              # maximum per order, as a share of the order's value

    def __call__(self, dollars: np.ndarray, price: np.ndarray) -> np.ndarray:
        """Commission in dollars for orders of `dollars` (absolute value) at `price`; zero where nothing trades.

        As in the broker's schedule, the maximum wins when it is below the minimum.
        """
        with np.errstate(divide="ignore", invalid="ignore"):
            shares = np.where(price > 0, dollars / price, np.nan)
        fee = np.fmax(self.per_share * shares, self.min_per_order)
        fee = np.minimum(fee, self.max_fraction * dollars)
        return np.where(dollars > 0, fee, 0.0)


COMPONENTS = ("spread", "impact", "commission")


@dataclass(frozen=True)
class TradingCost:
    """Half-spread, square-root impact and commission for a book of `book_size` dollars of capital.

    Panels are on the engine's grid and already shifted, so row s holds what is
    known before grid time s. `fill_price` is the price at s.
    """

    half_spread: np.ndarray
    volatility: np.ndarray
    dollar_volume: np.ndarray
    fill_price: np.ndarray
    book_size: float
    impact_coefficient: float
    commission: CommissionSchedule

    def unit_cost(self, s: int, dollars: np.ndarray, price: np.ndarray) -> np.ndarray:
        """One-way cost per dollar traded at grid time s, for orders of `dollars` at `price`."""
        with np.errstate(divide="ignore", invalid="ignore"):
            impact = self.impact_coefficient * self.volatility[s] * np.sqrt(dollars / self.dollar_volume[s])
            commission = np.where(dollars > 0, self.commission(dollars, price) / dollars, 0.0)
        return self.half_spread[s] + impact + commission

    def components(self, trades: np.ndarray, gross: np.ndarray) -> dict[str, np.ndarray]:
        """Cost per day by component, per unit of capital. `gross` is not needed: weights are fractions of capital."""
        d = np.abs(trades) * self.book_size
        with np.errstate(divide="ignore", invalid="ignore"):
            impact_rate = self.impact_coefficient * self.volatility * np.sqrt(d / self.dollar_volume)
        dollars = {
            "spread": self.half_spread * d,
            "impact": np.where(d > 0, impact_rate * d, 0.0),
            "commission": self.commission(d, self.fill_price),
        }
        return {k: np.nansum(np.where(d > 0, v, 0.0), axis=1) / self.book_size for k, v in dollars.items()}


HALF_TICK = 0.005   # US dollars: half the one-cent tick of stocks priced above $1


def half_spread(inputs: CostInputs, spread: str | float, half_tick_floor: bool) -> np.ndarray:
    """One-way half-spread per dollar traded, as known before each grid time.

    `spread` names an estimator (half its pooled spread) or gives a fixed
    half-spread in bps. With `half_tick_floor`, the result is at least half a
    cent over the previous close: no stock trades inside its tick.
    """
    if isinstance(spread, str):
        half = fill_missing_by_row(before(inputs.spread[spread] / 2))
    else:
        half = np.full(inputs.close.shape, float(spread) * 1e-4)
    if half_tick_floor:
        with np.errstate(divide="ignore", invalid="ignore"):
            floor = before(np.where(inputs.close > 0, HALF_TICK / inputs.close, np.nan))
        half = np.fmax(half, floor)
    return half


def trading_cost(
    inputs: CostInputs,
    grid_kind: str,
    spread: str | float,
    half_tick_floor: bool,
    book_size: float,
    impact_coefficient: float,
    commission: CommissionSchedule,
) -> TradingCost:
    """The cost model for a fill grid: inputs from the day before each grid time, missing values filled by the day's median.

    `spread` names an estimator, or gives a fixed one-way half-spread in bps.
    """
    fill_price = inputs.open if grid_kind == "open" else inputs.close
    return TradingCost(
        half_spread=half_spread(inputs, spread, half_tick_floor),
        volatility=fill_missing_by_row(before(inputs.volatility)),
        dollar_volume=fill_missing_by_row(before(inputs.dollar_volume)),
        fill_price=fill_price,
        book_size=book_size,
        impact_coefficient=impact_coefficient,
        commission=commission,
    )


def borrow_rates(
    volatility_before: np.ndarray, is_stock: np.ndarray, general_annual: float, hard_annual: float, hard_quantile: float
) -> tuple[np.ndarray, np.ndarray]:
    """Annual borrow rate per name and grid time, and the hard-to-borrow flag.

    A stock is hard to borrow at s when its trailing volatility, as known before
    s, is in the top `hard_quantile` of stocks with a value that day. ETFs are
    never hard to borrow. This is a proxy: free data says nothing about
    borrow availability.
    """
    vol = np.where(is_stock[None, :], volatility_before, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        cut = np.nanquantile(vol, 1 - hard_quantile, axis=1)
    hard = np.isfinite(vol) & (vol >= cut[:, None])
    return np.where(hard, hard_annual, general_annual), hard


# No-trade zone ----------------------------------------------------------------------


@dataclass(frozen=True)
class NoTradeZone:
    """Engine policy (`engine.Policy`): trade a name only when the expected move pays for the trade.

    `expected_move` is on decision dates (row t, known at the close of t), in
    return units over the holding period; the engine fills decisions of t at
    grid time t + delay. Opening a position needs an expected move in its
    direction above the round-trip cost; resizing an existing one needs it above
    the one-way cost of that trade; exits and changes of side always trade.
    Costs are estimated with the previous close as the price, since the fill
    price is not known when the order is sent.
    """

    expected_move: np.ndarray
    cost: TradingCost
    decision_price: np.ndarray     # grid-aligned: row s holds the close before s
    delay: int

    def __call__(self, s: int, held: np.ndarray, drifted: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, None]:
        decided = s - self.delay
        if decided < 0:
            return target, None
        mu = np.nan_to_num(self.expected_move[decided])
        want = np.isfinite(target)
        tgt = np.where(want, target, drifted)
        delta = tgt - drifted
        dollars = np.abs(delta) * self.cost.book_size
        unit = np.nan_to_num(self.cost.unit_cost(s, dollars, self.decision_price[s]), nan=np.inf)
        opening = (drifted == 0) & (tgt != 0)
        exiting = (tgt == 0) | (np.sign(tgt) * np.sign(drifted) < 0)
        resizing = ~opening & ~exiting & (delta != 0)
        skip = (opening & (mu * np.sign(tgt) < 2 * unit)) | (resizing & (mu * np.sign(delta) < unit))
        return np.where(want & skip, np.nan, target), None
