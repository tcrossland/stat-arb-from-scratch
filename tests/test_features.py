"""Phase 5 features, the ranked target and config/models.toml.

The look-ahead checks come in two kinds. Perturbing values after a cut-off
catches a feature that reads a later value. Removing the rows after it catches
one that depends on whether a later row exists, which perturbation cannot see:
the defective dispersion below, over the whole stock axis, passes the first and
fails the second.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from helpers import MARKET_CAL, MARKET_ETFS, synthetic_market
from statarb.models.config import ModelsConfig, load_models_config
from statarb.models.features import (
    SECTOR,
    build_features,
    dispersion,
    feature_names,
    known_on,
    ranked_target,
)
from statarb.signals.calibration import forward_sum
from statarb.signals.tables import TABLES, build_tables
from statarb.testing.lookahead import (
    assert_unchanged_through,
    perturb_after,
    truncate_after,
)

CFG = load_models_config()
FEATURES = dataclasses.replace(CFG.features, sectors=("Financials", "Information Technology"))
LATE = "S00"                       # a member throughout whose residuals start after the cut-offs below
LATE_FROM = MARKET_CAL[230]


def _long(seed: int = 11) -> dict[str, pd.DataFrame]:
    long = dict(zip(TABLES, synthetic_market(seed=seed), strict=True))
    r = long["residuals"]
    long["residuals"] = r.loc[(r["ticker"] != LATE) | (r["date"] >= LATE_FROM)].reset_index(drop=True)
    return long


def _tables(long: dict[str, pd.DataFrame]):
    return build_tables(*(long[t] for t in TABLES), "SPY", MARKET_ETFS)


def _frame(long: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return build_features(_tables(long), FEATURES).frame


def _perturbed(long: dict[str, pd.DataFrame], cutoff: pd.Timestamp, seed: int) -> dict[str, pd.DataFrame]:
    out = dict(long)
    out["returns"] = perturb_after(long["returns"], cutoff, ["ret"], seed=seed, scale=1.0)
    out["prices"] = perturb_after(long["prices"], cutoff, ["high", "low", "close", "volume"], seed=seed + 1, scale=1.0)
    out["residuals"] = perturb_after(long["residuals"], cutoff, ["residual"], seed=seed + 2, scale=1.0)
    u = long["universe"]
    keep = np.random.default_rng(seed).random(len(u)) < 0.6
    out["universe"] = u.loc[(u["date"] <= cutoff) | keep].reset_index(drop=True)
    return out


def _defective_dispersion(long: dict[str, pd.DataFrame]) -> pd.Series:
    """The obvious definition, over every member on the stock axis: a known defect, kept to test the test."""
    t = _tables(long)
    return pd.Series(dispersion(t.raw.to_numpy(), t.members), index=t.dates)


# --- config ---------------------------------------------------------------------------------------


def test_config_holds_the_brief_dates() -> None:
    p = CFG.period
    assert (p.first_test, p.development_end, p.holdout_start, p.holdout_end) == (
        pd.Timestamp("2020-01-02").date(),
        pd.Timestamp("2025-11-13").date(),
        pd.Timestamp("2025-11-14").date(),
        pd.Timestamp("2026-11-13").date(),
    )


def _raw_config() -> dict:
    from statarb.config import load_config

    return load_config("models")


def test_config_rejects_unknown_and_missing_keys() -> None:
    raw = _raw_config()
    with pytest.raises(ValueError, match="unknown"):
        ModelsConfig.from_dict({**raw, "features": {**raw["features"], "lookback": 3}})
    with pytest.raises(ValueError, match="missing"):
        ModelsConfig.from_dict({**raw, "period": {k: v for k, v in raw["period"].items() if k != "development_end"}})


def test_config_refuses_a_development_end_inside_the_holdout() -> None:
    raw = _raw_config()
    with pytest.raises(ValueError, match="development_end < holdout_start"):
        ModelsConfig.from_dict({**raw, "period": {**raw["period"], "development_end": raw["period"]["holdout_start"]}})


# --- definitions ----------------------------------------------------------------------------------


def test_fifteen_features_one_row_per_member_day_with_a_residual() -> None:
    long = _long()
    fs = build_features(_tables(long), FEATURES)
    assert len(feature_names(CFG.features)) == 15
    assert list(fs.frame.columns) == ["date", "ticker", *fs.names]
    t = _tables(long)
    expected = int((t.members & np.isfinite(t.residual.to_numpy())).sum())
    assert len(fs.frame) == expected
    assert not fs.frame.duplicated(["date", "ticker"]).any()
    assert fs.frame.equals(fs.frame.sort_values(["date", "ticker"], kind="stable"))


def test_feature_values_follow_their_definitions() -> None:
    t = _tables(_long())
    fs = build_features(t, FEATURES)
    f = fs.frame
    res = t.residual.to_numpy()
    j, d = t.stocks.index("S05"), 100
    row = f.loc[(f["date"] == t.dates[d]) & (f["ticker"] == "S05")].iloc[0]
    assert row["res_sum_3"] == pytest.approx(res[d - 2 : d + 1, j].sum())
    assert row["res_vol_20"] == pytest.approx(np.std(res[d - 19 : d + 1, j], ddof=1))
    assert row["range"] == pytest.approx(0.02 / 1.0, rel=1e-12)          # the fixture's high and low are 1% either side of the close
    assert (f["from_high_20"].dropna() <= 0).all() and (f["from_low_60"].dropna() >= 0).all()
    assert f["market_vol"].groupby(f["date"]).nunique().max() == 1
    assert set(f[SECTOR].dropna().unique()) == {0.0, 1.0}                 # positions in [features] sectors
    assert row[SECTOR] == float(FEATURES.sectors.index("Information Technology"))   # odd stocks are IT in the fixture


def test_dispersion_counts_only_members_known_on_the_day() -> None:
    t = _tables(_long())
    fs = build_features(t, FEATURES)
    d = 150                                                               # before the late stock's first residual
    raw = t.raw.to_numpy()[d]
    counted = t.members[d] & known_on(t.residual.to_numpy())[d]
    assert not counted[t.stocks.index(LATE)] and t.members[d, t.stocks.index(LATE)]
    day = fs.frame.loc[fs.frame["date"] == t.dates[d], "dispersion"]
    assert day.iloc[0] == pytest.approx(np.std(raw[counted], ddof=1))


def test_unknown_sector_is_refused() -> None:
    with pytest.raises(ValueError, match="not in"):
        build_features(_tables(_long()), dataclasses.replace(FEATURES, sectors=("Financials",)))


def test_ranked_target_ranks_the_forward_move_across_members() -> None:
    t = _tables(_long())
    res = t.residual.to_numpy()
    for h in (1, 3):
        target = ranked_target(res, t.members, h)
        move = np.where(t.members, forward_sum(res, h), np.nan)
        d = 120
        ok = np.isfinite(move[d])
        assert np.nanmin(target[d]) == -0.5 and np.nanmax(target[d]) == 0.5
        assert (np.argsort(target[d, ok], kind="stable") == np.argsort(move[d, ok], kind="stable")).all()
        assert np.isnan(target[-h:]).all()                                # no outcome yet


# --- look-ahead -----------------------------------------------------------------------------------


@pytest.mark.parametrize("cut", [100, 210])
def test_features_do_not_change_when_later_values_are_perturbed(cut: int) -> None:
    long = _long()
    cutoff = MARKET_CAL[cut]
    before, after = _frame(long), _frame(_perturbed(long, cutoff, seed=cut))
    assert_unchanged_through(before, after, cutoff)
    both = before.merge(after, on=["date", "ticker"], suffixes=("", "_p"))
    later = both.loc[both["date"] > cutoff]
    for name in ("res_sum_1", "range", "volume_ratio", "from_high_20", "dispersion"):
        assert (later[name] != later[f"{name}_p"]).any(), name           # the perturbation reached them


@pytest.mark.parametrize("cut", [100, 210])
def test_features_do_not_change_when_later_rows_are_removed(cut: int) -> None:
    long = _long()
    cutoff = MARKET_CAL[cut]
    assert_unchanged_through(_frame(long), _frame(truncate_after(long, cutoff)), cutoff)


def test_the_row_removal_test_catches_a_dispersion_over_the_whole_stock_axis() -> None:
    long = _long()
    cutoff = MARKET_CAL[150]
    whole = _defective_dispersion(long).loc[:cutoff]
    perturbed = _defective_dispersion(_perturbed(long, cutoff, seed=3)).loc[:cutoff]
    cut = _defective_dispersion(truncate_after(long, cutoff))
    pd.testing.assert_series_equal(whole, perturbed)                     # perturbation cannot see it
    assert not np.allclose(whole.to_numpy(), cut.to_numpy(), equal_nan=True)   # removing later rows can


def test_ranked_target_on_a_day_uses_nothing_after_its_horizon() -> None:
    long = _long()
    h, cut = 3, 150
    cutoff = MARKET_CAL[cut]
    before = ranked_target(_tables(long).residual.to_numpy(), _tables(long).members, h)
    p = _perturbed(long, cutoff, seed=5)
    after = ranked_target(_tables(p).residual.to_numpy(), _tables(p).members, h)
    np.testing.assert_array_equal(before[: cut + 1 - h], after[: cut + 1 - h])
