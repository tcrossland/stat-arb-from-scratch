"""Which sessions the daily job processes: the New York date decides, whatever the machine's clock says."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from statarb.data import schema
from statarb.paper import sessions
from statarb.paper.config import load_paper_config

NY, LONDON, TOKYO = ZoneInfo("America/New_York"), ZoneInfo("Europe/London"), ZoneInfo("Asia/Tokyo")
FIRST = pd.Timestamp("2026-11-16")
# A fixed calendar: weekdays with Thanksgiving (2026-11-26) closed, as XNYS has it.
CAL = pd.bdate_range("2026-11-16", "2026-12-04").drop(pd.Timestamp("2026-11-26"))
SIX = dt.time(6, 0)


def _at(zone, *args) -> dt.datetime:
    return dt.datetime(*args, tzinfo=zone)


def _days(*days: str) -> list[pd.Timestamp]:
    return [pd.Timestamp(d) for d in days]


def test_nothing_is_due_on_the_first_day_before_or_after_the_close() -> None:
    for now in (
        _at(NY, 2026, 11, 16, 15, 0),        # before the close
        _at(NY, 2026, 11, 16, 17, 0),        # after it: a snapshot taken today holds no bar for today
        _at(LONDON, 2026, 11, 16, 20, 0),    # 15:00 in New York
        _at(TOKYO, 2026, 11, 17, 8, 0),      # already the 17th in Tokyo, 18:00 on the 16th in New York
    ):
        assert list(sessions.due(CAL, now, FIRST, None)) == []


def test_the_first_session_is_due_the_next_new_york_morning_from_any_zone() -> None:
    for now in (_at(NY, 2026, 11, 17, 6, 0), _at(LONDON, 2026, 11, 17, 11, 0), _at(TOKYO, 2026, 11, 17, 20, 0)):
        assert list(sessions.due(CAL, now, FIRST, None)) == _days("2026-11-16")


def test_missed_days_are_caught_up_in_order_and_holidays_skipped() -> None:
    assert list(sessions.due(CAL, _at(NY, 2026, 11, 23, 6, 0), FIRST, pd.Timestamp("2026-11-17"))) == _days(
        "2026-11-18", "2026-11-19", "2026-11-20"
    )
    assert list(sessions.due(CAL, _at(NY, 2026, 11, 27, 6, 0), FIRST, pd.Timestamp("2026-11-25"))) == []
    assert list(sessions.due(CAL, _at(NY, 2026, 11, 30, 6, 0), FIRST, pd.Timestamp("2026-11-25"))) == _days("2026-11-27")


def test_a_second_run_finds_nothing_due() -> None:
    now = _at(NY, 2026, 11, 20, 6, 0)
    done = sessions.due(CAL, now, FIRST, None)
    assert list(sessions.due(CAL, now, FIRST, done[-1])) == []


def test_a_naive_clock_is_refused() -> None:
    with pytest.raises(ValueError, match="time zone aware"):
        sessions.due(CAL, dt.datetime(2026, 11, 20, 6, 0), FIRST, None)


@pytest.mark.parametrize(
    ("now", "last_due"),
    [
        # Autumn 2026: London leaves summer time on 25 October and New York on 1 November, so for a
        # week New York is 4 hours behind London rather than 5.
        (_at(LONDON, 2026, 10, 28, 23, 30), "2026-10-27"),   # 19:30 on the 28th in New York
        (_at(LONDON, 2026, 10, 29, 4, 30), "2026-10-28"),    # 00:30 on the 29th in New York
        # Spring 2027: New York starts summer time on 14 March and London on 28 March.
        (_at(LONDON, 2027, 3, 16, 3, 30), "2027-03-12"),     # 23:30 on the 15th in New York
        (_at(LONDON, 2027, 3, 16, 4, 30), "2027-03-15"),     # 00:30 on the 16th in New York
    ],
)
def test_the_weeks_when_us_and_european_clock_changes_differ(now, last_due) -> None:
    cal = pd.bdate_range("2026-10-19", "2027-03-31")
    assert sessions.due(cal, now, pd.Timestamp("2026-10-19"), None)[-1] == pd.Timestamp(last_due)


def test_before_the_run_time_the_previous_new_york_day_counts_as_today() -> None:
    assert list(sessions.due(CAL, _at(NY, 2026, 11, 17, 5, 59), FIRST, None, SIX)) == []
    assert list(sessions.due(CAL, _at(NY, 2026, 11, 17, 6, 0), FIRST, None, SIX)) == _days("2026-11-16")
    assert list(sessions.due(CAL, _at(LONDON, 2026, 11, 17, 10, 59), FIRST, None, SIX)) == []    # 05:59 in New York
    assert list(sessions.due(CAL, _at(TOKYO, 2026, 11, 17, 20, 0), FIRST, None, SIX)) == _days("2026-11-16")
    assert sessions.run_day(_at(NY, 2026, 11, 17, 5, 59), SIX) == dt.date(2026, 11, 16)
    assert sessions.run_day(_at(NY, 2026, 11, 17, 5, 59)) == dt.date(2026, 11, 17)          # no run time: midnight


def test_the_run_time_follows_new_york_summer_time() -> None:
    """06:00 in New York is 10:00 UTC in summer time and 11:00 in winter; the gate moves with it."""
    cal = pd.bdate_range("2026-10-26", "2026-11-06")
    first = pd.Timestamp("2026-10-26")
    assert list(sessions.due(cal, _at(dt.UTC, 2026, 10, 27, 10, 0), first, None, SIX)) == _days("2026-10-26")
    assert list(sessions.due(cal, _at(dt.UTC, 2026, 11, 3, 10, 30), first, pd.Timestamp("2026-10-30"), SIX)) == []
    assert list(sessions.due(cal, _at(dt.UTC, 2026, 11, 3, 11, 0), first, pd.Timestamp("2026-10-30"), SIX)) == _days("2026-11-02")


def test_a_scheduler_firing_every_hour_processes_each_session_once() -> None:
    last, processed = None, []
    for hour in pd.date_range("2026-11-16 00:00", "2026-12-01 00:00", freq="h", tz=NY):
        due = sessions.due(CAL, hour.to_pydatetime(), FIRST, last, SIX)
        processed += list(due)
        last = due[-1] if len(due) else last
        assert all(d.date() < hour.date() and hour.time() >= SIX for d in due)
    assert processed == list(CAL[CAL < pd.Timestamp("2026-11-30")])     # the 30th is due at 06:00 on 1 December


def test_gaps_and_extra_days_in_the_ledger() -> None:
    done = _days("2026-11-16", "2026-11-17", "2026-11-19", "2026-11-26")
    assert sessions.gaps(CAL, done, FIRST) == _days("2026-11-18", "2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25")
    assert sessions.extra(CAL, done, FIRST) == _days("2026-11-26")
    assert sessions.gaps(CAL, [], FIRST) == []


def test_xnys_sessions_come_from_the_calendars_rules() -> None:
    """exchange_calendars computes sessions from its rules: no network."""
    got = sessions.market_sessions("XNYS", FIRST, pd.Timestamp("2027-01-31"))
    assert got.dtype == "datetime64[ns]" and got.tz is None
    closed = pd.bdate_range(FIRST, "2027-01-31").difference(got)
    assert list(closed) == _days("2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18")
    assert len(got) == 51


def test_the_run_section_is_set_by_the_forward_runs_decision() -> None:
    cfg = load_paper_config()
    assert cfg.run.first == pd.Timestamp("2026-11-16")   # decision record 0007
    assert cfg.frozen.is_set
    assert cfg.run.calendar == "XNYS" and cfg.run.run_time == SIX


def test_only_the_calendar_build_is_spared_pandas_4s_warning() -> None:
    """The filter around `get_calendar` must not hide the same deprecation in our own code."""
    sessions.market_sessions("XNYS", pd.Timestamp("2026-11-16"), pd.Timestamp("2026-11-20"))
    aware = pd.Series(pd.date_range("2026-11-16", periods=2, tz="America/New_York"))
    with pytest.warns(pd.errors.Pandas4Warning, match=schema.CALENDAR_VALUES):
        _ = aware.values
