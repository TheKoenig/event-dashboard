"""Application configuration models and persistence."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import tempfile
import threading
import uuid

import pydantic

logger = logging.getLogger(__name__)

DEFAULT_RANGE_MINUTES = 120
MAX_RANGE_MINUTES = 7 * 24 * 60
ALLOWED_SCHEMES = ("http://", "https://", "webcal://", "webcals://")
DEFAULT_COLORS = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b")


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
    color: str = pydantic.Field(default=DEFAULT_COLORS[0], pattern=r"^#[0-9a-fA-F]{6}$")

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
        range_minutes: Look-ahead window for upcoming events in minutes.
        calendars: List of subscribed calendars.
    """

    range_minutes: int = pydantic.Field(default=DEFAULT_RANGE_MINUTES, ge=1, le=MAX_RANGE_MINUTES)
    calendars: list[CalendarConfig] = pydantic.Field(default_factory=list)

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
            os.replace(tmp_name, self.path)
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
