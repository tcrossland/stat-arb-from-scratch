"""Which trading sessions the daily job processes.

The job never trusts the machine's clock or time zone, or infers a session
from whether data has arrived:

- **Which sessions exist** comes from the market calendar (`exchange_calendars`'
  XNYS: holidays included), so a session the data lacks is a failure to
  retry, not a day to skip.
- **Which are due** follows the data build's snapshot rule: a snapshot taken
  on New York date *D* holds bars before *D* only (`statarb.data.schema.exchange_today`).
  A session is due once New York's date has moved past it, so a run on the
  session's own day, before or after its close, early close or not, does
  nothing for it.
- **Run time:** and not before the configured New York run time on a later
  day (06:00, after the source has settled the close and its corporate
  actions). A run before it treats the previous New York date as today, so the
  scheduler may fire early, late or more than once without changing what a
  run processes.
- **Catch-up:** every due session after the last one in the ledger, in order,
  from the first session of the run.

Sessions are tz-naive `datetime64[ns]` at midnight, as dates are everywhere
else in the project.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd

from statarb.data.schema import EXCHANGE_TZ, exchange_calendar, exchange_today

MIDNIGHT = dt.time(0, 0)


def market_sessions(calendar: str, first: pd.Timestamp, last: pd.Timestamp) -> pd.DatetimeIndex:
    """The calendar's sessions from `first` to `last`, inclusive."""
    sessions = exchange_calendar(calendar).sessions_in_range(pd.Timestamp(first), pd.Timestamp(last))
    return pd.DatetimeIndex(sessions.tz_localize(None) if sessions.tz is not None else sessions).astype("datetime64[ns]")


def run_day(now: dt.datetime, run_time: dt.time = MIDNIGHT) -> dt.date:
    """New York's date at `now`, or the day before if New York's clock has not reached `run_time`."""
    today = exchange_today(now)
    if now.astimezone(ZoneInfo(EXCHANGE_TZ)).time() < run_time:
        return today - dt.timedelta(days=1)
    return today


def early(name: dt.date, taken: dt.datetime, run_time: dt.time = MIDNIGHT) -> bool:
    """Whether a snapshot named for New York date `name` was taken before `run_time` on that date.

    Its last session may then not have settled. The daily job names its
    snapshots for the run day, so it takes none early; one taken by hand can be.
    """
    at = taken.astimezone(ZoneInfo(EXCHANGE_TZ))
    return (at.date(), at.time()) < (name, run_time)


def due(
    sessions: pd.DatetimeIndex, now: dt.datetime, first: pd.Timestamp, last_done: pd.Timestamp | None, run_time: dt.time = MIDNIGHT
) -> pd.DatetimeIndex:
    """Sessions to process now, in order: from `first` (or after `last_done`) to the last one before the run day.

    The run day is New York's date, or the day before until New York's clock
    reaches `run_time`. `now` must be time zone aware; its zone does not matter.
    """
    today = pd.Timestamp(run_day(now, run_time))
    after = pd.Timestamp(first) if last_done is None else pd.Timestamp(last_done) + pd.Timedelta(days=1)
    return sessions[(sessions >= after) & (sessions < today)]


def gaps(sessions: pd.DatetimeIndex, done: list[pd.Timestamp], first: pd.Timestamp) -> list[pd.Timestamp]:
    """Sessions from `first` to the last one done that the ledger does not have."""
    if not done:
        return []
    expected = sessions[(sessions >= pd.Timestamp(first)) & (sessions <= max(done))]
    return sorted(set(expected) - set(done))


def extra(sessions: pd.DatetimeIndex, done: list[pd.Timestamp], first: pd.Timestamp) -> list[pd.Timestamp]:
    """Ledger days that are not sessions of the run: a holiday or weekend, or a day before `first`."""
    valid = set(sessions[sessions >= pd.Timestamp(first)])
    return sorted(d for d in done if d not in valid)
