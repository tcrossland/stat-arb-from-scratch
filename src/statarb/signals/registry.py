"""Every signal, by the name config chooses it by.

A new signal is added here and nowhere else in the shared modules; the
look-ahead contract in `tests/contract/test_signals.py` runs over this registry,
so it is checked before it is used.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from statarb.signals.base import Signal
from statarb.signals.momentum import MomentumSignal
from statarb.signals.reversal import ReversalSignal
from statarb.signals.sscore import SScoreSignal


def _model_forecast(**params: Any) -> Signal:
    # Imported when first built: statarb.models reads its config through statarb.backtest.config,
    # which imports this registry.
    from statarb.models.forecast import ForecastSignal

    return ForecastSignal(**params)


SIGNALS: dict[str, Callable[..., Signal]] = {
    "residual": lambda **p: ReversalSignal("residual", "residual", **p),
    "raw": lambda **p: ReversalSignal("raw", "raw", **p),
    "sscore": lambda **p: SScoreSignal(**p),
    "model": _model_forecast,     # the phase 5 walk-forward forecast, from config/models.toml
    "momentum": lambda **p: MomentumSignal("momentum", "raw", **p),                     # phase 8
    "residual_momentum": lambda **p: MomentumSignal("residual_momentum", "residual", **p),
}

# Signals ranked into decile books; the s-score has its own threshold rule.
DECILE_SIGNALS = ("residual", "raw")


def make_signal(name: str, **params: Any) -> Signal:
    if name not in SIGNALS:
        raise KeyError(f"no signal registered as {name!r}; registered: {sorted(SIGNALS)}")
    return SIGNALS[name](**params)
