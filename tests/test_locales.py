"""Consistency checks for UI translation files."""

import json
import pathlib
import re

import pytest

import event_dashboard

LOCALES = pathlib.Path(event_dashboard.__file__).parent / "static" / "locales"
STATIC = LOCALES.parent
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _load(path: pathlib.Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


REFERENCE = _load(LOCALES / "en.json")
LOCALE_FILES = sorted(LOCALES.glob("*.json"))


@pytest.mark.parametrize("path", LOCALE_FILES, ids=lambda p: p.stem)
def test_locale_matches_reference(path: pathlib.Path) -> None:
    messages = _load(path)
    assert set(messages) == set(REFERENCE)
    for key, text in messages.items():
        assert isinstance(text, str)
        assert text.strip(), key
        assert set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(REFERENCE[key])), key


def test_default_title_matches_server() -> None:
    from event_dashboard import config

    assert REFERENCE["defaultTitle"] == config.DEFAULT_TITLE
    assert f'SERVER_DEFAULT_TITLE = "{config.DEFAULT_TITLE}"' in (STATIC / "app.js").read_text()


def test_all_used_keys_exist() -> None:
    sources = (STATIC / "app.js").read_text() + (STATIC / "index.html").read_text()
    used = set(re.findall(r'\bt\("(\w+)"', sources))
    used |= set(re.findall(r'data-i18n(?:-placeholder|-title|-aria-label)?="(\w+)"', sources))
    assert used
    assert used <= set(REFERENCE), used - set(REFERENCE)


def test_fallback_locale_exists() -> None:
    assert 'FALLBACK_LANG = "en"' in (STATIC / "i18n.js").read_text()
    assert (LOCALES / "en.json").is_file()
