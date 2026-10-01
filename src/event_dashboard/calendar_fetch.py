"""Fetching and caching of remote ICS calendars."""

from __future__ import annotations

import dataclasses
import logging
import threading
import time

import httpx

logger = logging.getLogger(__name__)

MAX_ICS_BYTES = 20 * 1024 * 1024


class FetchError(Exception):
    """Raised when a calendar cannot be fetched."""


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
        timeout: Request timeout in seconds.
        ttl: Cache time-to-live in seconds.
        client: Optional preconfigured ``httpx.Client`` (useful for tests).
    """

    def __init__(
        self, timeout: float = 15.0, ttl: float = 300.0, client: httpx.Client | None = None
    ) -> None:
        self.ttl = ttl
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
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
            raise FetchError(f"Could not fetch calendar: {exc.__class__.__name__}") from exc
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
