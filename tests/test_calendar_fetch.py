"""Tests for calendar fetching and caching."""

import httpx
import pytest
import respx

from event_dashboard import calendar_fetch


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("webcal://example.com/a.ics", "https://example.com/a.ics"),
        ("WEBCALS://example.com/a.ics", "https://example.com/a.ics"),
        (" https://example.com/a.ics ", "https://example.com/a.ics"),
        ("http://example.com/a.ics", "http://example.com/a.ics"),
    ],
)
def test_normalize_url(url: str, expected: str) -> None:
    assert calendar_fetch.normalize_url(url) == expected


@respx.mock
def test_fetch_uses_cache() -> None:
    route = respx.get("https://example.com/a.ics").mock(
        return_value=httpx.Response(200, content=b"DATA")
    )
    fetcher = calendar_fetch.CalendarFetcher(ttl=300)
    assert fetcher.fetch("webcal://example.com/a.ics") == b"DATA"
    assert fetcher.fetch("https://example.com/a.ics") == b"DATA"
    assert route.call_count == 1
    fetcher.clear()
    fetcher.fetch("https://example.com/a.ics")
    assert route.call_count == 2
    fetcher.close()


@respx.mock
def test_fetch_http_error() -> None:
    respx.get("https://example.com/a.ics").mock(return_value=httpx.Response(404))
    fetcher = calendar_fetch.CalendarFetcher()
    with pytest.raises(calendar_fetch.FetchError, match="HTTP 404"):
        fetcher.fetch("https://example.com/a.ics")


@respx.mock
def test_fetch_network_error() -> None:
    respx.get("https://example.com/a.ics").mock(side_effect=httpx.ConnectTimeout("boom"))
    fetcher = calendar_fetch.CalendarFetcher()
    with pytest.raises(calendar_fetch.FetchError, match="ConnectTimeout"):
        fetcher.fetch("https://example.com/a.ics")


@respx.mock
def test_stale_cache_served_on_failure() -> None:
    route = respx.get("https://example.com/a.ics")
    route.side_effect = [httpx.Response(200, content=b"OLD"), httpx.Response(500)]
    fetcher = calendar_fetch.CalendarFetcher(ttl=0)
    assert fetcher.fetch("https://example.com/a.ics") == b"OLD"
    assert fetcher.fetch("https://example.com/a.ics") == b"OLD"


@respx.mock
def test_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calendar_fetch, "MAX_ICS_BYTES", 3)
    respx.get("https://example.com/a.ics").mock(return_value=httpx.Response(200, content=b"1234"))
    with pytest.raises(calendar_fetch.FetchError, match="too large"):
        calendar_fetch.CalendarFetcher().fetch("https://example.com/a.ics")


@respx.mock
def test_force_bypasses_fresh_cache() -> None:
    route = respx.get("https://example.com/a.ics")
    route.side_effect = [
        httpx.Response(200, content=b"OLD"),
        httpx.Response(200, content=b"NEW"),
        httpx.Response(500),
    ]
    fetcher = calendar_fetch.CalendarFetcher(ttl=300)
    assert fetcher.fetch("https://example.com/a.ics") == b"OLD"
    assert fetcher.fetch("https://example.com/a.ics", force=True) == b"NEW"
    assert fetcher.fetch("https://example.com/a.ics") == b"NEW"
    # A failed forced refresh keeps serving the last good copy.
    assert fetcher.fetch("https://example.com/a.ics", force=True) == b"NEW"
    assert route.call_count == 3
