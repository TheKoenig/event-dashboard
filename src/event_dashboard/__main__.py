"""Command line entry point for the event dashboard."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import ssl

import click
import dotenv
import uvicorn

from event_dashboard import app as app_module
from event_dashboard import calendar_fetch, config, redirect

logger = logging.getLogger("event_dashboard")

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _tls_options(certfile: str | None, keyfile: str | None, password: str | None) -> dict[str, str]:
    """Validate the TLS files and return the matching ``uvicorn.run`` keyword arguments.

    Args:
        certfile: PEM certificate (chain) or ``None``.
        keyfile: PEM private key or ``None``.
        password: Password of an encrypted private key, if any.

    Returns:
        Keyword arguments for ``uvicorn.run``; empty when TLS is disabled.

    Raises:
        click.UsageError: If only one of certificate and key is given.
        click.ClickException: If the certificate and key cannot be loaded.
    """
    if not certfile and not keyfile:
        if password:
            raise click.UsageError("--ssl-keyfile-password requires --ssl-keyfile.")
        return {}
    if not certfile or not keyfile:
        raise click.UsageError("--ssl-certfile and --ssl-keyfile must be given together.")
    # Load once up front so a wrong file, password or mismatched key fails with a clear message.
    try:
        ssl.create_default_context(ssl.Purpose.CLIENT_AUTH).load_cert_chain(
            certfile, keyfile, password
        )
    except (OSError, ssl.SSLError) as exc:
        raise click.ClickException(
            "Cannot load TLS certificate/key (not PEM, key does not match the certificate, "
            f"or wrong key password): {exc}"
        ) from exc
    options = {"ssl_certfile": certfile, "ssl_keyfile": keyfile}
    if password:
        options["ssl_keyfile_password"] = password
    return options


def _bind(host: str, port: int) -> socket.socket:
    """Open a listening socket, turning failures into a clear CLI error."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        return socket.create_server((host, port), family=family)
    except PermissionError as exc:
        raise click.ClickException(
            f"Cannot listen on {host}:{port}: {exc}. Ports below 1024 need root or "
            "CAP_NET_BIND_SERVICE; choose another port with --port/--http-redirect-port."
        ) from exc
    except OSError as exc:
        raise click.ClickException(f"Cannot listen on {host}:{port}: {exc}") from exc


async def _serve_all(servers: list[tuple[uvicorn.Server, socket.socket]]) -> None:
    """Run the main server and any helper servers until the main server stops."""
    (main_server, main_sock), *helpers = servers
    tasks = [asyncio.create_task(srv.serve(sockets=[sock])) for srv, sock in helpers]
    try:
        await main_server.serve(sockets=[main_sock])
    finally:
        for srv, _ in helpers:
            srv.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)


def _run(configs: list[uvicorn.Config]) -> None:
    """Bind all ports first, then serve every config in one event loop.

    The first config is the main application; when it stops, the others are stopped too.
    """
    sockets: list[socket.socket] = []
    try:
        for cfg in configs:
            sockets.append(_bind(cfg.host, cfg.port))
        asyncio.run(
            _serve_all([(uvicorn.Server(c), s) for c, s in zip(configs, sockets, strict=True)])
        )
    finally:
        for sock in sockets:
            sock.close()


@click.group()
def cli() -> None:
    """Event dashboard: upcoming calendar events as progress bars."""
    dotenv.load_dotenv(dotenv.find_dotenv(usecwd=True))


@cli.command()
@click.option("--host", envvar="EVENT_DASHBOARD_HOST", default="127.0.0.1", show_default=True)
@click.option(
    "--port",
    envvar="EVENT_DASHBOARD_PORT",
    default=None,
    type=click.IntRange(min=1, max=65535),
    help="Port to listen on.  [default: 443 with TLS, otherwise 80]",
)
@click.option(
    "--config",
    "config_path",
    envvar="EVENT_DASHBOARD_CONFIG",
    default="config.json",
    show_default=True,
    type=click.Path(dir_okay=False),
    help="JSON configuration file (created if missing).",
)
@click.option(
    "--fetch-timeout",
    envvar="EVENT_DASHBOARD_FETCH_TIMEOUT",
    default=15,
    type=click.IntRange(min=calendar_fetch.MIN_FETCH_TIMEOUT),
    show_default=True,
    help="HTTP timeout in seconds for calendar downloads.",
)
@click.option(
    "--cache-ttl",
    envvar="EVENT_DASHBOARD_CACHE_TTL",
    default=3600,
    type=click.IntRange(min=calendar_fetch.MIN_CACHE_TTL),
    show_default=True,
    help="Seconds to cache downloaded calendars.",
)
@click.option(
    "--ca-bundle",
    envvar="EVENT_DASHBOARD_CA_BUNDLE",
    default=None,
    type=click.Path(exists=True),
    help="Extra CA certificate file/directory to trust (e.g. a TLS-inspecting proxy's CA).",
)
@click.option(
    "--ssl-certfile",
    envvar="EVENT_DASHBOARD_SSL_CERTFILE",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="PEM certificate (chain) to serve HTTPS. Requires --ssl-keyfile.",
)
@click.option(
    "--ssl-keyfile",
    envvar="EVENT_DASHBOARD_SSL_KEYFILE",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="PEM private key matching --ssl-certfile.",
)
@click.option(
    "--ssl-keyfile-password",
    envvar="EVENT_DASHBOARD_SSL_KEYFILE_PASSWORD",
    default=None,
    help="Password of an encrypted --ssl-keyfile (prefer the environment variable).",
)
@click.option(
    "--http-redirect-port",
    envvar="EVENT_DASHBOARD_HTTP_REDIRECT_PORT",
    default=80,
    type=click.IntRange(min=0, max=65535),
    show_default=True,
    help="With TLS: plain HTTP port that redirects to HTTPS (0 disables). Ignored without TLS.",
)
@click.option(
    "--log-level",
    envvar="EVENT_DASHBOARD_LOG_LEVEL",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    show_default=True,
)
def serve(
    host: str,
    port: int | None,
    config_path: str,
    fetch_timeout: int,
    cache_ttl: int,
    ca_bundle: str | None,
    ssl_certfile: str | None,
    ssl_keyfile: str | None,
    ssl_keyfile_password: str | None,
    http_redirect_port: int,
    log_level: str,
) -> None:
    """Start the web server (HTTPS when a certificate and key are given)."""
    logging.basicConfig(
        level=log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        store = config.ConfigStore(os.path.abspath(config_path))
    except config.ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        fetcher = calendar_fetch.CalendarFetcher(
            timeout=fetch_timeout, ttl=cache_ttl, ca_bundle=ca_bundle
        )
    except (OSError, ssl.SSLError) as exc:
        raise click.ClickException(f"Invalid CA bundle {ca_bundle}: {exc}") from exc
    tls_options = _tls_options(ssl_certfile, ssl_keyfile, ssl_keyfile_password)
    if port is None:
        port = 443 if tls_options else 80
    scheme = "https" if tls_options else "http"
    logger.info("Using config %s; serving on %s://%s:%d", store.path, scheme, host, port)
    if not tls_options and host not in LOCAL_HOSTS:
        logger.warning(
            "Serving plain HTTP on %s: settings and calendar URLs are sent unencrypted. "
            "Use --ssl-certfile/--ssl-keyfile to enable HTTPS.",
            host,
        )
    configs = [
        uvicorn.Config(
            app_module.create_app(store, fetcher),
            host=host,
            port=port,
            log_level="info",
            **tls_options,
        )
    ]
    if tls_options and http_redirect_port:
        if http_redirect_port == port:
            raise click.UsageError("--http-redirect-port must differ from --port.")
        configs.append(
            uvicorn.Config(
                redirect.create_redirect_app(port),
                host=host,
                port=http_redirect_port,
                log_level="info",
                lifespan="off",
            )
        )
        logger.info("Redirecting http://%s:%d to HTTPS", host, http_redirect_port)
    try:
        _run(configs)
    finally:
        fetcher.close()


if __name__ == "__main__":
    cli()
