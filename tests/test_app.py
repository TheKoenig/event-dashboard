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


def test_index_and_static(client: fastapi.testclient.TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "settings-toggle" in resp.text
    assert client.get("/static/app.js").status_code == 200


def test_config_roundtrip(client: fastapi.testclient.TestClient) -> None:
    assert client.get("/api/config").json() == {"range_minutes": 120, "calendars": []}
    body = {
        "range_minutes": 30,
        "calendars": [{"name": "Work", "url": "https://example.com/a.ics", "color": "#123456"}],
    }
    resp = client.put("/api/config", json=body)
    assert resp.status_code == 200
    saved = resp.json()
    assert saved["range_minutes"] == 30
    assert saved["calendars"][0]["id"]
    assert client.get("/api/config").json() == saved


def test_config_validation(client: fastapi.testclient.TestClient) -> None:
    resp = client.put("/api/config", json={"range_minutes": 0, "calendars": []})
    assert resp.status_code == 422


def test_events_empty(client: fastapi.testclient.TestClient) -> None:
    data = client.get("/api/events").json()
    assert data["calendars"] == []
    assert data["range_minutes"] == 120


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
