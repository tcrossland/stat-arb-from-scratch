"""Look-ahead checks: perturb data after a cut-off and confirm earlier output is unchanged.

Used by every phase that computes values at time t (CLAUDE.md, "Testing").
"""

from __future__ import annotations

from collections.abc import Sequence

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
