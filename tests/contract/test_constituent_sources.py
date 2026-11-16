"""Contract every ConstituentSource adapter must pass (phase 0 brief, "Source interfaces")."""

from __future__ import annotations

import pandas as pd
import pytest

from helpers import constituents_html, fake_wikipedia_api
from statarb.data.schema import GICS_SECTORS
from statarb.data.wikipedia import WikipediaConstituents

ADAPTERS = {"wikipedia": lambda: WikipediaConstituents(api=fake_wikipedia_api(constituents_html()))}
COLUMNS = ["ticker", "security", "sector", "sub_industry", "date_added", "cik"]


@pytest.fixture(params=sorted(ADAPTERS))
def adapter(request):
    return ADAPTERS[request.param]()


def test_snapshot_has_revision_and_raw_bytes(adapter) -> None:
    snap = adapter.fetch(None)
    assert isinstance(snap.revision_id, int) and snap.revision_id > 0
    assert isinstance(snap.raw, bytes) and snap.raw


def test_parse_from_raw_gives_schema(adapter) -> None:
    table = adapter.parse(adapter.fetch(None).raw)
    assert list(table.columns) == COLUMNS
    assert table["ticker"].is_unique
    assert set(table["sector"]) <= GICS_SECTORS
    assert table["date_added"].dtype == "datetime64[ns]"
    assert table["ticker"].is_monotonic_increasing


def test_parse_is_deterministic(adapter) -> None:
    raw = adapter.fetch(None).raw
    pd.testing.assert_frame_equal(adapter.parse(raw), adapter.parse(raw))
