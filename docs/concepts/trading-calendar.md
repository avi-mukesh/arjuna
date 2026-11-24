# Trading calendar

**Code:** `src/arjuna/data/calendar.py` · **Tests:** `tests/unit/test_calendar.py`

## Intuition
A "day" in a trading system means a **session**: a day the exchange was open. Weekends,
holidays (Good Friday, Thanksgiving, Juneteenth, ...) and rare unscheduled closures
(Hurricane Sandy, 29–30 Oct 2012) are not sessions. Every lookback ("63 days"), every
annualisation (√252) and every schedule ("last day of the week") counts sessions, not
calendar days or weekdays.

## The rules Arjuna uses
- **Lookback of L days** = L sessions back: `sessions_back(t, L)`.
- **Next open** = open of `next_session(t)`, the first session strictly after *t*.
- **Weekly rebalance** = the last session of the ISO week. In a Good Friday week, that's Thursday.
- **Monthly rebalance** = the last session of the calendar month.
- **≈252 sessions a year.** That's where √252 in annualised vol comes from (250–253 in practice).

## Assumptions
- The NYSE calendar (`exchange_calendars`, code `XNYS`) applies to every US ETF in the universe.
  An LSE universe would need `XLON`.
- The library's holiday list is correct, and gets updated for new closures, e.g. national
  days of mourning, which are announced at short notice.

## How it breaks
- **Mon–Fri calendars** (`pd.bdate_range`) treat holidays as trading days. Forward-filling
  data onto them creates fake **0% return** days, so vol estimates come out too low and
  positions too big. Weekly schedules then land on days with no data. Nothing crashes;
  the numbers are just quietly wrong.
- **Early closes** (13:00 ET the day after Thanksgiving, Christmas Eve) matter for anything
  scheduled by clock time. `session_close` accounts for them.
- **Timezones.** The open is 09:30 New York time. The US and UK change clocks on different
  dates, so anything scheduled in UK time drifts by an hour for a few weeks a year.

## Reference
- `exchange_calendars` documentation: <https://github.com/gerrymanoim/exchange_calendars>
- NYSE holidays and trading hours: <https://www.nyse.com/markets/hours-calendars>
