"""Every signal, by the name config chooses it by.

A new signal is added here and nowhere else in the shared modules; the
look-ahead contract in `tests/contract/test_signals.py` runs over this registry,
so it is checked before it is used.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from statarb.signals.base import Signal
from statarb.signals.reversal import ReversalSignal
from statarb.signals.sscore import SScoreSignal

SIGNALS: dict[str, Callable[..., Signal]] = {
    "residual": lambda **p: ReversalSignal("residual", "residual", **p),
    "raw": lambda **p: ReversalSignal("raw", "raw", **p),
    "sscore": lambda **p: SScoreSignal(**p),
}

# Signals ranked into decile books; the s-score has its own threshold rule.
DECILE_SIGNALS = ("residual", "raw")


def make_signal(name: str, **params: Any) -> Signal:
    if name not in SIGNALS:
        raise KeyError(f"no signal registered as {name!r}; registered: {sorted(SIGNALS)}")
    return SIGNALS[name](**params)
