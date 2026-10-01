"""Tests for the HTTP to HTTPS redirect app."""

import fastapi.testclient
import pytest

from event_dashboard import redirect


@pytest.mark.parametrize(
    ("host", "https_port", "expected"),
    [
        ("example.com:8080", 8090, "https://example.com:8090/api/x?a=1&b=%20"),
        ("example.com", 443, "https://example.com/api/x?a=1&b=%20"),
        ("[::1]:8080", 8090, "https://[::1]:8090/api/x?a=1&b=%20"),
        ("10.0.0.5:8080", 8090, "https://10.0.0.5:8090/api/x?a=1&b=%20"),
        ("evil.com/@x\r\nSet-Cookie: a", 8090, "https://testserver:8090/api/x?a=1&b=%20"),
    ],
)
def test_redirects_to_https(host: str, https_port: int, expected: str) -> None:
    client = fastapi.testclient.TestClient(redirect.create_redirect_app(https_port))
    resp = client.get("/api/x?a=1&b=%20", headers={"host": host}, follow_redirects=False)
    assert resp.status_code == 308
    assert resp.headers["location"] == expected


def test_method_preserving_redirect() -> None:
    client = fastapi.testclient.TestClient(redirect.create_redirect_app(8090))
    resp = client.put("/api/config", json={}, follow_redirects=False)
    assert resp.status_code == 308
    assert resp.headers["location"] == "https://testserver:8090/api/config"


@pytest.mark.parametrize(
    ("server", "expected"),
    [
        (("0.0.0.0", 8080), "localhost"),  # noqa: S104
        (("::1", 8080), "[::1]"),
        (None, "localhost"),
    ],
)
def test_target_host_without_host_header(server: tuple | None, expected: str) -> None:
    assert redirect._target_host({"headers": [], "server": server}) == expected
