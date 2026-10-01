"""Tests for event parsing and filtering."""

import datetime

import pytest

from event_dashboard import events

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
WINDOW = datetime.timedelta(hours=2)


def test_upcoming_events_filters_and_sorts(sample_ics: bytes) -> None:
    result = events.upcoming_events(sample_ics, NOW, WINDOW, local_tz=UTC)
    assert [ev.title for ev in result] == [
        "Standup Berlin",
        "Weekly Sync",
        "Floating Time",
        "(no title)",
    ]
    standup = result[0]
    assert standup.start == datetime.datetime(2026, 10, 1, 8, 30, tzinfo=UTC)
    floating = result[2]
    assert floating.end - floating.start == datetime.timedelta(minutes=30)
    assert result[3].end == result[3].start


def test_window_is_inclusive(sample_ics: bytes) -> None:
    result = events.upcoming_events(sample_ics, NOW, datetime.timedelta(minutes=30), local_tz=UTC)
    assert [ev.title for ev in result] == ["Standup Berlin"]


def test_all_day_event_in_future_window(sample_ics: bytes) -> None:
    now = datetime.datetime(2026, 9, 30, 23, 0, tzinfo=UTC)
    result = events.upcoming_events(sample_ics, now, WINDOW, local_tz=UTC)
    all_day = [ev for ev in result if ev.title == "All Day Past Start"]
    assert len(all_day) == 1
    assert all_day[0].all_day
    assert all_day[0].to_dict()["start"] == "2026-10-01T00:00:00+00:00"


def test_progress_countdown() -> None:
    ev = events.Event("x", NOW + datetime.timedelta(minutes=30), NOW, all_day=False)
    assert ev.progress(NOW, WINDOW) == pytest.approx(0.75)
    assert ev.progress(NOW + datetime.timedelta(hours=1), WINDOW) == 1.0
    assert ev.progress(NOW - datetime.timedelta(hours=5), WINDOW) == 0.0


def test_invalid_ics_raises() -> None:
    with pytest.raises(events.ParseError):
        events.upcoming_events(b"this is not a calendar", NOW, WINDOW)


def test_naive_now_rejected(sample_ics: bytes) -> None:
    with pytest.raises(ValueError):
        events.upcoming_events(sample_ics, NOW.replace(tzinfo=None), WINDOW)


def test_keep_includes_recently_started(sample_ics: bytes) -> None:
    later = datetime.datetime(2026, 10, 1, 8, 33, tzinfo=UTC)  # standup started at 08:30
    without = events.upcoming_events(sample_ics, later, WINDOW, local_tz=UTC)
    assert "Standup Berlin" not in [ev.title for ev in without]
    kept = events.upcoming_events(
        sample_ics, later, WINDOW, local_tz=UTC, keep=datetime.timedelta(minutes=5)
    )
    assert kept[0].title == "Standup Berlin"
    expired = events.upcoming_events(
        sample_ics, later, WINDOW, local_tz=UTC, keep=datetime.timedelta(minutes=2)
    )
    assert "Standup Berlin" not in [ev.title for ev in expired]
