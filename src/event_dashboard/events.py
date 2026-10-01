"""Parsing of ICS data into upcoming events."""

from __future__ import annotations

import dataclasses
import datetime
import logging

import icalendar
import recurring_ical_events

logger = logging.getLogger(__name__)


class ParseError(Exception):
    """Raised when ICS data cannot be parsed."""


@dataclasses.dataclass(frozen=True)
class Event:
    """An upcoming calendar event.

    Attributes:
        title: Event summary.
        start: Timezone-aware start time.
        end: Timezone-aware end time.
        all_day: Whether the event is an all-day event.
    """

    title: str
    start: datetime.datetime
    end: datetime.datetime
    all_day: bool

    def progress(self, now: datetime.datetime, window: datetime.timedelta) -> float:
        """Return countdown progress in ``[0, 1]``; 1 means the event starts now.

        Args:
            now: Current timezone-aware time.
            window: Look-ahead window.

        Returns:
            Fraction of the window that has elapsed relative to the event start.
        """
        remaining = (self.start - now) / window
        return max(0.0, min(1.0, 1.0 - remaining))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "title": self.title,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "all_day": self.all_day,
        }


def _to_aware(
    value: datetime.date | datetime.datetime, local_tz: datetime.tzinfo
) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value if value.tzinfo else value.replace(tzinfo=local_tz)
    return datetime.datetime.combine(value, datetime.time.min, tzinfo=local_tz)


def _local_tz() -> datetime.tzinfo:
    tz = datetime.datetime.now().astimezone().tzinfo
    return tz or datetime.timezone.utc


def upcoming_events(
    ics: bytes | str,
    now: datetime.datetime,
    window: datetime.timedelta,
    local_tz: datetime.tzinfo | None = None,
) -> list[Event]:
    """Return events starting within ``[now, now + window]``, sorted by start.

    Recurring events are expanded. Floating and all-day times are interpreted in ``local_tz``.

    Args:
        ics: Raw ICS calendar data.
        now: Current timezone-aware time.
        window: Look-ahead window.
        local_tz: Timezone for floating/all-day times (defaults to system local timezone).

    Returns:
        Sorted list of upcoming events.

    Raises:
        ParseError: If the data is not a valid calendar.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local_tz = local_tz or _local_tz()
    try:
        calendar = icalendar.Calendar.from_ical(ics)
    except (ValueError, IndexError, KeyError) as exc:
        raise ParseError(f"Invalid ICS data: {exc}") from exc
    end = now + window
    # Query with a margin so floating/all-day events in other offsets are not missed.
    margin = datetime.timedelta(days=1)
    try:
        components = recurring_ical_events.of(calendar).between(now - margin, end + margin)
    except Exception as exc:  # library raises a variety of errors on broken data
        raise ParseError(f"Could not expand events: {exc}") from exc

    events: list[Event] = []
    for component in components:
        if component.name != "VEVENT":
            continue
        if str(component.get("STATUS", "")).upper() == "CANCELLED":
            continue
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue
        raw_start = dtstart.dt
        all_day = not isinstance(raw_start, datetime.datetime)
        start = _to_aware(raw_start, local_tz)
        dtend = component.get("DTEND")
        if dtend is not None:
            finish = _to_aware(dtend.dt, local_tz)
        elif component.get("DURATION") is not None:
            finish = start + component.get("DURATION").dt
        else:
            finish = start + (datetime.timedelta(days=1) if all_day else datetime.timedelta(0))
        if not now <= start <= end:
            continue
        title = str(component.get("SUMMARY", "")).strip() or "(no title)"
        events.append(Event(title=title, start=start, end=finish, all_day=all_day))
    events.sort(key=lambda event: (event.start, event.title))
    return events
