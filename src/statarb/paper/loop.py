"""Phase 6 daily loop: one engine step per trading day, carried through the ledger.

A ledger day d is grid time d on the fill grid. It books the return from grid
time d-1 to d on the holdings carried in, fills the decision made at the close
of d-1 (read from the ledger, not recomputed), and records the decision made at
the close of d for the next day to fill. The step is the backtest's
(`statarb.backtest.engine.step`), with the backtest's policy; only the decision
the policy reads for the fill comes from the ledger.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from statarb.backtest.costs import NoTradeZone
from statarb.backtest.engine import Policy, Step, step
from statarb.paper.ledger import Carry
from statarb.portfolio.optimiser import Optimiser


def with_decision(policy: Policy | None, s: int, expected_move: np.ndarray) -> Policy | None:
    """The policy with the expected move it reads at grid time s set to the one the ledger recorded.

    The decile sort (None) reads no expected move. The no-trade zone checks the
    stored targets against it; the optimiser solves on it, over the stock
    columns, which come first on the grid.
    """
    if policy is None:
        return None
    if isinstance(policy, NoTradeZone):
        panel = policy.expected_move.copy()
        panel[s - policy.delay] = expected_move
        return replace(policy, expected_move=panel)
    if isinstance(policy, Optimiser):
        panel = policy.expected_move.copy()
        panel[s - policy.delay] = expected_move[: policy.n]
        return replace(policy, expected_move=panel)
    raise TypeError(f"the daily job cannot run a {type(policy).__name__} policy")


def live_step(s: int, carry: Carry, returns: np.ndarray, tradable: np.ndarray, rate: np.ndarray, policy: Policy | None) -> Step:
    """Grid time s from the previous ledger day's carry, which must be on the same grid.

    The carried target is the decile rule's decision, which the zone filters;
    the optimiser ignores it and solves on the carried expected move.
    """
    return step(s, carry.holdings, returns, tradable, carry.target, rate, with_decision(policy, s, carry.expected_move))
