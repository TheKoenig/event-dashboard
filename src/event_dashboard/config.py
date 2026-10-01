"""Application configuration models and persistence."""

from __future__ import annotations

import errno
import importlib.resources
import json
import logging
import os
import pathlib
import tempfile
import threading
import typing
import uuid

import pydantic

logger = logging.getLogger(__name__)

DEFAULT_RANGE_MINUTES = 120
MAX_RANGE_MINUTES = 7 * 24 * 60
ALLOWED_SCHEMES = ("http://", "https://", "webcal://", "webcals://")
DEFAULT_COLORS = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b")
DEFAULT_TITLE = "Upcoming events"
DEFAULT_STARTED_KEEP_MINUTES = 5
MAX_STARTED_KEEP_MINUTES = 24 * 60
DEFAULT_WARN_MINUTES = 15
DEFAULT_WARN_COLOR = "#ff8c00"
DEFAULT_ALERT_MINUTES = 3
DEFAULT_ALERT_COLOR = "#e53935"
_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"
AUTO_LANGUAGE = "auto"
Theme = typing.Literal["auto", "light", "dark"]
_LANGUAGE_PATTERN = r"^(auto|[a-z]{2,3}(-[a-z0-9]{2,8})?)$"


def available_languages() -> list[str]:
    """Return the language codes that have a translation file, sorted.

    Returns:
        Language codes such as ``["de", "en"]``.
    """
    locales = importlib.resources.files("event_dashboard") / "static" / "locales"
    return sorted(
        entry.name.removesuffix(".json")
        for entry in locales.iterdir()
        if entry.name.endswith(".json")
    )


class CalendarConfig(pydantic.BaseModel):
    """A single subscribed calendar.

    Attributes:
        id: Stable identifier of the calendar.
        name: Display name.
        url: ICS or webcal URL.
        color: Hex color (``#rrggbb``) used for the progress bars.
    """

    id: str = pydantic.Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = pydantic.Field(min_length=1, max_length=100)
    url: str = pydantic.Field(min_length=1, max_length=2048)
    color: str = pydantic.Field(default=DEFAULT_COLORS[0], pattern=_COLOR_PATTERN)

    @pydantic.field_validator("name", "url")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @pydantic.field_validator("url")
    @classmethod
    def _check_scheme(cls, value: str) -> str:
        if not value.lower().startswith(ALLOWED_SCHEMES):
            raise ValueError("URL must start with http://, https://, webcal:// or webcals://")
        return value

    @pydantic.field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        value = value.strip()
        return value or uuid.uuid4().hex[:12]


class AppConfig(pydantic.BaseModel):
    """Top-level application configuration.

    Attributes:
        title: Page title shown in the header and browser tab.
        theme: Color theme; ``auto`` follows the operating system preference.
        language: UI language code; ``auto`` uses the browser language.
        range_minutes: Look-ahead window for upcoming events in minutes.
        started_keep_minutes: How long a started event stays visible (full grey bar); 0 hides it
            immediately.
        warn_minutes: Bars switch to ``warn_color`` this many minutes before the start; 0 disables.
        warn_color: Hex color for approaching events.
        alert_minutes: Bars switch to ``alert_color`` and blink this many minutes before the
            start; 0 disables. Must not exceed ``warn_minutes`` unless that is 0.
        alert_color: Hex color for imminent events.
        calendars: List of subscribed calendars.
    """

    title: str = pydantic.Field(default=DEFAULT_TITLE, max_length=100)
    theme: Theme = "auto"
    language: str = pydantic.Field(default=AUTO_LANGUAGE, pattern=_LANGUAGE_PATTERN)
    range_minutes: int = pydantic.Field(default=DEFAULT_RANGE_MINUTES, ge=1, le=MAX_RANGE_MINUTES)
    started_keep_minutes: int = pydantic.Field(
        default=DEFAULT_STARTED_KEEP_MINUTES, ge=0, le=MAX_STARTED_KEEP_MINUTES
    )
    warn_minutes: int = pydantic.Field(default=DEFAULT_WARN_MINUTES, ge=0, le=MAX_RANGE_MINUTES)
    warn_color: str = pydantic.Field(default=DEFAULT_WARN_COLOR, pattern=_COLOR_PATTERN)
    alert_minutes: int = pydantic.Field(default=DEFAULT_ALERT_MINUTES, ge=0, le=MAX_RANGE_MINUTES)
    alert_color: str = pydantic.Field(default=DEFAULT_ALERT_COLOR, pattern=_COLOR_PATTERN)
    calendars: list[CalendarConfig] = pydantic.Field(default_factory=list)

    @pydantic.field_validator("title")
    @classmethod
    def _default_title(cls, value: str) -> str:
        return value.strip() or DEFAULT_TITLE

    @pydantic.field_validator("language", mode="before")
    @classmethod
    def _normalize_language(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @pydantic.model_validator(mode="after")
    def _alert_within_warn(self) -> AppConfig:
        if self.warn_minutes and self.alert_minutes > self.warn_minutes:
            raise ValueError("alert_minutes must not be greater than warn_minutes")
        return self

    @pydantic.model_validator(mode="after")
    def _unique_ids(self) -> AppConfig:
        ids = [cal.id for cal in self.calendars]
        if len(ids) != len(set(ids)):
            raise ValueError("calendar ids must be unique")
        return self


class ConfigStore:
    """Thread-safe JSON-file backed configuration store.

    Args:
        path: Path of the JSON configuration file.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = pathlib.Path(path).expanduser().resolve()
        self._lock = threading.Lock()
        self._config = self._load()

    def _load(self) -> AppConfig:
        if not self.path.exists():
            logger.info("Config %s not found, creating default config", self.path)
            config = AppConfig()
            self._write(config)
            return config
        try:
            with self.path.open(encoding="utf-8") as handle:
                data = json.load(handle)
            return AppConfig.model_validate(data)
        except (json.JSONDecodeError, pydantic.ValidationError, OSError) as exc:
            raise ConfigError(f"Invalid config file {self.path}: {exc}") from exc

    def _write(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".config-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(config.model_dump(), handle, indent=2, ensure_ascii=False)
            try:
                os.replace(tmp_name, self.path)
            except OSError as exc:
                # A bind-mounted file (e.g. Docker ``-v ./config.json:/data/config.json``) cannot
                # be replaced by rename; overwrite it in place instead.
                if exc.errno not in (errno.EBUSY, errno.EXDEV):
                    raise
                logger.debug("Atomic replace of %s failed (%s), writing in place", self.path, exc)
                with self.path.open("w", encoding="utf-8") as handle:
                    json.dump(config.model_dump(), handle, indent=2, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                pathlib.Path(tmp_name).unlink(missing_ok=True)
        except BaseException:
            pathlib.Path(tmp_name).unlink(missing_ok=True)
            raise

    def get(self) -> AppConfig:
        """Return a copy of the current configuration."""
        with self._lock:
            return self._config.model_copy(deep=True)

    def update(self, config: AppConfig) -> AppConfig:
        """Persist and activate a new configuration.

        Args:
            config: The validated new configuration.

        Returns:
            The stored configuration.
        """
        with self._lock:
            self._write(config)
            self._config = config.model_copy(deep=True)
            logger.info("Saved config with %d calendar(s)", len(config.calendars))
            return self._config.model_copy(deep=True)


class ConfigError(Exception):
    """Raised when the configuration file cannot be loaded."""
