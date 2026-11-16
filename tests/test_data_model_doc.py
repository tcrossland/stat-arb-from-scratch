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
from statarb.config import repo_root
from statarb.data import build as b
from statarb.data.wikipedia import WikipediaConstituents

DOC = (repo_root() / "docs" / "data-model.md").read_text()
ARROW_NAMES = {"large_string": "string"}


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
    b.write_outputs(out, tmp / "processed", tmp / "reports")
    return {
        p.stem: [(f.name, ARROW_NAMES.get(str(f.type), str(f.type))) for f in pq.read_schema(p)]
        for p in (tmp / "processed").glob("*.parquet")
    }


def test_documented_tables_match_the_written_ones(written) -> None:
    assert _documented() == written


def test_no_em_dashes() -> None:
    assert "—" not in DOC
