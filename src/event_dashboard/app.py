"""FastAPI application exposing the dashboard and its JSON API."""

from __future__ import annotations

import concurrent.futures
import datetime
import importlib.resources
import logging

import fastapi
import fastapi.responses
import fastapi.staticfiles

from event_dashboard import calendar_fetch, config, events

logger = logging.getLogger(__name__)

MAX_WORKERS = 8


def _calendar_payload(
    cal: config.CalendarConfig,
    fetcher: calendar_fetch.CalendarFetcher,
    now: datetime.datetime,
    window: datetime.timedelta,
    force: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": cal.id,
        "name": cal.name,
        "color": cal.color,
        "error": None,
        "events": [],
    }
    try:
        data = fetcher.fetch(cal.url, force=force)
        payload["events"] = [ev.to_dict() for ev in events.upcoming_events(data, now, window)]
    except (calendar_fetch.FetchError, events.ParseError) as exc:
        logger.warning("Calendar %r failed: %s", cal.name, exc)
        payload["error"] = str(exc)
    return payload


def create_app(
    store: config.ConfigStore, fetcher: calendar_fetch.CalendarFetcher
) -> fastapi.FastAPI:
    """Build the FastAPI application.

    Args:
        store: Configuration store.
        fetcher: Calendar fetcher with cache.

    Returns:
        Configured FastAPI app.
    """
    app = fastapi.FastAPI(title="Event Dashboard", docs_url=None, redoc_url=None)
    static_dir = importlib.resources.files("event_dashboard") / "static"

    @app.get("/api/config")
    def get_config() -> config.AppConfig:
        return store.get()

    @app.put("/api/config")
    def put_config(new_config: config.AppConfig) -> config.AppConfig:
        languages = config.available_languages()
        if new_config.language not in (config.AUTO_LANGUAGE, *languages):
            raise fastapi.HTTPException(
                status_code=422,
                detail=[
                    {
                        "loc": ["body", "language"],
                        "msg": f"Unsupported language; choose auto or one of {languages}",
                    }
                ],
            )
        return store.update(new_config)

    @app.get("/api/languages")
    def get_languages() -> list[str]:
        return config.available_languages()

    @app.get("/api/events")
    def get_events(refresh: bool = False) -> dict[str, object]:
        cfg = store.get()
        now = datetime.datetime.now(datetime.timezone.utc)
        window = datetime.timedelta(minutes=cfg.range_minutes)
        calendars: list[dict[str, object]] = []
        if refresh:
            logger.info(
                "Manual refresh requested; re-downloading %d calendar(s)", len(cfg.calendars)
            )
        if cfg.calendars:
            workers = min(MAX_WORKERS, len(cfg.calendars))
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                calendars = list(
                    pool.map(
                        lambda c: _calendar_payload(c, fetcher, now, window, force=refresh),
                        cfg.calendars,
                    )
                )
        return {
            "now": now.isoformat(),
            "title": cfg.title,
            "theme": cfg.theme,
            "language": cfg.language,
            "range_minutes": cfg.range_minutes,
            "calendars": calendars,
        }

    @app.get("/api/calendars/{calendar_id}/events")
    def get_calendar_events(calendar_id: str, refresh: bool = False) -> dict[str, object]:
        cfg = store.get()
        cal = next((c for c in cfg.calendars if c.id == calendar_id), None)
        if cal is None:
            raise fastapi.HTTPException(status_code=404, detail="Unknown calendar")
        if refresh:
            logger.info("Manual refresh requested for calendar %r", cal.name)
        now = datetime.datetime.now(datetime.timezone.utc)
        window = datetime.timedelta(minutes=cfg.range_minutes)
        return {
            "now": now.isoformat(),
            "range_minutes": cfg.range_minutes,
            "calendar": _calendar_payload(cal, fetcher, now, window, force=refresh),
        }

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> fastapi.responses.FileResponse:
        # Browsers request /favicon.ico by default; serve the SVG to avoid 404s.
        return fastapi.responses.FileResponse(
            str(static_dir / "favicon.svg"), media_type="image/svg+xml"
        )

    @app.get("/", include_in_schema=False)
    def index() -> fastapi.responses.FileResponse:
        return fastapi.responses.FileResponse(str(static_dir / "index.html"))

    app.mount("/static", fastapi.staticfiles.StaticFiles(directory=str(static_dir)), name="static")
    return app
