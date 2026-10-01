# Event Dashboard

A small web app that subscribes to one or more calendars (Outlook ICS links or Apple `webcal://`
links) and shows a countdown progress bar for every event **starting within an adjustable time
range** (default: 2 hours). Bars are grouped by calendar and use a color per calendar.

## Setup

```bash
uv sync
cp .env.example .env   # optional, adjust host/port/config path
uv run event-dashboard serve
```

Open <http://127.0.0.1:8000>, then click **⚙** to open the settings panel, where you can:

- set the time range in minutes (1–10080)
- add or remove calendars (name, ICS/webcal URL, color)

Settings are stored server-side in a JSON file (default `config.json`), so all viewers share them.

## How it works

- Each bar shows the event title and start date/time, plus a countdown.
- A bar fills from 0 % (the event starts at the far end of the range) to 100 % (the event starts now).
- Bars update in the browser every 5 s. Event data is reloaded every 60 s.
- Calendars are downloaded at most once per cache TTL (default 5 min). If a refresh fails, the last good copy is used.
- Repeating events (RRULE/EXDATE), time zones, all-day and floating events, and cancelled events are all handled.
- If a calendar fails to load or parse, the error is shown in that calendar's section.

## CLI options

```
uv run event-dashboard serve --help
```

| Option            | Env variable                     | Default       |
|-------------------|----------------------------------|---------------|
| `--host`          | `EVENT_DASHBOARD_HOST`           | `127.0.0.1`   |
| `--port`          | `EVENT_DASHBOARD_PORT`           | `8000`        |
| `--config`        | `EVENT_DASHBOARD_CONFIG`         | `config.json` |
| `--fetch-timeout` | `EVENT_DASHBOARD_FETCH_TIMEOUT`  | `15` s        |
| `--cache-ttl`     | `EVENT_DASHBOARD_CACHE_TTL`      | `300` s       |
| `--log-level`     | `EVENT_DASHBOARD_LOG_LEVEL`      | `INFO`        |

> **Security note:** the settings API has no authentication. Bind it to `127.0.0.1` or run it on a
> trusted network only. Calendar URLs often contain secret tokens and are visible in the settings.

## API

- `GET /api/events`: upcoming events grouped by calendar
- `GET /api/config` / `PUT /api/config`: read or replace the configuration

## Development

```bash
uv run ruff format . && uv run ruff check .
uv run pytest
```

## License

Released under the [MIT License](LICENSE).
