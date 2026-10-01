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
