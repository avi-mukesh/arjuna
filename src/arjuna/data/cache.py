"""Parquet cache of raw daily bars, one file per (source, symbol).

Layout: ``<root>/<source>/<SYMBOL>.parquet`` plus a small ``<SYMBOL>.meta.json`` sidecar that
records the earliest date ever *requested* for the symbol, so an earlier ``start`` can be
backfilled without re-requesting pre-inception history on every run.

Files hold canonical bar frames (see ``arjuna.data.provider``): raw prices plus dividend and
split events. Those are fixed once correct, but vendors sometimes correct recent rows, e.g. a
dividend published a day after its ex-date. So every incremental update re-fetches the last
``OVERLAP_SESSIONS`` cached sessions, replaces them, and logs a warning if any changed.
Corrections older than that window need ``refresh=True``.

Writes are atomic (write a temp file, then rename), so a crash mid-write can't leave a
truncated file behind.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import structlog

from arjuna.data.calendar import TradingCalendar
from arjuna.data.provider import (
    BAR_COLUMNS,
    DataError,
    DataProvider,
    as_float_frame,
    validate_bars,
)

log = structlog.get_logger(__name__)

OVERLAP_SESSIONS = 10
"""Cached sessions re-fetched on each incremental update to pick up vendor corrections."""


@dataclass(frozen=True)
class UpdateResult:
    symbol: str
    rows_added: int
    first: dt.date | None
    last: dt.date | None
    rows_revised: int = 0


@dataclass(frozen=True)
class CacheStatus:
    symbol: str
    rows: int
    first: dt.date | None
    last: dt.date | None
    missing_sessions: tuple[dt.date, ...]


class BarCache:
    def __init__(self, root: Path, source: str, calendar: TradingCalendar) -> None:
        self.root = root
        self.source = source
        self.calendar = calendar

    def path(self, symbol: str) -> Path:
        return self.root / self.source / f"{symbol}.parquet"

    def meta_path(self, symbol: str) -> Path:
        return self.root / self.source / f"{symbol}.meta.json"

    def exists(self, symbol: str) -> bool:
        return self.path(symbol).exists()

    def load(self, symbol: str) -> pd.DataFrame:
        """Load and validate cached bars. Raises ``DataError`` if missing, unreadable or invalid."""
        p = self.path(symbol)
        if not p.exists():
            raise DataError(f"no cached {self.source} bars for {symbol} at {p}")
        try:
            bars = as_float_frame(pd.read_parquet(p))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # pyarrow's ArrowInvalid/ArrowIOError subclass ValueError/OSError.
            raise DataError(
                f"{symbol}: unreadable cache file {p} ({type(exc).__name__}); "
                "re-download with refresh"
            ) from exc
        validate_bars(bars, self.calendar, symbol)
        return bars

    def update(
        self,
        provider: DataProvider,
        symbol: str,
        start: dt.date,
        end: dt.date,
        *,
        refresh: bool = False,
    ) -> UpdateResult:
        """Bring the cache for ``symbol`` up to date for [start, end].

        * No cache (or ``refresh``): download [start, end] and replace the file.
        * ``start`` earlier than any start requested before: backfill the missing early range.
        * New sessions after the last cached one: download them plus an overlap of
          ``OVERLAP_SESSIONS`` cached sessions, replacing (and reporting) revised rows.
        """
        if provider.name != self.source:
            raise DataError(
                f"provider {provider.name!r} does not match cache source {self.source!r}"
            )

        existing = None if refresh or not self.exists(symbol) else self.load(symbol)
        if existing is None or existing.empty:
            new = self._fetch(provider, symbol, start, end)
            if not new.empty:
                self._write(symbol, new, requested_start=start)
            log.info("cache_updated", symbol=symbol, source=self.source, rows_added=len(new))
            return self._result(symbol, new, added=len(new))

        requested_start = self._requested_start(symbol, existing)
        first_cached = existing.index[0].date()
        last_cached = existing.index[-1].date()
        pieces: list[pd.DataFrame] = []

        # 1. Backfill an earlier start than was ever requested.
        if start < requested_start:
            back_end = min(self.calendar.previous_session(first_cached), end)
            if back_end >= start:
                pieces.append(self._fetch(provider, symbol, start, back_end))
            requested_start = start

        # 2. Append new sessions, re-fetching an overlap to catch vendor corrections.
        if self.calendar.next_session(last_cached) <= end:
            overlap_pos = max(0, len(existing) - OVERLAP_SESSIONS)
            fetch_start = max(existing.index[overlap_pos].date(), start)
            pieces.append(self._fetch(provider, symbol, fetch_start, end))

        if not pieces:
            if requested_start != self._requested_start(symbol, existing):
                self._write_meta(symbol, requested_start)
            return self._result(symbol, existing, added=0)

        fetched = pd.concat(pieces).sort_index()
        fetched = fetched[~fetched.index.duplicated(keep="last")]
        revised = _revised_dates(existing, fetched)
        if revised:
            log.warning(
                "cached_rows_revised",
                symbol=symbol,
                count=len(revised),
                dates=[str(d) for d in revised[:5]],
            )
        added = int((~fetched.index.isin(existing.index)).sum())
        combined = pd.concat([existing[~existing.index.isin(fetched.index)], fetched]).sort_index()

        gaps = validate_bars(combined, self.calendar, symbol)
        if gaps:
            log.warning("missing_sessions", symbol=symbol, count=len(gaps), first=str(gaps[0]))
        self._write(symbol, combined, requested_start=requested_start)
        log.info(
            "cache_updated",
            symbol=symbol,
            source=self.source,
            rows_added=added,
            rows_revised=len(revised),
        )
        return self._result(symbol, combined, added=added, revised=len(revised))

    def status(self, symbol: str) -> CacheStatus:
        if not self.exists(symbol):
            return CacheStatus(symbol, 0, None, None, ())
        bars = self.load(symbol)
        gaps = validate_bars(bars, self.calendar, symbol)
        first, last = _bounds(bars)
        return CacheStatus(symbol, len(bars), first, last, tuple(gaps))

    # ------------------------------------------------------------------ internals

    def _fetch(
        self, provider: DataProvider, symbol: str, start: dt.date, end: dt.date
    ) -> pd.DataFrame:
        bars = provider.daily_bars(symbol, start, end)
        validate_bars(bars, self.calendar, symbol)
        return as_float_frame(bars)

    def _requested_start(self, symbol: str, existing: pd.DataFrame) -> dt.date:
        """Earliest start ever requested; falls back to the first cached date."""
        p = self.meta_path(symbol)
        if p.exists():
            try:
                raw = json.loads(p.read_text())["requested_start"]
                return dt.date.fromisoformat(str(raw))
            except (OSError, ValueError, KeyError, TypeError):
                log.warning("cache_meta_unreadable", symbol=symbol, path=str(p))
        first: dt.date = pd.Timestamp(existing.index[0]).date()
        return first

    def _write(self, symbol: str, bars: pd.DataFrame, *, requested_start: dt.date) -> None:
        p = self.path(symbol)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".parquet.tmp")
        as_float_frame(bars).to_parquet(tmp)
        os.replace(tmp, p)
        self._write_meta(symbol, requested_start)

    def _write_meta(self, symbol: str, requested_start: dt.date) -> None:
        p = self.meta_path(symbol)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"requested_start": requested_start.isoformat()}))
        os.replace(tmp, p)

    @staticmethod
    def _result(symbol: str, bars: pd.DataFrame, *, added: int, revised: int = 0) -> UpdateResult:
        first, last = _bounds(bars)
        return UpdateResult(symbol, added, first, last, revised)


def _bounds(bars: pd.DataFrame) -> tuple[dt.date | None, dt.date | None]:
    if bars.empty:
        return None, None
    return bars.index[0].date(), bars.index[-1].date()


def _revised_dates(existing: pd.DataFrame, fetched: pd.DataFrame) -> list[dt.date]:
    """Dates present in both frames whose values differ beyond float noise."""
    common = existing.index.intersection(fetched.index)
    if common.empty:
        return []
    old = existing.loc[common, list(BAR_COLUMNS)].to_numpy()
    new = fetched.loc[common, list(BAR_COLUMNS)].to_numpy()
    changed = ~np.isclose(old, new, rtol=1e-9, atol=1e-12).all(axis=1)
    return [d.date() for d in common[changed]]
