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
