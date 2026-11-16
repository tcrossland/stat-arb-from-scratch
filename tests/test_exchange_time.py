"""The trading date comes from New York time, never the machine's time zone."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from statarb.data.schema import exchange_today


@pytest.mark.parametrize(
    ("local", "zone", "expected"),
    [
        # 01:00 in Tokyo on 15 Nov is 11:00 on 14 Nov in New York, mid-session.
        (dt.datetime(2026, 11, 15, 1, 0), "Asia/Tokyo", dt.date(2026, 11, 14)),
        # 23:30 in Madrid on 14 Nov is 17:30 in New York, after the close.
        (dt.datetime(2026, 11, 14, 23, 30), "Europe/Madrid", dt.date(2026, 11, 14)),
        # 00:30 in Madrid on 15 Nov is 18:30 on 14 Nov in New York.
        (dt.datetime(2026, 11, 15, 0, 30), "Europe/Madrid", dt.date(2026, 11, 14)),
        # 20:00 in Los Angeles on 14 Nov is 23:00 in New York, still 14 Nov.
        (dt.datetime(2026, 11, 14, 20, 0), "America/Los_Angeles", dt.date(2026, 11, 14)),
        # 2026-03-10: the US has moved to daylight time, Europe has not yet.
        (dt.datetime(2026, 3, 10, 4, 30), "Europe/London", dt.date(2026, 3, 10)),
        (dt.datetime(2026, 3, 10, 3, 30), "Europe/London", dt.date(2026, 3, 9)),
    ],
)
def test_exchange_today_uses_new_york_date(local, zone, expected) -> None:
    assert exchange_today(local.replace(tzinfo=ZoneInfo(zone))) == expected


def test_naive_time_is_rejected() -> None:
    with pytest.raises(ValueError):
        exchange_today(dt.datetime(2026, 11, 14, 12, 0))
