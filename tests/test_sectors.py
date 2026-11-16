from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from statarb.config import load_config, repo_root
from statarb.data.sectors import SectorChangeError, build_sector_intervals

START = dt.date(2016, 1, 1)
CURRENT = pd.DataFrame({"ticker": ["V", "GOOGL", "KO"], "sector": ["Financials", "Communication Services", "Consumer Staples"]})


def test_no_changes_gives_one_open_interval_per_ticker() -> None:
    out = build_sector_intervals(CURRENT, [], START)
    assert len(out) == 3 and out["valid_to"].isna().all()
    assert (out["valid_from"] == pd.Timestamp(START)).all()


def test_changes_split_intervals_at_effective_dates() -> None:
    changes = [
        {"ticker": "V", "from": "Information Technology", "to": "Financials", "effective": dt.date(2023, 3, 20)},
        {"ticker": "GOOGL", "from": "Information Technology", "to": "Communication Services", "effective": dt.date(2018, 9, 24)},
    ]
    out = build_sector_intervals(CURRENT, changes, START).set_index(["ticker", "sector"])
    assert out.loc[("V", "Information Technology"), "valid_to"] == pd.Timestamp("2023-03-20")
    assert out.loc[("V", "Financials"), "valid_from"] == pd.Timestamp("2023-03-20")
    assert pd.isna(out.loc[("V", "Financials"), "valid_to"])


@pytest.mark.parametrize(
    "change",
    [
        {"ticker": "V", "from": "Information Technology", "to": "Industrials", "effective": dt.date(2023, 3, 20)},
        {"ticker": "ZZZ", "from": "Energy", "to": "Utilities", "effective": dt.date(2020, 1, 1)},
        {"ticker": "V", "from": "Info Tech", "to": "Financials", "effective": dt.date(2023, 3, 20)},
        {"ticker": "V", "to": "Financials", "effective": dt.date(2023, 3, 20)},
    ],
)
def test_inconsistent_changes_raise(change) -> None:
    with pytest.raises(SectorChangeError):
        build_sector_intervals(CURRENT, [change], START)


def test_changes_must_chain() -> None:
    changes = [
        {"ticker": "V", "from": "Industrials", "to": "Materials", "effective": dt.date(2017, 1, 3)},
        {"ticker": "V", "from": "Information Technology", "to": "Financials", "effective": dt.date(2023, 3, 20)},
    ]
    with pytest.raises(SectorChangeError, match="chain"):
        build_sector_intervals(CURRENT, changes, START)


def test_former_sector_is_allowed_before_a_change() -> None:
    current = pd.DataFrame({"ticker": ["T"], "sector": ["Communication Services"]})
    changes = [{"ticker": "T", "from": "Telecommunication Services", "to": "Communication Services",
                "effective": dt.date(2018, 9, 24)}]
    out = build_sector_intervals(current, changes, START)
    assert out["sector"].tolist() == ["Telecommunication Services", "Communication Services"]


def test_former_sector_cannot_be_current() -> None:
    current = pd.DataFrame({"ticker": ["T"], "sector": ["Telecommunication Services"]})
    with pytest.raises(SectorChangeError):
        build_sector_intervals(current, [], START)


# The three structural GICS changes, whose announcements the config's header cites.
STRUCTURAL_DATES = {dt.date(2016, 9, 19), dt.date(2018, 9, 24), dt.date(2023, 3, 20)}


def test_repository_sector_changes_are_consistent() -> None:
    """Keys, sector names and chaining, with each ticker's current sector taken from its last move.

    A structural change cites its announcement in the file's header; a company-level move cites its own.
    """
    changes = load_config("sector_changes", repo_root())["change"]
    for change in changes:
        assert set(change) - {"source"} == {"ticker", "from", "to", "effective", "note"}, change
        assert isinstance(change["effective"], dt.date)
        if change["effective"] not in STRUCTURAL_DATES:
            assert change.get("source", "").startswith("https://"), change
    last = {}
    for change in sorted(changes, key=lambda c: c["effective"]):
        last[change["ticker"]] = change["to"]
    current = pd.DataFrame({"ticker": list(last), "sector": list(last.values())})
    out = build_sector_intervals(current, changes, START)
    assert len(out) == len(current) + len(changes)
