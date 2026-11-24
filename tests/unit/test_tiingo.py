"""Tiingo provider against a mocked HTTP transport (no network)."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import httpx
import pytest
import structlog

from arjuna.data.provider import BAR_COLUMNS, DataError
from arjuna.data.tiingo import API_KEY_ENV, BASE_URL, TiingoProvider

KEY = "test-key-not-real"


def row(
    date: str, close: float, adj: float, div: float = 0.0, split: float = 1.0
) -> dict[str, Any]:
    return {
        "date": f"{date}T00:00:00.000Z",
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": 1000,
        "adjOpen": adj,
        "adjHigh": adj,
        "adjLow": adj,
        "adjClose": adj,
        "adjVolume": 1000,
        "divCash": div,
        "splitFactor": split,
    }


ROWS = [
    row("2025-04-16", 100.0, 99.0),
    row("2025-04-17", 99.0, 99.0, div=1.0),  # ex-dividend; adjusted series is flat
    row("2025-04-21", 101.0, 101.0),
]


def provider(handler: Any) -> TiingoProvider:
    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return TiingoProvider(KEY, client=client)


def test_parses_bars_and_sends_auth_header() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=ROWS)

    bars = provider(handler).daily_bars("SPY", dt.date(2025, 4, 16), dt.date(2025, 4, 21))
    req = seen[0]
    assert req.url.path == "/tiingo/daily/spy/prices"
    assert req.url.params["startDate"] == "2025-04-16"
    assert req.url.params["endDate"] == "2025-04-21"
    assert req.headers["Authorization"] == f"Token {KEY}"
    assert tuple(bars.columns) == BAR_COLUMNS
    assert [d.date() for d in bars.index] == [
        dt.date(2025, 4, 16),
        dt.date(2025, 4, 17),
        dt.date(2025, 4, 21),
    ]
    assert bars.index.tz is None
    assert bars.loc["2025-04-17", "div_cash"] == 1.0
    assert "adjClose" not in bars.columns


def test_unsorted_response_keeps_adj_close_aligned() -> None:
    """Rows arriving newest-first must not misalign adjClose in the mismatch check."""
    with structlog.testing.capture_logs() as logs:
        bars = provider(lambda r: httpx.Response(200, json=list(reversed(ROWS)))).daily_bars(
            "SPY", dt.date(2025, 4, 16), dt.date(2025, 4, 21)
        )
    assert bars.index.is_monotonic_increasing
    assert bars.loc["2025-04-17", "div_cash"] == 1.0
    assert not any(e["event"] == "tiingo_return_mismatch" for e in logs)


def test_dotted_ticker_uses_hyphen() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=[])

    provider(handler).daily_bars("BRK.B", dt.date(2025, 4, 16), dt.date(2025, 4, 21))
    assert seen[0].url.path == "/tiingo/daily/brk-b/prices"


def test_context_manager_closes_own_client_only() -> None:
    owned = TiingoProvider(KEY)
    with owned:
        pass
    assert owned._client.is_closed

    injected = httpx.Client(
        base_url=BASE_URL, transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    with TiingoProvider(KEY, client=injected):
        pass
    assert not injected.is_closed


def test_empty_response() -> None:
    bars = provider(lambda r: httpx.Response(200, json=[])).daily_bars(
        "SPY", dt.date(2025, 4, 16), dt.date(2025, 4, 21)
    )
    assert bars.empty
    assert tuple(bars.columns) == BAR_COLUMNS


@pytest.mark.parametrize(
    ("status", "match"),
    [
        (401, "rejected the API key"),
        (403, "rejected the API key"),
        (404, "does not know"),
        (429, "rate limit"),
        (500, "HTTP 500"),
    ],
)
def test_http_errors(status: int, match: str) -> None:
    p = provider(lambda r: httpx.Response(status, json={"detail": "nope"}))
    with pytest.raises(DataError, match=match) as exc_info:
        p.daily_bars("SPY", dt.date(2025, 4, 16), dt.date(2025, 4, 21))
    assert KEY not in str(exc_info.value)


def test_network_error_does_not_leak_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"boom {req.headers['Authorization']}")

    with pytest.raises(DataError, match="ConnectError") as exc_info:
        provider(handler).daily_bars("SPY", dt.date(2025, 4, 16), dt.date(2025, 4, 21))
    assert KEY not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_missing_fields_rejected() -> None:
    bad = [{k: v for k, v in ROWS[0].items() if k != "divCash"}]
    with pytest.raises(DataError, match="divCash"):
        provider(lambda r: httpx.Response(200, json=bad)).daily_bars(
            "SPY", dt.date(2025, 4, 16), dt.date(2025, 4, 16)
        )


def test_non_list_response_rejected() -> None:
    with pytest.raises(DataError, match="JSON list"):
        provider(lambda r: httpx.Response(200, content=json.dumps({"a": 1}))).daily_bars(
            "SPY", dt.date(2025, 4, 16), dt.date(2025, 4, 16)
        )


def test_warns_when_events_disagree_with_adjusted_close() -> None:
    rows = [
        row("2025-04-16", 100.0, 99.0),
        row("2025-04-17", 99.0, 99.0, div=0.0),
    ]  # dividend missing
    with structlog.testing.capture_logs() as logs:
        provider(lambda r: httpx.Response(200, json=rows)).daily_bars(
            "SPY", dt.date(2025, 4, 16), dt.date(2025, 4, 17)
        )
    assert any(e["event"] == "tiingo_return_mismatch" for e in logs)


def test_no_warning_when_consistent() -> None:
    with structlog.testing.capture_logs() as logs:
        provider(lambda r: httpx.Response(200, json=ROWS)).daily_bars(
            "SPY", dt.date(2025, 4, 16), dt.date(2025, 4, 21)
        )
    assert not any(e["event"] == "tiingo_return_mismatch" for e in logs)


def test_repr_redacts_key() -> None:
    assert KEY not in repr(provider(lambda r: httpx.Response(200, json=[])))


def test_from_env_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    with pytest.raises(DataError, match=API_KEY_ENV):
        TiingoProvider.from_env()
