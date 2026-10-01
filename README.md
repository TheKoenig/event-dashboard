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

Open <http://127.0.0.1> (or <https://127.0.0.1> with TLS), then click **⚙** to open the settings panel, where you can:

- set the page title (shown in the header and browser tab)
- pick a theme: **Auto** (follows the OS light/dark setting), **Light** or **Dark**
- pick a language: **Auto (browser)** (default) or a specific language
- set the time range in minutes (1–10080)
- add or remove calendars (name, ICS/webcal URL, color)

Settings are stored server-side in a JSON file (default `config.json`), so all viewers share them.

## How it works

- Each bar shows the event title and start date/time, plus a countdown.
- A bar fills from 0 % (the event starts at the far end of the range) to 100 % (the event starts now).
- Bars update in the browser every 5 s. Event data is reloaded every 60 s.
- Calendars are downloaded at most once per cache TTL (default 1 h). If a refresh fails, the last good copy is used.
- The **reload** button next to ⚙ downloads all calendars immediately, bypassing the cache (useful right
  after adding an event). Its hover text shows when the data was last updated.
- Each calendar card also has its own small reload button that downloads only that calendar.
- Repeating events (RRULE/EXDATE), time zones, all-day and floating events, and cancelled events are all handled.
- If a calendar fails to load or parse, the error is shown in that calendar's section.

## Language

By default the page uses the browser's language. A fixed language can be selected in the settings;
it applies to all viewers. Translations live in `src/event_dashboard/static/locales/<lang>.json`
(currently `en` and `de`), and the language list in the settings is built from these files. If no
translation matches, the page falls back to English. Dates and times follow the browser locale on
**Auto**, and the selected language otherwise.

To add a language, copy `en.json` to e.g. `fr.json` and translate the values. Keep the keys and the
`{placeholders}` unchanged; `tests/test_locales.py` checks this.

Error messages from the server (validation and fetch errors) stay in English.

## CLI options

```
uv run event-dashboard serve --help
```

| Option            | Env variable                     | Default       |
|-------------------|----------------------------------|---------------|
| `--host`          | `EVENT_DASHBOARD_HOST`           | `127.0.0.1`   |
| `--port`          | `EVENT_DASHBOARD_PORT`           | `443` with TLS, else `80` |
| `--http-redirect-port` | `EVENT_DASHBOARD_HTTP_REDIRECT_PORT` | `80` (TLS only, `0` = off) |
| `--config`        | `EVENT_DASHBOARD_CONFIG`         | `config.json` |
| `--fetch-timeout` | `EVENT_DASHBOARD_FETCH_TIMEOUT`  | `15` s (min 3 s) |
| `--cache-ttl`     | `EVENT_DASHBOARD_CACHE_TTL`      | `3600` s (1 h, min 120 s) |
| `--ca-bundle`     | `EVENT_DASHBOARD_CA_BUNDLE`      | none          |
| `--ssl-certfile`  | `EVENT_DASHBOARD_SSL_CERTFILE`   | none (HTTP)   |
| `--ssl-keyfile`   | `EVENT_DASHBOARD_SSL_KEYFILE`    | none          |
| `--ssl-keyfile-password` | `EVENT_DASHBOARD_SSL_KEYFILE_PASSWORD` | none |
| `--log-level`     | `EVENT_DASHBOARD_LOG_LEVEL`      | `INFO`        |

### HTTPS for the dashboard

By default the dashboard is served over plain HTTP. That is fine on `127.0.0.1`, but on a network
the API traffic (including calendar URLs with secret tokens) would be unencrypted. To serve HTTPS,
pass a PEM certificate and its private key:

```bash
event-dashboard serve --host 0.0.0.0 --ssl-certfile cert.pem --ssl-keyfile key.pem
```

With TLS the server listens on 443 and redirects plain HTTP from port 80 (`--http-redirect-port`,
`0` disables it) with a `308` to HTTPS. Ports below 1024 need root or
`sudo setcap 'cap_net_bind_service=+ep' "$(readlink -f .venv/bin/python)"`; otherwise pick
ports ≥ 1024, e.g. `--port 8443 --http-redirect-port 8080`.

Both files are required and are checked at startup. For an encrypted key, set
`EVENT_DASHBOARD_SSL_KEYFILE_PASSWORD` (preferred over the CLI option, which shows up in the process
list). A self-signed certificate for testing:

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj /CN=localhost \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" -keyout key.pem -out cert.pem
```

Browsers warn about self-signed certificates; use one from your company or public CA for real use.
A warning is logged when the server listens on a non-local address without TLS.

### Corporate proxies and TLS certificates

HTTPS downloads trust the certifi bundle **and** the operating system's CA bundle
(e.g. `/etc/ssl/certs/ca-certificates.crt`), plus `SSL_CERT_FILE` / `SSL_CERT_DIR` if set. This means
a TLS-inspecting company proxy works out of the box when its CA is installed system-wide. Proxy
settings are taken from `HTTP(S)_PROXY` / `NO_PROXY`.

If a calendar shows *"TLS certificate not trusted"*, point `--ca-bundle` (or
`EVENT_DASHBOARD_CA_BUNDLE`) to a PEM file or directory containing the proxy's CA certificate.

> **Security note:** the settings API has no authentication (TLS encrypts but does not restrict
> access). Bind it to `127.0.0.1` or run it on a trusted network only. Calendar URLs often contain secret tokens and are visible in the settings.

## API

- `GET /api/events`: upcoming events grouped by calendar (`?refresh=true` bypasses the cache)
- `GET /api/calendars/{id}/events`: events of a single calendar (`?refresh=true` re-downloads only that one)
- `GET /api/config` / `PUT /api/config`: read or replace the configuration
- `GET /api/languages`: available UI translations

## Development

```bash
uv run ruff format . && uv run ruff check .
uv run pytest
```

## License

Released under the [MIT License](LICENSE).
