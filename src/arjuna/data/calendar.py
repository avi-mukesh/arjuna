"""Exchange trading calendar.

All date logic in Arjuna goes through this module. Never use ``pd.bdate_range``: a
Mon-Fri calendar treats holidays (Good Friday, Thanksgiving, ...) as trading days, which
creates fake 0%-return bars, biases vol estimates down and misplaces rebalance days.

Sessions are represented as ``datetime.date`` in the public API and as a tz-naive,
midnight-normalised ``pd.DatetimeIndex`` where a pandas index is needed (bar frames
use the same convention).
"""

from __future__ import annotations

import datetime as dt
from functools import cached_property
from typing import Literal

import exchange_calendars as xcals
import pandas as pd

Frequency = Literal["daily", "weekly", "monthly"]

DEFAULT_START = dt.date(1990, 1, 1)
DEFAULT_YEARS_AHEAD = 5
"""The calendar extends this many years past today, so schedule queries (e.g. "is today the
last session of the week?", which looks at the next session) never hit its end in practice.
Holidays that far ahead come from rules and may miss ad-hoc closures announced later."""


class CalendarError(Exception):
    """A date is outside the calendar's range or is not a session when one is required."""


def _ts(d: dt.date) -> pd.Timestamp:
    return pd.Timestamp(d)


class TradingCalendar:
    """Thin, typed wrapper around an ``exchange_calendars`` calendar (default: NYSE)."""

    def __init__(
        self,
        exchange: str = "XNYS",
        start: dt.date = DEFAULT_START,
        end: dt.date | None = None,
    ) -> None:
        self.exchange = exchange
        if end is None:
            end = dt.date.today() + dt.timedelta(days=366 * DEFAULT_YEARS_AHEAD)
        self._cal = xcals.get_calendar(exchange, start=_ts(start), end=_ts(end))

    @cached_property
    def all_sessions(self) -> pd.DatetimeIndex:
        idx = pd.DatetimeIndex(self._cal.sessions)
        return idx.tz_localize(None) if idx.tz is not None else idx

    @property
    def first_session(self) -> dt.date:
        return self.all_sessions[0].date()

    @property
    def last_session(self) -> dt.date:
        return self.all_sessions[-1].date()

    def _check_range(self, d: dt.date) -> None:
        if not (self.first_session <= d <= self.last_session):
            raise CalendarError(
                f"{d} is outside the {self.exchange} calendar range "
                f"[{self.first_session}, {self.last_session}]"
            )

    # ------------------------------------------------------------------ queries

    def is_session(self, d: dt.date) -> bool:
        # if the date is outside the calendar's range then no point checking if
        # it is a session or not
        self._check_range(d)
        return bool(self._cal.is_session(_ts(d)))

    def sessions(self, start: dt.date, end: dt.date) -> pd.DatetimeIndex:
        """All sessions in [start, end], inclusive."""
        if end < start:
            return pd.DatetimeIndex([])
        idx = self.all_sessions
        return idx[(idx >= _ts(start)) & (idx <= _ts(end))]

    def next_session(self, d: dt.date) -> dt.date:
        """First session strictly after ``d`` (``d`` need not be a session)."""
        idx = self.all_sessions
        pos = int(idx.searchsorted(_ts(d), side="right"))
        if pos >= len(idx):
            raise CalendarError(f"no {self.exchange} session after {d} in calendar range")
        return idx[pos].date()

    def previous_session(self, d: dt.date) -> dt.date:
        """Last session strictly before ``d`` (``d`` need not be a session)."""
        idx = self.all_sessions
        pos = int(idx.searchsorted(_ts(d), side="left")) - 1
        if pos < 0:
            raise CalendarError(f"no {self.exchange} session before {d} in calendar range")
        return idx[pos].date()

    def sessions_back(self, session: dt.date, n: int) -> dt.date:
        """The session ``n`` trading days before ``session`` (``n=0`` returns ``session``)."""
        if n < 0:
            raise ValueError(f"n must be >= 0, got {n}")
        if not self.is_session(session):
            raise CalendarError(f"{session} is not a {self.exchange} session")
        pos = int(self.all_sessions.searchsorted(_ts(session), side="left"))
        if pos - n < 0:
            raise CalendarError(f"{n} sessions before {session} is before the calendar start")
        return self.all_sessions[pos - n].date()

    def is_rebalance_day(self, d: dt.date, frequency: Frequency) -> bool:
        """True if ``d`` is a session and the last session of its week/month.

        Weekly means the last session of the ISO week, so in a Good Friday week it is the
        Thursday. Monthly means the last session of the calendar month.
        """
        # holiday or weekend can't be a rebalance day
        if not self.is_session(d):
            return False
        # if we are rebalancing daily, then everyday is a rebalance day
        if frequency == "daily":
            return True
        if d == self.last_session:
            raise CalendarError(
                f"cannot tell whether {d} ends its period: it is the last session in the "
                f"{self.exchange} calendar; construct TradingCalendar with a later end"
            )
        #
        nxt = self.next_session(d)
        if frequency == "weekly":
            # (year, week)
            # if this isn't the same, that means nxt trading session is a new week
            # so the current session is a rebalance day
            return nxt.isocalendar()[:2] != d.isocalendar()[:2]
        return (nxt.year, nxt.month) != (d.year, d.month)

    def rebalance_days(self, start: dt.date, end: dt.date, frequency: Frequency) -> list[dt.date]:
        return [
            s.date()
            for s in self.sessions(start, end)
            if self.is_rebalance_day(s.date(), frequency)
        ]

    def session_open(self, session: dt.date) -> pd.Timestamp:
        """Market open of ``session`` as a UTC timestamp."""
        if not self.is_session(session):
            raise CalendarError(f"{session} is not a {self.exchange} session")
        return pd.Timestamp(self._cal.session_open(_ts(session)))

    def session_close(self, session: dt.date) -> pd.Timestamp:
        """Market close of ``session`` as a UTC timestamp (accounts for early closes)."""
        if not self.is_session(session):
            raise CalendarError(f"{session} is not a {self.exchange} session")
        return pd.Timestamp(self._cal.session_close(_ts(session)))
