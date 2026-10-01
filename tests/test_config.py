"""Tests for configuration handling."""

import errno
import json
import os
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
    assert store.get().title == config.DEFAULT_TITLE
    assert store.get().theme == "auto"


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


def test_blank_title_uses_default() -> None:
    assert config.AppConfig(title="   ").title == config.DEFAULT_TITLE


def test_title_trimmed() -> None:
    assert config.AppConfig(title="  My Board ").title == "My Board"


def test_old_config_without_new_fields_loads(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"range_minutes": 45, "calendars": []}))
    cfg = config.ConfigStore(path).get()
    assert cfg.range_minutes == 45
    assert cfg.title == config.DEFAULT_TITLE
    assert cfg.theme == "auto"


def test_invalid_theme() -> None:
    with pytest.raises(pydantic.ValidationError):
        config.AppConfig(theme="blue")


def test_language_default_and_normalized() -> None:
    assert config.AppConfig().language == "auto"
    assert config.AppConfig(language=" DE ").language == "de"


@pytest.mark.parametrize("language", ["", "german", "../x", "d"])
def test_invalid_language_format(language: str) -> None:
    with pytest.raises(pydantic.ValidationError):
        config.AppConfig(language=language)


def test_unknown_language_still_loads(tmp_path: pathlib.Path) -> None:
    # A config that names a language whose file was removed must not stop the server.
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"language": "fr"}))
    assert config.ConfigStore(path).get().language == "fr"


def test_available_languages() -> None:
    assert {"de", "en"} <= set(config.available_languages())


@pytest.mark.parametrize("err", [errno.EBUSY, errno.EXDEV])
def test_save_falls_back_to_in_place_write(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, err: int
) -> None:
    path = tmp_path / "config.json"
    store = config.ConfigStore(path)

    def busy(src: str, dst: object) -> None:
        raise OSError(err, os.strerror(err))

    monkeypatch.setattr(config.os, "replace", busy)
    store.update(config.AppConfig(range_minutes=42))
    assert json.loads(path.read_text())["range_minutes"] == 42
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]  # temp file removed


def test_save_other_replace_errors_propagate(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = config.ConfigStore(tmp_path / "config.json")

    def denied(src: str, dst: object) -> None:
        raise PermissionError(errno.EACCES, "denied")

    monkeypatch.setattr(config.os, "replace", denied)
    with pytest.raises(PermissionError):
        store.update(config.AppConfig(range_minutes=42))
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]
