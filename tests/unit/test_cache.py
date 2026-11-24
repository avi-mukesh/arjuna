"""Parquet bar cache with a fake provider."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest
import structlog

from arjuna.data.cache import OVERLAP_SESSIONS, BarCache
from arjuna.data.provider import DataError, validate_bars
from tests.unit.bars_helpers import CAL, FakeProvider, make_bars

D = dt.date
FULL = make_bars(D(2024, 1, 2), D(2024, 12, 31), seed=3)


@pytest.fixture
def cache(tmp_path: Path) -> BarCache:
    return BarCache(tmp_path, "fake", CAL)


def test_first_update_downloads_range_and_roundtrips(cache: BarCache) -> None:
    p = FakeProvider({"SPY": FULL})
    res = cache.update(p, "SPY", D(2024, 1, 1), D(2024, 6, 30))
    assert res.rows_added == len(CAL.sessions(D(2024, 1, 1), D(2024, 6, 30)))
    assert cache.path("SPY").exists()
    loaded = cache.load("SPY")
    pd.testing.assert_frame_equal(loaded, FULL.loc[:"2024-06-30"], check_freq=False)


def test_incremental_update_refetches_overlap_then_appends(cache: BarCache) -> None:
    p = FakeProvider({"SPY": FULL})
    cache.update(p, "SPY", D(2024, 1, 1), D(2024, 6, 30))
    res = cache.update(p, "SPY", D(2024, 1, 1), D(2024, 12, 31))
    # Second call re-fetches the last OVERLAP_SESSIONS cached sessions, then the new ones.
    overlap_start = CAL.sessions_back(D(2024, 6, 28), OVERLAP_SESSIONS - 1)
    assert p.calls[1] == ("SPY", overlap_start, D(2024, 12, 31))
    assert res.rows_added == len(CAL.sessions(D(2024, 7, 1), D(2024, 12, 31)))
    assert res.rows_revised == 0
    assert res.last == D(2024, 12, 31)
    pd.testing.assert_frame_equal(cache.load("SPY"), FULL, check_freq=False)


def test_late_dividend_correction_is_picked_up(cache: BarCache) -> None:
    """A dividend the vendor publishes after we cached the ex-date row replaces the stale row."""
    ex_date = pd.Timestamp("2024-06-27")
    first_version = FULL.loc[:"2024-06-30"].copy()  # div_cash = 0 on the ex-date
    corrected = FULL.copy()
    corrected.loc[ex_date, "div_cash"] = 0.25

    cache.update(FakeProvider({"SPY": first_version}), "SPY", D(2024, 1, 1), D(2024, 6, 30))
    with structlog.testing.capture_logs() as logs:
        res = cache.update(FakeProvider({"SPY": corrected}), "SPY", D(2024, 1, 1), D(2024, 7, 31))
    assert res.rows_revised == 1
    assert cache.load("SPY").loc[ex_date, "div_cash"] == 0.25
    revised = [e for e in logs if e["event"] == "cached_rows_revised"]
    assert revised
    assert revised[0]["dates"] == ["2024-06-27"]


def test_earlier_start_backfills_once(cache: BarCache) -> None:
    p = FakeProvider({"SPY": FULL})
    cache.update(p, "SPY", D(2024, 6, 1), D(2024, 12, 31))
    res = cache.update(p, "SPY", D(2024, 1, 1), D(2024, 12, 31))
    assert p.calls[1] == ("SPY", D(2024, 1, 1), D(2024, 5, 31))
    assert res.first == D(2024, 1, 2)
    pd.testing.assert_frame_equal(cache.load("SPY"), FULL, check_freq=False)
    # Asking again for the same start makes no request.
    cache.update(p, "SPY", D(2024, 1, 1), D(2024, 12, 31))
    assert len(p.calls) == 2


def test_pre_inception_start_is_not_requested_every_run(cache: BarCache) -> None:
    """Symbol listed mid-2024; start=2020 must not trigger a backfill request on each update."""
    listed = FULL.loc["2024-06-03":]
    p = FakeProvider({"UUP": listed})
    cache.update(p, "UUP", D(2020, 1, 1), D(2024, 12, 31))
    cache.update(p, "UUP", D(2020, 1, 1), D(2024, 12, 31))
    assert len(p.calls) == 1


def test_corrupt_file_raises_data_error(cache: BarCache) -> None:
    cache.update(FakeProvider({"SPY": FULL}), "SPY", D(2024, 1, 1), D(2024, 2, 1))
    cache.path("SPY").write_bytes(b"not a parquet file")
    with pytest.raises(DataError, match="unreadable cache file"):
        cache.load("SPY")
    with pytest.raises(DataError, match="unreadable"):
        cache.status("SPY")


def test_wrong_schema_file_raises_data_error(cache: BarCache) -> None:
    cache.path("SPY").parent.mkdir(parents=True)
    pd.DataFrame({"x": [1.0]}).to_parquet(cache.path("SPY"))
    with pytest.raises(DataError, match="unreadable cache file"):
        cache.load("SPY")


def test_refresh_recovers_from_corrupt_file(cache: BarCache) -> None:
    cache.path("SPY").parent.mkdir(parents=True)
    cache.path("SPY").write_bytes(b"junk")
    cache.update(FakeProvider({"SPY": FULL}), "SPY", D(2024, 1, 1), D(2024, 12, 31), refresh=True)
    pd.testing.assert_frame_equal(cache.load("SPY"), FULL, check_freq=False)


def test_up_to_date_cache_makes_no_request(cache: BarCache) -> None:
    p = FakeProvider({"SPY": FULL})
    cache.update(p, "SPY", D(2024, 1, 1), D(2024, 12, 31))
    res = cache.update(p, "SPY", D(2024, 1, 1), D(2024, 12, 31))
    assert len(p.calls) == 1
    assert res.rows_added == 0


def test_refresh_redownloads(cache: BarCache) -> None:
    p = FakeProvider({"SPY": FULL})
    cache.update(p, "SPY", D(2024, 1, 1), D(2024, 12, 31))
    cache.update(p, "SPY", D(2024, 1, 1), D(2024, 12, 31), refresh=True)
    assert p.calls[1] == ("SPY", D(2024, 1, 1), D(2024, 12, 31))


def test_status_reports_gaps(cache: BarCache) -> None:
    holey = FULL.drop(index=[pd.Timestamp("2024-03-05"), pd.Timestamp("2024-03-06")])
    cache.update(FakeProvider({"SPY": holey}), "SPY", D(2024, 1, 1), D(2024, 12, 31))
    st = cache.status("SPY")
    assert st.missing_sessions == (D(2024, 3, 5), D(2024, 3, 6))
    assert st.first == D(2024, 1, 2)


def test_status_of_missing_symbol(cache: BarCache) -> None:
    assert cache.status("QQQ").rows == 0


def test_load_missing_raises(cache: BarCache) -> None:
    with pytest.raises(DataError, match="no cached"):
        cache.load("QQQ")


def test_source_mismatch_rejected(tmp_path: Path) -> None:
    other = BarCache(tmp_path, "tiingo", CAL)
    with pytest.raises(DataError, match="does not match"):
        other.update(FakeProvider({"SPY": FULL}), "SPY", D(2024, 1, 1), D(2024, 2, 1))


def test_no_temp_file_left_behind(cache: BarCache) -> None:
    cache.update(FakeProvider({"SPY": FULL}), "SPY", D(2024, 1, 1), D(2024, 2, 1))
    assert not list(cache.path("SPY").parent.glob("*.tmp"))


# ------------------------------------------------------------------ validation


def test_holiday_row_rejected() -> None:
    bad = FULL.copy()
    bad.loc[pd.Timestamp("2024-03-29")] = bad.iloc[0]  # Good Friday 2024
    bad = bad.sort_index()
    with pytest.raises(DataError, match="non-sessions"):
        validate_bars(bad, CAL, "SPY")


@pytest.mark.parametrize(
    ("column", "value", "match"),
    [
        ("close", -1.0, "non-positive"),
        ("close", float("nan"), "NaN"),
        ("div_cash", -0.1, "negative dividend"),
    ],
)
def test_bad_values_rejected(column: str, value: float, match: str) -> None:
    bad = FULL.copy()
    bad.iloc[5, bad.columns.get_loc(column)] = value
    with pytest.raises(DataError, match=match):
        validate_bars(bad, CAL, "SPY")


def test_duplicate_dates_rejected() -> None:
    bad = pd.concat([FULL.iloc[:3], FULL.iloc[2:3]])
    with pytest.raises(DataError, match="duplicate"):
        validate_bars(bad, CAL, "SPY")


def test_tz_aware_index_rejected() -> None:
    bad = FULL.copy()
    bad.index = bad.index.tz_localize("UTC")
    with pytest.raises(DataError, match="tz-naive"):
        validate_bars(bad, CAL, "SPY")
