"""NYSE trading calendar: holidays, early closes, rebalance days."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from arjuna.data.calendar import CalendarError, TradingCalendar

D = dt.date


@pytest.fixture(scope="module")
def cal() -> TradingCalendar:
    return TradingCalendar()


@pytest.mark.parametrize(
    "holiday",
    [
        D(2025, 1, 1),  # New Year's Day
        D(2025, 4, 18),  # Good Friday (not a federal holiday, but NYSE closes)
        D(2025, 6, 19),  # Juneteenth
        D(2025, 7, 4),  # Independence Day
        D(2025, 11, 27),  # Thanksgiving
        D(2025, 12, 25),  # Christmas
        D(2012, 10, 29),  # Hurricane Sandy (unscheduled closure)
        D(2025, 4, 19),  # Saturday
    ],
)
def test_non_sessions(cal: TradingCalendar, holiday: dt.date) -> None:
    assert not cal.is_session(holiday)


def test_good_friday_week_has_four_sessions(cal: TradingCalendar) -> None:
    week = cal.sessions(D(2025, 4, 14), D(2025, 4, 18))
    assert list(week.date) == [D(2025, 4, 14), D(2025, 4, 15), D(2025, 4, 16), D(2025, 4, 17)]
    # A Mon-Fri calendar would wrongly include Friday.
    assert len(pd.bdate_range("2025-04-14", "2025-04-18")) == 5


def test_sessions_are_tz_naive_midnight(cal: TradingCalendar) -> None:
    idx = cal.sessions(D(2025, 1, 2), D(2025, 1, 10))
    assert idx.tz is None
    assert (idx == idx.normalize()).all()


def test_sessions_empty_when_end_before_start(cal: TradingCalendar) -> None:
    assert len(cal.sessions(D(2025, 1, 10), D(2025, 1, 2))) == 0


def test_next_and_previous_skip_holidays(cal: TradingCalendar) -> None:
    assert cal.next_session(D(2025, 4, 17)) == D(2025, 4, 21)  # Thu -> Mon over Good Friday
    assert cal.previous_session(D(2025, 4, 21)) == D(2025, 4, 17)
    # From a non-session date
    assert cal.next_session(D(2025, 4, 18)) == D(2025, 4, 21)
    assert cal.previous_session(D(2025, 4, 18)) == D(2025, 4, 17)


def test_sessions_back_counts_trading_days(cal: TradingCalendar) -> None:
    assert cal.sessions_back(D(2025, 4, 21), 0) == D(2025, 4, 21)
    assert cal.sessions_back(D(2025, 4, 21), 1) == D(2025, 4, 17)
    start = cal.sessions_back(D(2025, 4, 21), 63)
    assert len(cal.sessions(start, D(2025, 4, 21))) == 64  # 63 steps back, both ends inclusive


def test_sessions_back_requires_session(cal: TradingCalendar) -> None:
    with pytest.raises(CalendarError, match="not a XNYS session"):
        cal.sessions_back(D(2025, 4, 18), 5)


def test_about_252_sessions_per_year(cal: TradingCalendar) -> None:
    for year in range(2010, 2025):
        n = len(cal.sessions(D(year, 1, 1), D(year, 12, 31)))
        assert 250 <= n <= 253, (year, n)


def test_weekly_rebalance_moves_to_thursday_in_good_friday_week(cal: TradingCalendar) -> None:
    assert cal.is_rebalance_day(D(2025, 4, 17), "weekly")
    assert not cal.is_rebalance_day(D(2025, 4, 18), "weekly")
    assert not cal.is_rebalance_day(D(2025, 4, 16), "weekly")
    assert cal.is_rebalance_day(D(2025, 4, 25), "weekly")  # normal Friday


def test_weekly_rebalance_one_per_week(cal: TradingCalendar) -> None:
    days = cal.rebalance_days(D(2024, 1, 1), D(2024, 12, 31), "weekly")
    weeks = {d.isocalendar()[:2] for d in days}
    assert len(days) == len(weeks)
    assert 50 <= len(days) <= 53


def test_monthly_rebalance_last_session_of_month(cal: TradingCalendar) -> None:
    days = cal.rebalance_days(D(2025, 1, 1), D(2025, 12, 31), "monthly")
    assert len(days) == 12
    assert D(2025, 5, 30) in days  # Friday 30 May (31st is Saturday)
    assert D(2025, 10, 31) in days


def test_daily_rebalance_is_every_session(cal: TradingCalendar) -> None:
    start, end = D(2025, 3, 1), D(2025, 3, 31)
    assert len(cal.rebalance_days(start, end, "daily")) == len(cal.sessions(start, end))


def test_non_session_is_never_a_rebalance_day(cal: TradingCalendar) -> None:
    assert not cal.is_rebalance_day(D(2025, 4, 18), "daily")


def test_early_close_day_after_thanksgiving(cal: TradingCalendar) -> None:
    close = cal.session_close(D(2025, 11, 28))
    assert close.tz_convert("America/New_York").time() == dt.time(13, 0)
    normal = cal.session_close(D(2025, 11, 26))
    assert normal.tz_convert("America/New_York").time() == dt.time(16, 0)


def test_open_is_930_new_york_across_dst(cal: TradingCalendar) -> None:
    for d in (D(2025, 1, 15), D(2025, 7, 15)):  # winter and summer time
        assert cal.session_open(d).tz_convert("America/New_York").time() == dt.time(9, 30)


def test_calendar_extends_years_ahead(cal: TradingCalendar) -> None:
    assert cal.last_session > dt.date.today() + dt.timedelta(days=4 * 365)
    # So weekly checks near today never run off the end.
    assert isinstance(cal.is_rebalance_day(cal.next_session(dt.date.today()), "weekly"), bool)


def test_last_session_rebalance_check_raises_clearly() -> None:
    short = TradingCalendar(start=D(2025, 1, 1), end=D(2025, 3, 31))
    with pytest.raises(CalendarError, match="last session"):
        short.is_rebalance_day(short.last_session, "weekly")
    assert short.is_rebalance_day(short.last_session, "daily")


def test_out_of_range_raises(cal: TradingCalendar) -> None:
    with pytest.raises(CalendarError, match="outside"):
        cal.is_session(D(1980, 1, 2))


@given(st.dates(min_value=D(1995, 1, 1), max_value=D(2026, 6, 30)))
def test_next_previous_are_consistent(d: dt.date) -> None:
    c = _CAL
    nxt = c.next_session(d)
    assert nxt > d
    assert c.is_session(nxt)
    assert c.previous_session(nxt) == (d if c.is_session(d) else c.previous_session(d))
    # No session strictly between d and next_session(d)
    assert len(c.sessions(d + dt.timedelta(days=1), nxt - dt.timedelta(days=1))) == 0


_CAL = TradingCalendar()
