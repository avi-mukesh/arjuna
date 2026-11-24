"""The ``DataProvider`` interface and the canonical daily-bar frame.

A bar frame has a tz-naive, midnight-normalised ``DatetimeIndex`` named ``date`` (one row
per exchange session) and the columns in ``BAR_COLUMNS``:

* ``open``, ``high``, ``low``, ``close``: **raw** traded prices, never vendor-adjusted.
* ``volume``: raw share volume.
* ``div_cash``: cash dividend per share with ex-date on this session (0 otherwise).
* ``split_factor``: split ratio taking effect on this session (1 otherwise; 2.0 = 2-for-1).

Raw prices plus events never change after the fact, so a cache of them can't go stale.
Total returns are derived from them in ``arjuna.data.returns``.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol

import numpy as np
import pandas as pd

from arjuna.data.calendar import TradingCalendar

BAR_COLUMNS: tuple[str, ...] = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "div_cash",
    "split_factor",
)

# tuple[str, ...] is a type hint indicating any number of str
# whereas e.g. tuple[str, float] would mean a str and a float e.g. ('A', 2.7)
PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close")


class DataError(Exception):
    """Bad, missing or unobtainable market data."""


# Protocol is how DataProvider acts as an interface - stubs methods for e.g. TiingoProvider
# to implement
class DataProvider(Protocol):
    """Source of raw daily bars. Implementations do I/O; strategies never call them."""

    @property
    def name(self) -> str:
        """Short source name, used as the cache sub-directory (e.g. ``tiingo``)."""
        ...

    def daily_bars(self, symbol: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        """Raw daily bars for sessions in [start, end], as a canonical bar frame."""
        ...


def empty_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {c: pd.Series(dtype="float64") for c in BAR_COLUMNS},
        index=pd.DatetimeIndex([], name="date"),
    )


def validate_bars(bars: pd.DataFrame, calendar: TradingCalendar, symbol: str) -> list[dt.date]:
    """Raise ``DataError`` on structural problems; return sessions missing inside the range.

    Missing sessions (gaps) are returned rather than raised: the caller decides whether a
    gap is acceptable. Rows on non-sessions, duplicates, non-positive prices and NaNs are
    always errors.
    """
    missing_cols = [c for c in BAR_COLUMNS if c not in bars.columns]
    if missing_cols:
        raise DataError(f"{symbol}: missing columns {missing_cols}")
    if bars.empty:
        return []

    idx = bars.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise DataError(f"{symbol}: index must be a DatetimeIndex")
    if idx.tz is not None or not (idx == idx.normalize()).all():  # normalise times to all midnight
        raise DataError(f"{symbol}: index must be tz-naive session dates at midnight")
    if idx.has_duplicates:
        raise DataError(f"{symbol}: duplicate dates")
    if not idx.is_monotonic_increasing:
        raise DataError(f"{symbol}: dates not sorted")

    values = bars[list(BAR_COLUMNS)]
    # get the df of booleans where True means value is missing
    # .isna().any() gives one bool per column, where True means column has any NaN
    # .isna().any().any() gives one bool, where True means
    if values.isna().any().any():
        # mask for which columns have NaN, and report them
        bad = values.columns[values.isna().any()].tolist()
        raise DataError(f"{symbol}: NaNs in {bad}")
    if (bars[list(PRICE_COLUMNS)] <= 0).any().any():
        raise DataError(f"{symbol}: non-positive prices")
    if (bars["high"] < bars["low"]).any():
        raise DataError(f"{symbol}: high < low on some rows")
    if (bars["div_cash"] < 0).any() or (bars["split_factor"] <= 0).any():
        raise DataError(f"{symbol}: negative dividend or non-positive split factor")

    first, last = idx[0].date(), idx[-1].date()
    expected = calendar.sessions(first, last)
    extra = idx.difference(expected)
    if len(extra) > 0:
        # we have bars on e.g. Christmas Day, Good Friday, weekend, which shouldn't be there
        raise DataError(f"{symbol}: rows on non-sessions: {[d.date() for d in extra[:5]]}")
    # any missing trading days might be a real gap at the vendor, so return these rather
    # than erroring
    gaps = expected.difference(idx)
    return [d.date() for d in gaps]


def as_float_frame(bars: pd.DataFrame) -> pd.DataFrame:
    """Canonical column order and float64 dtype."""
    out = bars[list(BAR_COLUMNS)].astype(np.float64)
    out.index.name = "date"
    return out
