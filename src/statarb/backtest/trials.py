"""Trials: every distinct position path run in this repository, for the deflated Sharpe ratio.

A trial is a position path: the part of a configuration that sets positions
(`PATH_KEYS`), since costs, book size and labels change the P&L or the name but
not the positions. A no-trade path's positions also depend on the book size,
but it is one rule tried once, so book sizes are not separate trials; the same
holds for an optimiser setting (phase 4), whose `optimiser` key holds every
setting that moves its positions, and for the residuals a signal is built from
(`residuals`, null for Model A, so earlier entries keep their ids), and for a
phase 5 model forecast the walk-forward that made it (`model`). The count
reads the experiment logs of the repository (`reports/phase-NN/experiments.jsonl`)
up to a given phase, so a configuration tried in any phase counts against the
best result of every later one, a later phase's trials leave an earlier
phase's report unchanged, and a rerun of the same configuration is not a new
trial. Each path's statistic is the daily (not annualised) Sharpe ratio of its
gross returns, from its latest entry. A holdout read (`HOLDOUT_KINDS`, phase 5)
is not a trial, since nothing is chosen from it, and its paths, which repeat
development paths over the held-out year, never replace their statistic.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from statarb.backtest.engine import TRADING_DAYS
from statarb.backtest.experiments import config_id, read

# The configuration keys that set positions. A missing or null key is left out, so
# a phase 2 entry and a phase 3 entry for the same path share an id.
PATH_KEYS = (
    "signal", "source", "lookback_days", "vol_scaled", "holding_days", "fill", "decile", "start", "sscore", "no_trade", "residuals", "optimiser",
    "model",
)


# Log entry kinds (`config.kind`) of the phase 5 holdout read, which `trial_sharpes` skips.
HOLDOUT_KINDS = ("holdout walk-forward", "holdout path")


def path_id(config: dict[str, Any]) -> str:
    """The id of the position path a configuration runs: its config_id over `PATH_KEYS` alone."""
    return config_id({k: config[k] for k in PATH_KEYS if config.get(k) is not None})


def logs(reports: Path, through: str | None = None) -> list[Path]:
    """Each phase's experiment log under the reports directory, in phase order, up to phase `through` (e.g. "phase-02")."""
    found = sorted(reports.glob("phase-*/experiments.jsonl"))
    return [p for p in found if through is None or p.parent.name <= through]


def trial_sharpes(entries: Iterable[dict[str, Any]]) -> dict[str, float]:
    """Daily gross Sharpe ratio by path id; a later entry for the same path replaces an earlier one, and a holdout entry is skipped."""
    out: dict[str, float] = {}
    for e in entries:
        if e["config"].get("kind") in HOLDOUT_KINDS:
            continue
        value = e["metrics"].get("gross_sharpe")
        if value is not None:
            out[path_id(e["config"])] = value / math.sqrt(TRADING_DAYS)
    return out


def repository_trials(reports: Path, through: str | None = None) -> dict[str, float]:
    return trial_sharpes(e for path in logs(reports, through) for e in read(path))
