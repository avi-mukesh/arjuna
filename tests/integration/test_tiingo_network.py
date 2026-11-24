"""Real Tiingo API checks. Skipped unless `uv run --env-file .env pytest -m network`."""

from __future__ import annotations

import datetime as dt

import pytest

from arjuna.data.calendar import TradingCalendar
from arjuna.data.provider import validate_bars
from arjuna.data.returns import total_returns
from arjuna.data.tiingo import TiingoProvider

pytestmark = pytest.mark.network


def test_spy_2024_is_complete_and_valid() -> None:
    cal = TradingCalendar()
    bars = TiingoProvider.from_env().daily_bars("SPY", dt.date(2024, 1, 1), dt.date(2024, 12, 31))
    assert validate_bars(bars, cal, "SPY") == []
    assert len(bars) == len(cal.sessions(dt.date(2024, 1, 1), dt.date(2024, 12, 31)))
    assert (bars["div_cash"] > 0).sum() == 4  # SPY pays quarterly
    # SPY's 2024 total return was roughly +25%.
    assert 0.20 < float((1 + total_returns(bars).dropna()).prod() - 1) < 0.30
