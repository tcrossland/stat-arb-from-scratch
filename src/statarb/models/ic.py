"""Information coefficient: the daily rank correlation between a forecast and the realised target."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def daily_rank_ic(day: np.ndarray, forecast: np.ndarray, target: np.ndarray, min_names: int = 10) -> pd.Series:
    """Spearman correlation across names on each date position with at least `min_names` rows having both values."""
    ok = np.isfinite(forecast) & np.isfinite(target)
    d = pd.DataFrame({"day": day[ok], "f": forecast[ok], "y": target[ok]})
    if d.empty:
        return pd.Series(dtype="float64", name="ic")
    g = d.groupby("day", sort=True)
    d["rf"] = g["f"].rank(method="average")
    d["ry"] = g["y"].rank(method="average")
    for c in ("rf", "ry"):
        d[c] = d[c] - d.groupby("day")[c].transform("mean")
    num = (d["rf"] * d["ry"]).groupby(d["day"]).sum()
    den = np.sqrt((d["rf"] ** 2).groupby(d["day"]).sum() * (d["ry"] ** 2).groupby(d["day"]).sum())
    n = d.groupby("day").size()
    ic = (num / den.where(den > 0)).where(n >= min_names)
    return ic.dropna().rename("ic")


def ic_summary(ic: pd.Series) -> dict[str, float]:
    """Mean, standard deviation and t-statistic of a daily IC series.

    The t-statistic treats days as independent. With an H-day target,
    consecutive days share H-1 days of outcome, so for H > 1 it overstates
    significance by roughly sqrt(H).
    """
    n = len(ic)
    sd = float(ic.std()) if n > 1 else float("nan")
    mean = float(ic.mean()) if n else float("nan")
    return {"mean": mean, "sd": sd, "t_stat": mean / sd * math.sqrt(n) if n > 1 and sd > 0 else float("nan"), "days": n}
