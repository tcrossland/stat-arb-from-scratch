"""Trials: every distinct position path run in this repository, for the deflated Sharpe ratio.

A trial is a position path: a configuration less its cost level, since the cost
changes the P&L but not the positions. The count reads every experiment log in
the repository (`reports/phase-NN/experiments.jsonl`), so a configuration tried
in any phase counts against the best result of every later one, and a rerun of
the same configuration is not a new trial. Each path's statistic is the daily
(not annualised) Sharpe ratio of its gross returns, from its latest entry.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from statarb.backtest.engine import TRADING_DAYS
from statarb.backtest.experiments import config_id, read

COST_KEYS = ("cost_bps",)


def path_id(config: dict[str, Any]) -> str:
    """The id of the position path a configuration runs: its config_id without the cost level."""
    return config_id({k: v for k, v in config.items() if k not in COST_KEYS})


def logs(reports: Path) -> list[Path]:
    """Every phase's experiment log under the reports directory, in phase order."""
    return sorted(reports.glob("phase-*/experiments.jsonl"))


def trial_sharpes(entries: Iterable[dict[str, Any]]) -> dict[str, float]:
    """Daily gross Sharpe ratio by path id; a later entry for the same path replaces an earlier one."""
    out: dict[str, float] = {}
    for e in entries:
        value = e["metrics"].get("gross_sharpe")
        if value is not None:
            out[path_id(e["config"])] = value / math.sqrt(TRADING_DAYS)
    return out


def repository_trials(reports: Path) -> dict[str, float]:
    return trial_sharpes(e for path in logs(reports) for e in read(path))
