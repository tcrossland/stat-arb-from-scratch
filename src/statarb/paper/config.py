"""Typed phase 6 configuration from config/paper.toml, with strict keys as for the other phases.

`[frozen]` and `[run] first_session` are empty until the decision record that
starts the forward run sets them; `Frozen.is_set` and `Run.first` say whether
they are.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from statarb.backtest.config import _build
from statarb.backtest.trials import TRAILING
from statarb.config import load_config

SLOPE_RULES = (TRAILING, "floored", "expanding")
DECILE, ZONE, OPTIMISER = "decile sort", "no-trade zone", "optimiser"
OPTIMISER_RULE = re.compile(r"^optimiser κ = (\d+(?:\.\d+)?)$")
MODEL_FORECAST = re.compile(r"^model H=(\d+)$")


def parse_rule(label: str) -> tuple[str, float | None]:
    """A rule label as the logs write it, to the rule and its cost multiplier (None outside the optimiser)."""
    if label in (DECILE, ZONE):
        return label, None
    if m := OPTIMISER_RULE.match(label):
        return OPTIMISER, float(m.group(1))
    raise ValueError(f"the daily job runs the decile sort, the no-trade zone or 'optimiser κ = <multiplier>', not {label!r}")


def model_horizon(forecast: str) -> int | None:
    """The target horizon of a phase 5 model forecast's name, or None for a variant."""
    m = MODEL_FORECAST.match(forecast)
    return int(m.group(1)) if m else None


@dataclass(frozen=True)
class Choice:
    slope_rules: tuple[str, ...]


@dataclass(frozen=True)
class Frozen:
    """The strategy the forward run trades, and the hash of its frozen record (`statarb.paper.frozen`)."""

    forecast: str
    rule: str
    slope_rule: str
    book_size: float
    config_hash: str

    @property
    def is_set(self) -> bool:
        return bool(self.forecast)


@dataclass(frozen=True)
class Run:
    first_session: dt.date | str   # a date, or "" until the forward run's decision record sets it
    calendar: str
    run_time: dt.time              # New York time; see `statarb.paper.sessions.due`

    @property
    def first(self) -> pd.Timestamp | None:
        return pd.Timestamp(self.first_session) if self.first_session != "" else None


@dataclass(frozen=True)
class Backup:
    remote: str                    # git remote of the private ledger backup; empty means not configured


@dataclass(frozen=True)
class PaperConfig:
    choice: Choice
    frozen: Frozen
    run: Run
    backup: Backup

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperConfig:
        cfg = _build(cls, data, "paper")
        cfg.validate()
        return cfg

    def validate(self) -> None:
        rules = self.choice.slope_rules
        if not rules or rules[0] != TRAILING or len(set(rules)) != len(rules) or not set(rules) <= set(SLOPE_RULES):
            raise ValueError(f"choice: slope_rules must start with {TRAILING!r}, without repeats, from {SLOPE_RULES}")
        f = self.frozen
        if f.is_set:
            parse_rule(f.rule)
            if f.slope_rule not in SLOPE_RULES:
                raise ValueError(f"frozen: slope_rule must be one of {SLOPE_RULES}")
            if not f.book_size > 0:
                raise ValueError("frozen: book_size must be positive")
        elif (f.rule, f.slope_rule, f.book_size, f.config_hash) != ("", "", 0, ""):
            raise ValueError("frozen: with no forecast set, every other key must be empty (book_size 0)")
        first = self.run.first_session
        if not (first == "" or (isinstance(first, dt.date) and not isinstance(first, dt.datetime))):
            raise ValueError("run: first_session must be a TOML date such as 2027-01-04, or empty")
        if not isinstance(self.run.run_time, dt.time) or self.run.run_time.tzinfo is not None:
            raise ValueError("run: run_time must be a TOML local time such as 06:00:00, read as New York time")


def load_paper_config(root: Path | None = None) -> PaperConfig:
    return PaperConfig.from_dict(load_config("paper", root))
