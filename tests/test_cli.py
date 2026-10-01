"""Tests for the CLI entry point."""

import os
import pathlib
import shutil
import socket
import subprocess

import click.testing
import fastapi.testclient
import pytest

from event_dashboard import __main__ as main


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's .env and EVENT_DASHBOARD_* variables out of the tests."""
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.startswith("EVENT_DASHBOARD_"):
            monkeypatch.delenv(name)


def test_serve_starts_uvicorn(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configs = []
    monkeypatch.setattr(main, "_run", configs.extend)
    cfg = tmp_path / "c.json"
    result = click.testing.CliRunner().invoke(
        main.cli, ["serve", "--config", str(cfg), "--port", "9999"]
    )
    assert result.exit_code == 0, result.output
    assert [c.port for c in configs] == [9999]
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
    monkeypatch.setattr(main, "_run", lambda configs: None)
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


@pytest.fixture(scope="module")
def tls_files(tmp_path_factory: pytest.TempPathFactory) -> tuple[pathlib.Path, pathlib.Path]:
    directory = tmp_path_factory.mktemp("tls")
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return cert, key


def _serve(tmp_path: pathlib.Path, *args: str) -> click.testing.Result:
    return click.testing.CliRunner().invoke(
        main.cli, ["serve", "--config", str(tmp_path / "c.json"), *args]
    )


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_serve_with_tls(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    tls_files: tuple[pathlib.Path, pathlib.Path],
) -> None:
    monkeypatch.delenv("EVENT_DASHBOARD_HTTP_REDIRECT_PORT", raising=False)
    configs = []
    monkeypatch.setattr(main, "_run", configs.extend)
    cert, key = tls_files
    args = ("--port", "9443", "--ssl-certfile", str(cert), "--ssl-keyfile", str(key))
    result = _serve(tmp_path, *args)
    assert result.exit_code == 0, result.output
    app_cfg, redirect_cfg = configs
    assert app_cfg.port == 9443
    assert app_cfg.ssl_certfile == str(cert)
    assert app_cfg.ssl_keyfile == str(key)
    assert app_cfg.ssl_keyfile_password is None
    assert redirect_cfg.port == 80
    assert redirect_cfg.ssl_certfile is None

    configs.clear()
    assert _serve(tmp_path, *args, "--public-https-port", "8443").exit_code == 0
    redirect_app = configs[1].app
    client = fastapi.testclient.TestClient(redirect_app)
    resp = client.get("/x", headers={"host": "h:80"}, follow_redirects=False)
    assert resp.headers["location"] == "https://h:8443/x"

    configs.clear()
    assert _serve(tmp_path, *args, "--http-redirect-port", "0").exit_code == 0
    assert len(configs) == 1

    result = _serve(tmp_path, *args, "--http-redirect-port", "9443")
    assert result.exit_code != 0
    assert "must differ from --port" in result.output


def test_serve_without_tls_passes_no_ssl_options(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("CERTFILE", "KEYFILE", "KEYFILE_PASSWORD"):
        monkeypatch.delenv(f"EVENT_DASHBOARD_SSL_{var}", raising=False)
    configs = []
    monkeypatch.setattr(main, "_run", configs.extend)
    assert _serve(tmp_path, "--http-redirect-port", "8081").exit_code == 0
    (cfg,) = configs  # no redirect server without TLS
    assert cfg.ssl_certfile is None


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_default_ports(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    tls_files: tuple[pathlib.Path, pathlib.Path],
) -> None:
    configs = []
    monkeypatch.setattr(main, "_run", configs.extend)
    assert _serve(tmp_path).exit_code == 0
    assert [c.port for c in configs] == [80]
    configs.clear()
    cert, key = tls_files
    assert _serve(tmp_path, "--ssl-certfile", str(cert), "--ssl-keyfile", str(key)).exit_code == 0
    assert [c.port for c in configs] == [443, 80]


def test_bind_error_is_reported() -> None:
    with socket.create_server(("127.0.0.1", 0)) as busy:
        port = busy.getsockname()[1]
        with pytest.raises(click.ClickException, match=f"Cannot listen on 127.0.0.1:{port}"):
            main._bind("127.0.0.1", port)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_serve_tls_requires_cert_and_key(
    tmp_path: pathlib.Path, tls_files: tuple[pathlib.Path, pathlib.Path]
) -> None:
    cert, key = tls_files
    for args in (["--ssl-certfile", str(cert)], ["--ssl-keyfile", str(key)]):
        result = _serve(tmp_path, *args)
        assert result.exit_code != 0
        assert "must be given together" in result.output
    result = _serve(tmp_path, "--ssl-keyfile-password", "x")
    assert result.exit_code != 0
    assert "requires --ssl-keyfile" in result.output


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_serve_tls_mismatched_files(
    tmp_path: pathlib.Path, tls_files: tuple[pathlib.Path, pathlib.Path]
) -> None:
    cert, _ = tls_files
    # Using the certificate as key cannot work.
    result = _serve(tmp_path, "--ssl-certfile", str(cert), "--ssl-keyfile", str(cert))
    assert result.exit_code != 0
    assert "Cannot load TLS certificate/key" in result.output


def test_bind_permission_error_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*args: object, **kwargs: object) -> None:
        raise PermissionError("Permission denied")

    monkeypatch.setattr(main.socket, "create_server", deny)
    with pytest.raises(click.ClickException, match="Ports below 1024 need root"):
        main._bind("0.0.0.0", 80)  # noqa: S104
