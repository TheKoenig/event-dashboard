"""Tests for the FastAPI application."""

import datetime
import pathlib

import fastapi.testclient
import httpx
import pytest
import respx

from event_dashboard import app as app_module
from event_dashboard import calendar_fetch, config


def _ics_starting_in(minutes: int) -> bytes:
    start = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
    stamp = start.strftime("%Y%m%dT%H%M%SZ")
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//t//EN\r\n"
        f"BEGIN:VEVENT\r\nUID:a@t\r\nSUMMARY:Soon\r\nDTSTART:{stamp}\r\nDTEND:{stamp}\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode()


@pytest.fixture
def client(tmp_path: pathlib.Path) -> fastapi.testclient.TestClient:
    store = config.ConfigStore(tmp_path / "config.json")
    fetcher = calendar_fetch.CalendarFetcher(ttl=0)
    return fastapi.testclient.TestClient(app_module.create_app(store, fetcher))


@pytest.fixture
def cached_client(tmp_path: pathlib.Path) -> fastapi.testclient.TestClient:
    store = config.ConfigStore(tmp_path / "config.json")
    fetcher = calendar_fetch.CalendarFetcher(ttl=300)
    return fastapi.testclient.TestClient(app_module.create_app(store, fetcher))


def test_index_and_static(client: fastapi.testclient.TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "settings-toggle" in resp.text
    assert client.get("/static/app.js").status_code == 200


def test_config_roundtrip(client: fastapi.testclient.TestClient) -> None:
    assert client.get("/api/config").json() == {
        "title": "Upcoming events",
        "theme": "auto",
        "language": "auto",
        "range_minutes": 120,
        "calendars": [],
    }
    body = {
        "title": "Team Board",
        "theme": "dark",
        "language": "DE",
        "range_minutes": 30,
        "calendars": [{"name": "Work", "url": "https://example.com/a.ics", "color": "#123456"}],
    }
    resp = client.put("/api/config", json=body)
    assert resp.status_code == 200
    saved = resp.json()
    assert saved["range_minutes"] == 30
    assert saved["title"] == "Team Board"
    assert saved["theme"] == "dark"
    assert saved["language"] == "de"
    assert saved["calendars"][0]["id"]
    assert client.get("/api/config").json() == saved


@pytest.mark.parametrize(
    "body",
    [
        {"range_minutes": 0, "calendars": []},
        {"theme": "purple"},
        {"title": "x" * 101},
        {"language": "xx"},
        {"language": "../etc/passwd"},
    ],
)
def test_config_validation(client: fastapi.testclient.TestClient, body: dict) -> None:
    resp = client.put("/api/config", json=body)
    assert resp.status_code == 422


def test_events_empty(client: fastapi.testclient.TestClient) -> None:
    data = client.get("/api/events").json()
    assert data["calendars"] == []
    assert data["range_minutes"] == 120
    assert data["title"] == "Upcoming events"
    assert data["theme"] == "auto"
    assert data["language"] == "auto"


@respx.mock
def test_events_grouped(client: fastapi.testclient.TestClient, respx_mock: respx.Router) -> None:
    respx_mock.get("https://ok.example/a.ics").mock(
        return_value=httpx.Response(200, content=_ics_starting_in(10))
    )
    respx_mock.get("https://bad.example/b.ics").mock(return_value=httpx.Response(500))
    respx_mock.get("https://junk.example/c.ics").mock(
        return_value=httpx.Response(200, content=b"junk")
    )
    client.put(
        "/api/config",
        json={
            "range_minutes": 60,
            "calendars": [
                {"name": "Ok", "url": "webcal://ok.example/a.ics", "color": "#00ff00"},
                {"name": "Bad", "url": "https://bad.example/b.ics", "color": "#ff0000"},
                {"name": "Junk", "url": "https://junk.example/c.ics", "color": "#0000ff"},
            ],
        },
    )
    data = client.get("/api/events").json()
    ok, bad, junk = data["calendars"]
    assert ok["color"] == "#00ff00"
    assert [ev["title"] for ev in ok["events"]] == ["Soon"]
    assert ok["error"] is None
    assert "HTTP 500" in bad["error"]
    assert junk["error"]


def test_languages(client: fastapi.testclient.TestClient) -> None:
    langs = client.get("/api/languages").json()
    assert {"de", "en"} <= set(langs)
    assert langs == sorted(langs)
    for lang in langs:
        assert client.get(f"/static/locales/{lang}.json").status_code == 200


@respx.mock
def test_manual_refresh_bypasses_cache(
    cached_client: fastapi.testclient.TestClient, respx_mock: respx.Router
) -> None:
    route = respx_mock.get("https://cal.example/a.ics")
    route.side_effect = [
        httpx.Response(200, content=_ics_starting_in(10)),
        httpx.Response(200, content=_ics_starting_in(20).replace(b"Soon", b"Added later")),
    ]
    cached_client.put(
        "/api/config",
        json={"calendars": [{"name": "C", "url": "https://cal.example/a.ics"}]},
    )

    def titles(url: str) -> list[str]:
        return [ev["title"] for ev in cached_client.get(url).json()["calendars"][0]["events"]]

    assert titles("/api/events") == ["Soon"]
    assert titles("/api/events") == ["Soon"]
    assert route.call_count == 1
    assert titles("/api/events?refresh=true") == ["Added later"]
    assert route.call_count == 2


def test_favicon(client: fastapi.testclient.TestClient) -> None:
    assert 'rel="icon" href="/static/favicon.svg"' in client.get("/").text
    for url in ("/static/favicon.svg", "/favicon.ico"):
        resp = client.get(url)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/svg+xml")
        assert resp.text.lstrip().startswith("<svg")
