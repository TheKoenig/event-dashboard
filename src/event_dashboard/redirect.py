"""Minimal ASGI app that redirects plain HTTP requests to the HTTPS server."""

from __future__ import annotations

import collections.abc
import logging
import re

logger = logging.getLogger(__name__)

# Hostname, IPv4 address or bracketed IPv6 address, optionally followed by a port.
_HOST_RE = re.compile(r"^(?P<host>[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(?::\d+)?$")
_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::"})  # noqa: S104

Scope = collections.abc.MutableMapping[str, object]
Receive = collections.abc.Callable[[], collections.abc.Awaitable[dict[str, object]]]
Send = collections.abc.Callable[[dict[str, object]], collections.abc.Awaitable[None]]


def _target_host(scope: Scope) -> str:
    """Return the host to redirect to, taken from the Host header or the server address."""
    for name, value in scope.get("headers", []):  # type: ignore[attr-defined]
        if name == b"host":
            match = _HOST_RE.match(value.decode("latin-1").strip())
            if match:
                return match.group("host")
            break
    server = scope.get("server")
    host = server[0] if server else ""  # type: ignore[index]
    if host in _WILDCARD_HOSTS:
        return "localhost"
    return f"[{host}]" if ":" in host else host


def create_redirect_app(
    https_port: int,
) -> collections.abc.Callable[[Scope, Receive, Send], collections.abc.Awaitable[None]]:
    """Create an ASGI app that answers every HTTP request with a redirect to HTTPS.

    The redirect keeps host, path and query string and uses status 308, so the request method
    and body are preserved (e.g. ``PUT /api/config``).

    Args:
        https_port: Port of the HTTPS server; omitted from the URL when it is 443.

    Returns:
        The ASGI application.
    """
    port_suffix = "" if https_port == 443 else f":{https_port}"

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        path = scope.get("raw_path") or str(scope.get("path", "/")).encode()
        location = f"https://{_target_host(scope)}{port_suffix}{path.decode('latin-1')}"  # type: ignore[union-attr]
        query = scope.get("query_string") or b""
        if query:
            location += "?" + query.decode("latin-1")  # type: ignore[union-attr]
        await send(
            {
                "type": "http.response.start",
                "status": 308,
                "headers": [(b"location", location.encode("latin-1")), (b"content-length", b"0")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    return app
