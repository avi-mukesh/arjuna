"""Total returns from raw prices plus dividend and split events."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from arjuna.data.returns import max_return_mismatch, total_return_index, total_returns

IDX = pd.DatetimeIndex(pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]), name="date")


def bars(close: list[float], div: list[float], split: list[float]) -> pd.DataFrame:
    c = np.array(close)
    return pd.DataFrame(
        {
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "volume": 1.0,
            "div_cash": div,
            "split_factor": split,
        },
        index=IDX,
    )


def test_no_events_is_price_return() -> None:
    r = total_returns(bars([100, 101, 99.99], [0, 0, 0], [1, 1, 1]))
    assert np.isnan(r.iloc[0])
    assert r.iloc[1] == pytest.approx(0.01)
    assert r.iloc[2] == pytest.approx(-0.01)


def test_ex_dividend_drop_is_not_a_loss() -> None:
    # Price falls by exactly the $1 dividend: total return is 0, price return is -1%.
    r = total_returns(bars([100, 99, 99], [0, 1, 0], [1, 1, 1]))
    assert r.iloc[1] == pytest.approx(0.0)


def test_two_for_one_split_is_not_a_loss() -> None:
    # Raw close halves on the split date; holder now has 2 shares.
    r = total_returns(bars([100, 50.5, 50.5], [0, 0, 0], [1, 2, 1]))
    assert r.iloc[1] == pytest.approx(0.01)


def test_split_and_dividend_same_day() -> None:
    # 2-for-1 split plus a $0.50 post-split dividend: one old share -> 2 * (49.5 + 0.5) = 100.
    r = total_returns(bars([100, 49.5, 49.5], [0, 0.5, 0], [1, 2, 1]))
    assert r.iloc[1] == pytest.approx(0.0)


def test_total_return_index_compounds() -> None:
    idx = total_return_index(bars([100, 110, 121], [0, 0, 0], [1, 1, 1]), base=1.0)
    assert list(idx.round(10)) == [1.0, 1.1, 1.21]


def test_matches_ratio_back_adjusted_close() -> None:
    """Our formula agrees with a CRSP-style ratio back-adjustment of the same events."""
    b = bars([100, 99, 101], [0, 1, 0], [1, 1, 1])
    factor = 1 - 1 / 100  # dividend / previous close
    adj = pd.Series([100 * factor, 99, 101], index=IDX)
    assert max_return_mismatch(b, adj) == pytest.approx(0.0, abs=1e-12)


def test_mismatch_detects_wrong_events() -> None:
    b = bars([100, 99, 101], [0, 0, 0], [1, 1, 1])  # dividend missing from our events
    adj = pd.Series([99, 99, 101], index=IDX)
    assert max_return_mismatch(b, adj) == pytest.approx(0.01, abs=1e-9)


def test_returns_use_only_past_and_present() -> None:
    """r_t depends only on rows t-1 and t: changing later rows leaves it unchanged."""
    from tests.unit.bars_helpers import make_bars

    b = make_bars(dt.date(2024, 1, 2), dt.date(2024, 6, 28), seed=1)
    base = total_returns(b)
    cut = 60
    perturbed = b.copy()
    perturbed.iloc[cut + 1 :, perturbed.columns.get_loc("close")] *= 1.5
    perturbed.iloc[cut + 1 :, perturbed.columns.get_loc("div_cash")] = 0.3
    pd.testing.assert_series_equal(total_returns(perturbed).iloc[: cut + 1], base.iloc[: cut + 1])
