"""Look-ahead checks: perturb data after a cut-off, or remove the rows after it, and confirm earlier output is unchanged.

Used by every phase that computes values at time t (CLAUDE.md, "Testing").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd


def perturb_after(
    frame: pd.DataFrame,
    cutoff: pd.Timestamp,
    columns: Sequence[str],
    *,
    seed: int = 0,
    scale: float = 0.2,
    date_col: str = "date",
) -> pd.DataFrame:
    """Copy of frame with multiplicative log-normal noise on columns for rows after cutoff.

    Multiplicative noise keeps prices and volumes positive.
    """
    rng = np.random.default_rng(seed)
    out = frame.copy()
    mask = (out[date_col] > pd.Timestamp(cutoff)).to_numpy()
    for col in columns:
        noise = np.exp(scale * rng.standard_normal(int(mask.sum())))
        values = out[col].to_numpy(dtype="float64", copy=True)
        values[mask] = values[mask] * noise
        out[col] = values.astype(out[col].dtype) if out[col].dtype.kind == "f" else values
    return out


def truncate_after(tables: Mapping[str, pd.DataFrame], cutoff: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """The long tables as a live run on `cutoff` would load them: no row dated after it.

    Perturbing values after a cut-off leaves which rows exist alone, so it cannot
    see a value that depends on whether a later row exists. Comparing output from
    these tables with output from the whole tables can. Tables with a `date`
    column keep the rows on or before the cut-off; the sectors table keeps the
    spells that started by then, open-ended, since a later end is not yet known.
    """
    cut = pd.Timestamp(cutoff)
    out = {}
    for name, frame in tables.items():
        if "date" in frame.columns:
            out[name] = frame.loc[frame["date"] <= cut].reset_index(drop=True)
        elif {"valid_from", "valid_to"} <= set(frame.columns):
            kept = frame.loc[frame["valid_from"] <= cut]
            out[name] = kept.assign(valid_to=kept["valid_to"].where(kept["valid_to"] <= cut)).reset_index(drop=True)
        else:
            raise ValueError(f"table {name!r} has neither a date column nor validity dates")
    return out


def assert_unchanged_through(
    before: pd.DataFrame,
    after: pd.DataFrame,
    cutoff: pd.Timestamp,
    *,
    keys: Sequence[str] = ("date", "ticker"),
    date_col: str = "date",
) -> None:
    """Assert both frames agree exactly on all rows dated on or before cutoff."""
    cut = pd.Timestamp(cutoff)
    a = before.loc[before[date_col] <= cut].sort_values(list(keys)).reset_index(drop=True)
    b = after.loc[after[date_col] <= cut].sort_values(list(keys)).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_exact=True)
