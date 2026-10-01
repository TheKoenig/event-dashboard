"""Tests for configuration handling."""

import json
import pathlib

import pydantic
import pytest

from event_dashboard import config


def test_default_config_created(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "sub" / "config.json"
    store = config.ConfigStore(path)
    assert path.exists()
    assert store.get().range_minutes == config.DEFAULT_RANGE_MINUTES
    assert store.get().calendars == []


def test_update_persists(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "config.json"
    store = config.ConfigStore(path)
    new = config.AppConfig(
        range_minutes=60,
        calendars=[config.CalendarConfig(name="Work", url="webcal://x/cal.ics", color="#AABBCC")],
    )
    store.update(new)
    reloaded = config.ConfigStore(path).get()
    assert reloaded == new
    assert json.loads(path.read_text())["range_minutes"] == 60
    assert not list(tmp_path.glob(".config-*"))


def test_invalid_file_raises(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json")
    with pytest.raises(config.ConfigError):
        config.ConfigStore(path)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "A", "url": "ftp://x/cal.ics"},
        {"name": "A", "url": "https://x", "color": "red"},
        {"name": "  ", "url": "https://x"},
        {"name": "A", "url": "javascript:alert(1)"},
    ],
)
def test_invalid_calendar(kwargs: dict) -> None:
    with pytest.raises(pydantic.ValidationError):
        config.CalendarConfig(**kwargs)


@pytest.mark.parametrize("minutes", [0, config.MAX_RANGE_MINUTES + 1])
def test_invalid_range(minutes: int) -> None:
    with pytest.raises(pydantic.ValidationError):
        config.AppConfig(range_minutes=minutes)


def test_duplicate_ids_rejected() -> None:
    cal = {"id": "same", "name": "A", "url": "https://x"}
    with pytest.raises(pydantic.ValidationError):
        config.AppConfig(calendars=[cal, cal])


def test_blank_id_regenerated() -> None:
    assert config.CalendarConfig(id=" ", name="A", url="https://x").id
