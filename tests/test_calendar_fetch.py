"""Tests for calendar fetching and caching."""

import pathlib
import ssl

import certifi
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
    with pytest.raises(calendar_fetch.FetchError, match="connection timed out"):
        fetcher.fetch("https://example.com/a.ics")


@respx.mock
def test_cache_expires_and_stale_copy_served_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(calendar_fetch.time, "monotonic", lambda: clock[0])
    route = respx.get("https://example.com/a.ics")
    route.side_effect = [
        httpx.Response(200, content=b"OLD"),
        httpx.Response(200, content=b"NEW"),
        httpx.Response(500),
    ]
    fetcher = calendar_fetch.CalendarFetcher(ttl=120)
    assert fetcher.fetch("https://example.com/a.ics") == b"OLD"
    clock[0] += 119
    assert fetcher.fetch("https://example.com/a.ics") == b"OLD"
    assert route.call_count == 1
    clock[0] += 1
    assert fetcher.fetch("https://example.com/a.ics") == b"NEW"
    clock[0] += 120
    assert fetcher.fetch("https://example.com/a.ics") == b"NEW"
    assert route.call_count == 3


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [({"ttl": 119}, "Cache TTL"), ({"timeout": 2}, "Fetch timeout")],
)
def test_minimums_enforced(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        calendar_fetch.CalendarFetcher(**kwargs)


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


def _cert_verify_error() -> httpx.ConnectError:
    cause = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] unable to get issuer")
    try:
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]") from cause
    except httpx.ConnectError as exc:
        return exc


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_cert_verify_error(), "TLS certificate not trusted"),
        (httpx.ConnectTimeout("t"), "connection timed out"),
        (httpx.ConnectError("[Errno -2] Name or service not known"), "Name or service not known"),
        (httpx.ProxyError("407 Proxy Authentication Required"), "proxy error"),
        (httpx.ReadError(""), "ReadError"),
    ],
)
@respx.mock
def test_fetch_error_messages(error: httpx.HTTPError, expected: str) -> None:
    respx.get("https://example.com/a.ics").mock(side_effect=error)
    with pytest.raises(calendar_fetch.FetchError, match=expected) as info:
        calendar_fetch.CalendarFetcher().fetch("https://example.com/a.ics?token=SECRET")
    assert "SECRET" not in str(info.value)


def test_ssl_context_loads_system_and_extra_bundle(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded: list[tuple[str | None, str | None]] = []
    real = ssl.SSLContext.load_verify_locations

    def spy(self, cafile=None, capath=None, cadata=None):  # noqa: ANN001, ANN202
        loaded.append((cafile, capath))
        return real(self, cafile=certifi.where())

    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", spy)
    system = tmp_path / "system.pem"
    system.write_text("x")
    extra_dir = tmp_path / "certs"
    extra_dir.mkdir()
    monkeypatch.setattr(calendar_fetch, "SYSTEM_CA_BUNDLES", (str(system), "/does/not/exist"))
    monkeypatch.setenv("SSL_CERT_FILE", str(system))
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)

    context = calendar_fetch.build_ssl_context(extra_dir)

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert (str(system), None) in loaded
    assert (None, str(extra_dir)) in loaded
    assert not any(cafile == "/does/not/exist" for cafile, _ in loaded)


def test_ssl_context_missing_bundle(tmp_path: pathlib.Path) -> None:
    with pytest.raises(FileNotFoundError):
        calendar_fetch.build_ssl_context(tmp_path / "missing.pem")


def test_ssl_context_invalid_bundle(tmp_path: pathlib.Path) -> None:
    bad = tmp_path / "bad.pem"
    bad.write_text("not a certificate")
    with pytest.raises(ssl.SSLError):
        calendar_fetch.build_ssl_context(bad)
