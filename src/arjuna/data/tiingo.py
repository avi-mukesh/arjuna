"""Tiingo end-of-day data provider (ADR 0004).

One request per symbol returns raw OHLCV plus ``divCash`` and ``splitFactor``. Tiingo also
returns adjusted prices. They are used only as a download-time check of our total-return
formula and are never cached.

The API key comes from ``TIINGO_API_KEY``. It is sent only in the ``Authorization`` header
and never appears in logs, errors or ``repr``.
"""

from __future__ import annotations

import datetime as dt
import os
from types import TracebackType
from typing import Any, Self

import httpx
import pandas as pd
import structlog

from arjuna.data.provider import DataError, as_float_frame, empty_bars
from arjuna.data.returns import max_return_mismatch

BASE_URL = "https://api.tiingo.com"
API_KEY_ENV = "TIINGO_API_KEY"
MISMATCH_WARN = 1e-3
"""Warn if our total return and Tiingo's adjusted return differ by more than 0.1% on any day."""

_RENAME = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "divCash": "div_cash",
    "splitFactor": "split_factor",
}

log = structlog.get_logger(__name__)


class TiingoProvider:
    """``DataProvider`` backed by Tiingo's daily prices endpoint."""

    name = "tiingo"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        if not api_key:
            raise DataError(f"empty Tiingo API key; set {API_KEY_ENV}")
        self._api_key = api_key
        self._owns_client = client is None
        self._client = (
            client if client is not None else httpx.Client(base_url=BASE_URL, timeout=30.0)
        )

    @classmethod
    def from_env(cls) -> TiingoProvider:
        key = os.environ.get(API_KEY_ENV, "")
        if not key:
            raise DataError(
                f"{API_KEY_ENV} is not set. Put it in .env and run with "
                "`uv run --env-file .env ...`."
            )
        return cls(key)

    def __repr__(self) -> str:
        return "TiingoProvider(api_key=<redacted>)"

    def close(self) -> None:
        """Close the HTTP client if this provider created it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def daily_bars(self, symbol: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        if end < start:
            return empty_bars()
        try:
            resp = self._client.get(
                f"/tiingo/daily/{tiingo_ticker(symbol)}/prices",
                params={
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                    "resampleFreq": "daily",
                    "format": "json",
                },
                headers={"Authorization": f"Token {self._api_key}"},
            )
        except httpx.HTTPError as exc:
            raise DataError(f"Tiingo request for {symbol} failed: {type(exc).__name__}") from None
        _raise_for_status(resp, symbol)

        rows: Any = resp.json()
        if not isinstance(rows, list):
            raise DataError(f"unexpected Tiingo response for {symbol}: expected a JSON list")
        if not rows:
            return empty_bars()
        return _parse(rows, symbol)


def tiingo_ticker(symbol: str) -> str:
    """Tiingo writes share classes with a hyphen (``BRK.B`` -> ``brk-b``)."""
    return symbol.lower().replace(".", "-")


def _raise_for_status(resp: httpx.Response, symbol: str) -> None:
    code = resp.status_code
    if code == 200:
        return
    if code in (401, 403):
        raise DataError(f"Tiingo rejected the API key (HTTP {code}); check {API_KEY_ENV}")
    if code == 404:
        raise DataError(f"Tiingo does not know symbol {symbol!r} (HTTP 404)")
    if code == 429:
        raise DataError("Tiingo rate limit hit (HTTP 429); wait and retry later")
    raise DataError(f"Tiingo returned HTTP {code} for {symbol}")


def _parse(rows: list[dict[str, Any]], symbol: str) -> pd.DataFrame:
    raw = pd.DataFrame(rows)
    missing = [c for c in [*_RENAME, "date", "adjClose"] if c not in raw.columns]
    if missing:
        raise DataError(f"Tiingo response for {symbol} lacks fields {missing}")

    # Tiingo dates are session dates at UTC midnight, e.g. "2025-01-02T00:00:00.000Z".
    dates = pd.DatetimeIndex(
        pd.to_datetime(raw["date"], utc=True).dt.tz_localize(None).dt.normalize(), name="date"
    )
    # Index both frames by date *before* sorting, so adjClose stays aligned with its row.
    bars = as_float_frame(raw.rename(columns=_RENAME).set_index(dates)).sort_index()
    adj_close = pd.Series(raw["adjClose"].to_numpy(dtype=float), index=dates).sort_index()
    mismatch = max_return_mismatch(bars, adj_close)
    if mismatch > MISMATCH_WARN:
        log.warning("tiingo_return_mismatch", symbol=symbol, max_abs_diff=round(mismatch, 6))
    return bars
