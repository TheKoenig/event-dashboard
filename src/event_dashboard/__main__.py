"""Command line entry point for the event dashboard."""

from __future__ import annotations

import logging
import os
import ssl

import click
import dotenv
import uvicorn

from event_dashboard import app as app_module
from event_dashboard import calendar_fetch, config

logger = logging.getLogger("event_dashboard")


@click.group()
def cli() -> None:
    """Event dashboard: upcoming calendar events as progress bars."""
    dotenv.load_dotenv()


@cli.command()
@click.option("--host", envvar="EVENT_DASHBOARD_HOST", default="127.0.0.1", show_default=True)
@click.option("--port", envvar="EVENT_DASHBOARD_PORT", default=8000, type=int, show_default=True)
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
    default=15.0,
    type=click.FloatRange(min=1),
    show_default=True,
    help="HTTP timeout in seconds for calendar downloads.",
)
@click.option(
    "--cache-ttl",
    envvar="EVENT_DASHBOARD_CACHE_TTL",
    default=300.0,
    type=click.FloatRange(min=0),
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
    "--log-level",
    envvar="EVENT_DASHBOARD_LOG_LEVEL",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    show_default=True,
)
def serve(
    host: str,
    port: int,
    config_path: str,
    fetch_timeout: float,
    cache_ttl: float,
    ca_bundle: str | None,
    log_level: str,
) -> None:
    """Start the web server."""
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
    logger.info("Using config %s; serving on http://%s:%d", store.path, host, port)
    try:
        uvicorn.run(app_module.create_app(store, fetcher), host=host, port=port, log_level="info")
    finally:
        fetcher.close()


if __name__ == "__main__":
    cli()
