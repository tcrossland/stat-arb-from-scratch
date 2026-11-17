"""docs/data-model.md gives every table the build writes, with its columns and types in order."""

from __future__ import annotations

import datetime as dt
import re

import pandas as pd
import pyarrow.parquet as pq
import pytest

from helpers import (
    SplitAdjustedSource,
    constituents_html,
    fake_wikipedia_api,
    synthetic_truth,
)
from statarb.config import load_config, repo_root
from statarb.data import build as b
from statarb.data.wikipedia import WikipediaConstituents
from statarb.factors.build import build_pca_residuals, build_residuals, stocks_to_model
from statarb.io import read_parquet, write_parquet

DOC = (repo_root() / "docs" / "data-model.md").read_text()
ARROW_NAMES = {"large_string": "string"}
NUMBERED = re.compile(r"_\d+$")          # beta_1, beta_2, ... documented once as beta_k


def _documented() -> dict[str, list[tuple[str, str]]]:
    tables = {}
    for block in re.split(r"^## ", DOC, flags=re.MULTILINE)[1:]:
        title, body = block.split("\n", 1)
        rows = re.findall(r"^\| `(\w+)` \| ([\w\[\]]+) \|", body, flags=re.MULTILINE)
        if rows:
            tables[title.strip()] = rows
    return tables


@pytest.fixture(scope="module")
def written(tmp_path_factory) -> dict[str, list[tuple[str, str]]]:
    tmp = tmp_path_factory.mktemp("build")
    days = pd.bdate_range("2021-01-04", "2021-04-30")
    truths = {t: synthetic_truth(days, seed=i) for i, t in enumerate(["SPY", "AAA", "BRK.B", "CCC", "DDD", "EEE"])}
    constituents = WikipediaConstituents(api=fake_wikipedia_api(constituents_html(), revid=1))
    b.download_constituents(constituents, tmp / "raw", 1, dt.date(2021, 5, 3))
    b.download_prices(SplitAdjustedSource(truths), tmp / "raw", list(truths), dt.date(2021, 1, 4), dt.date(2021, 5, 3), 0.0, 0)
    cfg = {
        "dates": {"start": dt.date(2021, 1, 4)},
        "source": {"name": "synthetic", "snapshot": ""},
        "universe": {"size": 3, "liquidity_window_days": 20, "liquidity_min_observations": 18, "rebalance": "monthly"},
        "factors": {"market": "SPY", "sectors": []},
        "quality": {"max_abs_daily_return": 0.25, "min_live_coverage": 0.95},
    }
    out = b.build(tmp / "raw", cfg, {"revision_id": 1}, [], constituents, "synthetic")
    processed = tmp / "processed"
    b.write_outputs(out, processed, tmp / "reports")
    # Phase 1's residuals from those tables, with a window short enough for the fixture to have rows.
    factors = load_config("factors")
    factors = {**factors, "model": {**factors["model"], "window_days": 40, "min_observations": 30}}
    returns = read_parquet(processed / "returns.parquet")
    stocks = stocks_to_model(read_parquet(processed / "candidates.parquet"), returns)
    residuals = build_residuals(
        returns, read_parquet(processed / "sectors.parquet"), read_parquet(processed / "prices.parquet"), stocks, factors, "SPY"
    )
    assert not residuals.empty
    write_parquet(residuals, processed / "residuals.parquet", ["date", "ticker"])
    # Phase 4's Model B, with as few factors as the fixture's handful of stocks allows.
    factors = {**factors, "pca": {"factors": 2, "window_days": 40, "min_observations": 30}}
    pca = build_pca_residuals(returns, stocks, factors, "SPY")
    assert not pca.empty
    write_parquet(pca, processed / "residuals_pca.parquet", ["date", "ticker"])
    return {p.stem: _columns(p) for p in (tmp / "processed").glob("*.parquet")}


def _columns(path) -> list[tuple[str, str]]:
    """Each column's name and type, with numbered columns (one per factor) collapsed to `name_k`."""
    out = []
    for f in pq.read_schema(path):
        col = (NUMBERED.sub("_k", f.name), ARROW_NAMES.get(str(f.type), str(f.type)))
        if not out or out[-1] != col:
            out.append(col)
    return out


def test_documented_tables_match_the_written_ones(written) -> None:
    assert _documented() == written


def test_no_em_dashes() -> None:
    assert "—" not in DOC
