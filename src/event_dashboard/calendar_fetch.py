"""Fetching and caching of remote ICS calendars."""

from __future__ import annotations

import dataclasses
import logging
import os
import pathlib
import ssl
import threading
import time

import certifi
import httpx

logger = logging.getLogger(__name__)

MAX_ICS_BYTES = 20 * 1024 * 1024
# Lower bounds that keep the dashboard from hammering calendar servers or giving up too early.
MIN_CACHE_TTL = 120
MIN_FETCH_TIMEOUT = 3

# Well-known OS certificate bundles. Corporate TLS-inspection CAs are usually installed here,
# but Python distributions such as conda/miniforge ship their own bundle and ignore these files.
SYSTEM_CA_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",  # RHEL/Fedora
    "/etc/ssl/ca-bundle.pem",  # openSUSE
    "/etc/ssl/cert.pem",  # Alpine/macOS
)


class FetchError(Exception):
    """Raised when a calendar cannot be fetched."""


def build_ssl_context(ca_bundle: str | os.PathLike[str] | None = None) -> ssl.SSLContext:
    """Create the TLS context used for calendar downloads.

    Trusts the certifi bundle, the operating system's bundle (if found), any ``SSL_CERT_FILE`` /
    ``SSL_CERT_DIR`` from the environment, and an optional extra CA file or directory.

    Args:
        ca_bundle: Optional PEM file or directory with additional trusted CA certificates.

    Returns:
        A configured client-side SSL context.

    Raises:
        FileNotFoundError: If ``ca_bundle`` does not exist.
        ssl.SSLError: If ``ca_bundle`` contains no valid certificates.
    """
    context = ssl.create_default_context(cafile=certifi.where())
    for path in SYSTEM_CA_BUNDLES:
        if os.path.isfile(path):
            try:
                context.load_verify_locations(cafile=path)
                logger.debug("Loaded system CA bundle %s", path)
            except (OSError, ssl.SSLError) as exc:
                logger.warning("Ignoring unreadable CA bundle %s: %s", path, exc)
    env_file, env_dir = os.environ.get("SSL_CERT_FILE"), os.environ.get("SSL_CERT_DIR")
    if env_file and os.path.isfile(env_file):
        context.load_verify_locations(cafile=env_file)
    if env_dir and os.path.isdir(env_dir):
        context.load_verify_locations(capath=env_dir)
    if ca_bundle:
        path = pathlib.Path(ca_bundle).expanduser()
        if path.is_dir():
            context.load_verify_locations(capath=str(path))
        elif path.is_file():
            context.load_verify_locations(cafile=str(path))
        else:
            raise FileNotFoundError(f"CA bundle not found: {path}")
        logger.info("Using additional CA certificates from %s", path)
    return context


def _describe_error(exc: httpx.HTTPError) -> str:
    """Return a short, user-facing reason for a failed download (never includes the URL)."""
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(
            cause
        ):
            return (
                "TLS certificate not trusted (a TLS-inspecting proxy may be in use; "
                "set EVENT_DASHBOARD_CA_BUNDLE to its CA certificate)"
            )
        cause = cause.__cause__ or cause.__context__
    if isinstance(exc, httpx.TimeoutException):
        return "connection timed out"
    if isinstance(exc, httpx.ProxyError):
        return f"proxy error ({exc})"
    if isinstance(exc, httpx.ConnectError):
        detail = str(exc).strip()
        return f"connection failed ({detail})" if detail else "connection failed"
    return exc.__class__.__name__


def normalize_url(url: str) -> str:
    """Convert ``webcal://``/``webcals://`` URLs to ``https://``.

    Args:
        url: Calendar URL as entered by the user.

    Returns:
        A URL usable with an HTTP client.
    """
    url = url.strip()
    lower = url.lower()
    for prefix in ("webcals://", "webcal://"):
        if lower.startswith(prefix):
            return "https://" + url[len(prefix) :]
    return url


@dataclasses.dataclass
class _CacheEntry:
    content: bytes
    fetched_at: float


class CalendarFetcher:
    """Fetches ICS data over HTTP with a time-based cache.

    Args:
        timeout: Request timeout in seconds (at least ``MIN_FETCH_TIMEOUT``).
        ttl: Cache time-to-live in seconds (at least ``MIN_CACHE_TTL``).
        client: Optional preconfigured ``httpx.Client`` (useful for tests).
        ca_bundle: Optional extra CA file or directory to trust (see ``build_ssl_context``).

    Raises:
        ValueError: If ``timeout`` or ``ttl`` is below its minimum.
    """

    def __init__(
        self,
        timeout: int = 15,
        ttl: int = 3600,
        client: httpx.Client | None = None,
        ca_bundle: str | os.PathLike[str] | None = None,
    ) -> None:
        if ttl < MIN_CACHE_TTL:
            raise ValueError(f"Cache TTL must be at least {MIN_CACHE_TTL} seconds")
        if timeout < MIN_FETCH_TIMEOUT:
            raise ValueError(f"Fetch timeout must be at least {MIN_FETCH_TIMEOUT} seconds")
        self.ttl = ttl
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            verify=build_ssl_context(ca_bundle),
            headers={"User-Agent": "event-dashboard/0.1", "Accept": "text/calendar, */*"},
        )
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def fetch(self, url: str, force: bool = False) -> bytes:
        """Return ICS bytes for ``url``, using the cache if still fresh.

        If a refresh fails but stale data is cached, the stale data is returned.

        Args:
            url: Calendar URL (``webcal`` URLs are accepted).
            force: Download again even if the cached copy is still fresh.

        Returns:
            Raw ICS content.

        Raises:
            FetchError: If the calendar cannot be fetched and nothing is cached.
        """
        http_url = normalize_url(url)
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(http_url)
        if entry and not force and now - entry.fetched_at < self.ttl:
            return entry.content
        try:
            content = self._download(http_url)
        except FetchError:
            if entry:
                logger.warning("Refresh of %s failed, serving stale cache", http_url)
                return entry.content
            raise
        with self._lock:
            self._cache[http_url] = _CacheEntry(content, now)
        return content

    def _download(self, url: str) -> bytes:
        logger.debug("Fetching %s", url)
        try:
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FetchError(f"HTTP {exc.response.status_code} for calendar URL") from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"Could not fetch calendar: {_describe_error(exc)}") from exc
        content = response.content
        if len(content) > MAX_ICS_BYTES:
            raise FetchError("Calendar file too large")
        return content

    def clear(self) -> None:
        """Drop all cached calendars."""
        with self._lock:
            self._cache.clear()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()
