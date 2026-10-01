"""Tests for the CLI entry point."""

import pathlib

import click.testing
import pytest

from event_dashboard import __main__ as main


def test_serve_starts_uvicorn(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {}
    monkeypatch.setattr(main.uvicorn, "run", lambda app, **kw: calls.update(kw))
    cfg = tmp_path / "c.json"
    result = click.testing.CliRunner().invoke(
        main.cli, ["serve", "--config", str(cfg), "--port", "9999"]
    )
    assert result.exit_code == 0, result.output
    assert calls["port"] == 9999
    assert cfg.exists()


def test_serve_bad_config(tmp_path: pathlib.Path) -> None:
    cfg = tmp_path / "c.json"
    cfg.write_text("[]")
    result = click.testing.CliRunner().invoke(main.cli, ["serve", "--config", str(cfg)])
    assert result.exit_code != 0
    assert "Invalid config" in result.output


def test_serve_missing_ca_bundle(tmp_path: pathlib.Path) -> None:
    result = click.testing.CliRunner().invoke(
        main.cli,
        ["serve", "--config", str(tmp_path / "c.json"), "--ca-bundle", str(tmp_path / "x.pem")],
    )
    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_serve_invalid_ca_bundle(tmp_path: pathlib.Path) -> None:
    bad = tmp_path / "bad.pem"
    bad.write_text("nope")
    result = click.testing.CliRunner().invoke(
        main.cli, ["serve", "--config", str(tmp_path / "c.json"), "--ca-bundle", str(bad)]
    )
    assert result.exit_code != 0
    assert "Invalid CA bundle" in result.output


def test_default_cache_ttl_and_timeout_are_ints(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EVENT_DASHBOARD_CACHE_TTL", raising=False)
    monkeypatch.delenv("EVENT_DASHBOARD_FETCH_TIMEOUT", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    seen = {}
    real = main.calendar_fetch.CalendarFetcher

    def capture(**kwargs):  # noqa: ANN003, ANN202
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(main.calendar_fetch, "CalendarFetcher", capture)
    monkeypatch.setattr(main.uvicorn, "run", lambda app, **kw: None)
    result = click.testing.CliRunner().invoke(main.cli, ["serve", "--config", "c.json"])
    assert result.exit_code == 0, result.output
    assert seen["ttl"] == 3600
    assert isinstance(seen["ttl"], int)
    assert seen["timeout"] == 15
    assert isinstance(seen["timeout"], int)


@pytest.mark.parametrize("option", ["--cache-ttl", "--fetch-timeout"])
def test_int_options_reject_fractions(tmp_path: pathlib.Path, option: str) -> None:
    result = click.testing.CliRunner().invoke(
        main.cli, ["serve", "--config", str(tmp_path / "c.json"), option, "1.5"]
    )
    assert result.exit_code != 0
    assert "is not a valid integer" in result.output


@pytest.mark.parametrize(("option", "value"), [("--cache-ttl", "119"), ("--fetch-timeout", "2")])
def test_options_below_minimum_rejected(tmp_path: pathlib.Path, option: str, value: str) -> None:
    result = click.testing.CliRunner().invoke(
        main.cli, ["serve", "--config", str(tmp_path / "c.json"), option, value]
    )
    assert result.exit_code != 0
    assert "is not in the range" in result.output
