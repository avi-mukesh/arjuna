"""Helpers for building synthetic bar frames in tests."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from arjuna.data.calendar import TradingCalendar
from arjuna.data.provider import BAR_COLUMNS, as_float_frame

CAL = TradingCalendar()


def make_bars(
    start: dt.date,
    end: dt.date,
    *,
    seed: int = 0,
    start_price: float = 100.0,
    calendar: TradingCalendar = CAL,
) -> pd.DataFrame:
    """Random-walk raw bars on real sessions, with no dividends or splits."""
    idx = calendar.sessions(start, end)
    rng = np.random.default_rng(seed)
    close = start_price * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx))))
    open_ = close * (1 + rng.normal(0, 0.002, len(idx)))
    high = np.maximum(open_, close) * 1.005
    low = np.minimum(open_, close) * 0.995
    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, len(idx)).astype(float),
            "div_cash": 0.0,
            "split_factor": 1.0,
        },
        index=pd.DatetimeIndex(idx, name="date"),
    )
    assert tuple(df.columns) == BAR_COLUMNS
    return as_float_frame(df)


class FakeProvider:
    """In-memory ``DataProvider`` that records the ranges it was asked for."""

    name = "fake"

    def __init__(self, bars: dict[str, pd.DataFrame]) -> None:
        self._bars = bars
        self.calls: list[tuple[str, dt.date, dt.date]] = []

    def daily_bars(self, symbol: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        self.calls.append((symbol, start, end))
        df = self._bars[symbol]
        return df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
