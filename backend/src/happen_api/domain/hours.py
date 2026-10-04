"""Provider-shaped hours normalized into one canonical weekly schedule.

One parser serves the historical scoring path and the live planner. SerpApi
sends hours as a weekday dictionary, a list of weekday dictionaries, or a list
of `{"day": ..., "hours": ...}` records, with 12-hour or 24-hour clock text,
split shifts, overnight closes, all-day listings, and explicit closed days.

Normalization never guesses. A weekday label or a time string that is not
recognized stays unknown, carries a structured reason, and keeps its original
text, so a localized or unusual listing lowers confidence instead of inventing
an interval.
"""

from __future__ import annotations

import re
from datetime import date, time, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from happen_api.domain.models import DayOfWeek

DAY_ALIASES = {
    "mon": DayOfWeek.monday,
    "monday": DayOfWeek.monday,
    "tue": DayOfWeek.tuesday,
    "tues": DayOfWeek.tuesday,
    "tuesday": DayOfWeek.tuesday,
    "wed": DayOfWeek.wednesday,
    "wednesday": DayOfWeek.wednesday,
    "thu": DayOfWeek.thursday,
    "thur": DayOfWeek.thursday,
    "thurs": DayOfWeek.thursday,
    "thursday": DayOfWeek.thursday,
    "fri": DayOfWeek.friday,
    "friday": DayOfWeek.friday,
    "sat": DayOfWeek.saturday,
    "saturday": DayOfWeek.saturday,
    "sun": DayOfWeek.sunday,
    "sunday": DayOfWeek.sunday,
}
_CLOCK = re.compile(
    r"^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>am|pm)?$",
    re.IGNORECASE,
)
_CLOSED_TEXT = {"closed"}
_ALL_DAY_TEXT = {"open 24 hours", "open 24 hrs", "24 hours"}
_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
_SPACES = "\u00a0\u202f\u2009\u2007"
_MAX_INTERVALS = 6

HOURS_MISSING = "hours_missing"
HOURS_SHAPE_UNRECOGNIZED = "hours_shape_unrecognized"
HOURS_DAY_LABEL_UNRECOGNIZED = "hours_day_label_unrecognized"
HOURS_DAY_VALUE_UNRECOGNIZED = "hours_day_value_unrecognized"
HOURS_CONTRADICTORY = "hours_contradictory"
HOURS_CLOSED = "hours_closed"
HOURS_UNPARSEABLE = "hours_unparseable"
HOURS_DAY_NOT_LISTED = "hours_day_not_listed"
HOURS_OUTSIDE_LISTED = "hours_outside_listed_hours"
HOURS_COVERS_ARRIVAL = "hours_covers_arrival"

HoursState = Literal["open", "closed", "unknown"]


class ScheduleInterval(BaseModel):
    """One canonical opening interval. Equal bounds mean the whole day."""

    model_config = ConfigDict(extra="forbid")

    opens_at: time
    closes_at: time

    @property
    def overnight(self) -> bool:
        """An interval that closes at or before it opens runs into the next day."""

        return self.closes_at <= self.opens_at


class DaySchedule(BaseModel):
    """What one weekday is known to be."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["open", "closed", "unknown"]
    intervals: list[ScheduleInterval] = Field(default_factory=list, max_length=_MAX_INTERVALS)
    reason_codes: list[str] = Field(default_factory=list, max_length=4)
    original_text: str | None = Field(default=None, max_length=200)


class ProviderHours(BaseModel):
    """The canonical weekly schedule plus the provider text it came from."""

    model_config = ConfigDict(extra="forbid")

    days: dict[DayOfWeek, DaySchedule] = Field(default_factory=dict)
    original_lines: list[str] = Field(default_factory=list, max_length=8)
    unrecognized: list[str] = Field(default_factory=list, max_length=8)
    reason_codes: list[str] = Field(default_factory=list, max_length=8)

    @property
    def listed(self) -> bool:
        """Whether the provider named any weekday at all."""

        return bool(self.days)


def normalize_hours(raw: object) -> ProviderHours:
    """Normalize provider hours into a canonical schedule, keeping the original text."""

    entries, shape_reason = _provider_entries(raw)
    hours = ProviderHours(reason_codes=[shape_reason] if shape_reason else [])
    for label, text in entries:
        day = DAY_ALIASES.get(_day_label(label))
        if day is None:
            hours.unrecognized.append(text[:200])
            _add_reason(hours, HOURS_DAY_LABEL_UNRECOGNIZED)
            continue
        status, ranges = parse_day_text(text)
        if status == "uncertain":
            hours.unrecognized.append(text[:200])
            _add_reason(hours, HOURS_DAY_VALUE_UNRECOGNIZED)
            hours.days[day] = DaySchedule(
                status="unknown",
                reason_codes=[HOURS_DAY_VALUE_UNRECOGNIZED],
                original_text=text[:200],
            )
            continue
        if status == "closed":
            hours.days[day] = DaySchedule(
                status="closed",
                reason_codes=[HOURS_CLOSED],
                original_text=text[:200],
            )
            continue
        schedule = DaySchedule(
            status="open",
            intervals=[
                ScheduleInterval(opens_at=opens, closes_at=closes) for opens, closes in ranges
            ],
            original_text=text[:200],
        )
        existing = hours.days.get(day)
        if existing is not None and existing != schedule:
            hours.days[day] = DaySchedule(
                status="unknown",
                reason_codes=[HOURS_CONTRADICTORY],
                original_text=text[:200],
            )
            _add_reason(hours, HOURS_CONTRADICTORY)
            continue
        hours.days[day] = schedule
    if not hours.days and not hours.unrecognized and not hours.reason_codes:
        hours.reason_codes = [HOURS_MISSING]
    return hours


def schedule_from_lines(lines: list[str]) -> ProviderHours:
    """Normalize display lines of the form `day: text` into the same schedule."""

    entries: list[dict[str, str]] = []
    for line in lines:
        label, separator, text = line.partition(":")
        if not separator:
            entries.append({"": line})
            continue
        entries.append({label: text})
    return normalize_hours(entries)


def hours_state(
    hours: ProviderHours | None,
    *,
    local_date: date,
    arrival: time,
) -> HoursState:
    """Return open, closed, or unknown for one destination-local arrival.

    Coverage from the previous day counts because an overnight interval opens on
    the day it lists and closes after midnight.
    """

    if hours is None or not hours.days:
        return "unknown"
    if _covers_from_previous_day(hours, local_date, arrival):
        return "open"
    day = _weekday(local_date)
    if day not in hours.days:
        # Text that could not be normalized is not evidence of closure.
        return "unknown" if hours.unrecognized else "closed"
    schedule = hours.days[day]
    if schedule.status == "unknown":
        return "unknown"
    if schedule.status == "closed":
        return "closed"
    for interval in schedule.intervals:
        if interval.overnight:
            if arrival >= interval.opens_at:
                return "open"
            continue
        if interval.opens_at <= arrival < interval.closes_at:
            return "open"
    return "closed"


def hours_reason(
    hours: ProviderHours | None,
    *,
    local_date: date,
    arrival: time,
) -> str:
    """Return the structured reason behind one hours decision."""

    if hours is None or not hours.days:
        return hours.reason_codes[0] if hours is not None and hours.reason_codes else HOURS_MISSING
    if hours_state(hours, local_date=local_date, arrival=arrival) == "open":
        return HOURS_COVERS_ARRIVAL
    day = _weekday(local_date)
    schedule = hours.days.get(day)
    if schedule is None:
        if hours.unrecognized or not hours.listed:
            return hours.reason_codes[0] if hours.reason_codes else HOURS_MISSING
        return HOURS_DAY_NOT_LISTED
    if schedule.reason_codes:
        return schedule.reason_codes[0]
    if schedule.status == "closed":
        return HOURS_CLOSED
    return HOURS_OUTSIDE_LISTED


def day_intervals(
    hours: ProviderHours | None,
    local_date: date,
) -> list[ScheduleInterval]:
    """Return the canonical intervals listed for one local date."""

    if hours is None:
        return []
    schedule = hours.days.get(_weekday(local_date))
    if schedule is None or schedule.status != "open":
        return []
    return list(schedule.intervals)


def parse_day_text(text: str) -> tuple[str, list[tuple[time, time]]]:
    """Return closed, open, or uncertain for one weekday's provider text."""

    cleaned = _flatten(text)
    lowered = lowered_day_text(cleaned)
    if lowered in _CLOSED_TEXT:
        return "closed", []
    if lowered in _ALL_DAY_TEXT:
        return "open", [(time(0, 0), time(0, 0))]
    ranges: list[tuple[time, time]] = []
    for part in [piece.strip() for piece in cleaned.split(",") if piece.strip()]:
        parsed = parse_range(part)
        if parsed is None:
            return "uncertain", []
        ranges.append(parsed)
    if not ranges:
        return "uncertain", []
    return "open", ranges


def lowered_day_text(text: str) -> str:
    """Casefold one weekday's text and drop a trailing full stop."""

    return _flatten(text).casefold().rstrip(".")


def parse_range(part: str) -> tuple[time, time] | None:
    """Read one `open - close` interval, spaced or not."""

    pieces = re.split(r"\s+-\s+|\s+to\s+", part, maxsplit=1, flags=re.IGNORECASE)
    if len(pieces) != 2:
        pieces = part.split("-", maxsplit=1)
        if len(pieces) != 2:
            return None
    start = parse_clock(pieces[0])
    end = parse_clock(pieces[1])
    if start is None or end is None:
        return None
    return _resolve_clocks(start, end)


def parse_clock(token: str) -> tuple[int, int, str | None] | None:
    """Read one clock token, with or without a meridiem."""

    match = _CLOCK.fullmatch(token.strip())
    if match is None:
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    meridiem = match.group("meridiem")
    if minute > 59:
        return None
    if meridiem is not None:
        if not 1 <= hour <= 12:
            return None
        return hour, minute, meridiem.lower()
    if hour > 24 or (hour == 24 and minute != 0):
        return None
    return hour, minute, None


def twenty_four(hour: int, minute: int, *, allow_midnight_end: bool) -> time | None:
    """Read a 24-hour clock value, allowing 24:00 only as a closing bound."""

    if hour == 24:
        if allow_midnight_end and minute == 0:
            return time(0, 0)
        return None
    if hour > 23:
        return None
    return time(hour, minute)


def apply_meridiem(hour: int, minute: int, meridiem: str) -> time:
    """Apply am or pm to a 12-hour clock value."""

    base = 0 if hour == 12 else hour
    if meridiem == "pm":
        base += 12
    return time(base, minute)


def _provider_entries(raw: object) -> tuple[list[tuple[str, str]], str | None]:
    """Read the provider shapes already observed, without inventing a shape."""

    if isinstance(raw, dict):
        if _text(raw.get("hours")) or isinstance(raw.get("hours"), (dict, list)):
            # A record that wraps the hours under their own key is read one level in.
            return _provider_entries(raw["hours"])
        return [_split_label(label, value) for label, value in raw.items() if _text(value)], None
    if isinstance(raw, list):
        entries: list[tuple[str, str]] = []
        reason: str | None = None
        for item in raw:
            if isinstance(item, str):
                if _text(item):
                    entries.append(_split_label("", item))
                continue
            if not isinstance(item, dict):
                reason = reason or HOURS_SHAPE_UNRECOGNIZED
                continue
            day = item.get("day")
            text = item.get("hours")
            if isinstance(day, str) and isinstance(text, str):
                entries.append(_split_label(day, text))
                continue
            if len(item) == 1:
                label, value = next(iter(item.items()))
                if _text(value):
                    entries.append(_split_label(label, value))
                    continue
            reason = reason or HOURS_SHAPE_UNRECOGNIZED
        return entries, reason
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return [], None
    if isinstance(raw, (list, dict)) and not raw:
        return [], None
    return [], HOURS_SHAPE_UNRECOGNIZED


def _split_label(label: object, value: object) -> tuple[str, str]:
    """Read one weekday and its text, including a combined `day: text` string."""

    day = label.strip() if isinstance(label, str) else ""
    text = value.strip() if isinstance(value, str) else ""
    prefix, separator, rest = text.partition(":")
    if day and DAY_ALIASES.get(_day_label(day)) is not None:
        return day, text
    if separator and _text(rest) and DAY_ALIASES.get(_day_label(prefix)) is not None:
        return prefix.strip(), rest.strip()
    return day, text


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _covers_from_previous_day(
    hours: ProviderHours,
    local_date: date,
    arrival: time,
) -> bool:
    previous = hours.days.get(_weekday(local_date - timedelta(days=1)))
    if previous is None or previous.status != "open":
        return False
    return any(
        interval.overnight and arrival < interval.closes_at for interval in previous.intervals
    )


def _weekday(value: date) -> DayOfWeek:
    return DayOfWeek(value.strftime("%A").lower())


def _day_label(value: str) -> str:
    return _flatten(value).casefold().rstrip(".")


def _flatten(value: str) -> str:
    """Normalize dashes, spaces, and width so one separator compares equal."""

    text = value
    for dash in _DASHES:
        text = text.replace(dash, "-")
    for space in _SPACES:
        text = text.replace(space, " ")
    return " ".join(text.split())


def _add_reason(hours: ProviderHours, reason: str) -> None:
    if reason not in hours.reason_codes and len(hours.reason_codes) < 8:
        hours.reason_codes.append(reason)


def _resolve_clocks(
    start: tuple[int, int, str | None],
    end: tuple[int, int, str | None],
) -> tuple[time, time] | None:
    start_hour, start_minute, start_meridiem = start
    end_hour, end_minute, end_meridiem = end
    if start_meridiem is not None and end_meridiem is not None:
        return (
            apply_meridiem(start_hour, start_minute, start_meridiem),
            apply_meridiem(end_hour, end_minute, end_meridiem),
        )
    if start_meridiem is None and end_meridiem is None:
        start_time = twenty_four(start_hour, start_minute, allow_midnight_end=False)
        end_time = twenty_four(end_hour, end_minute, allow_midnight_end=True)
        if start_time is None or end_time is None:
            return None
        return start_time, end_time
    if start_meridiem is None and end_meridiem is not None:
        start_time = apply_meridiem(start_hour, start_minute, end_meridiem)
        end_time = apply_meridiem(end_hour, end_minute, end_meridiem)
        if _minutes(start_time) >= _minutes(end_time):
            start_time = _from_minutes(_minutes(start_time) - 12 * 60)
        return start_time, end_time
    start_time = apply_meridiem(start_hour, start_minute, start_meridiem or "am")
    same = apply_meridiem(end_hour, end_minute, start_meridiem or "am")
    if _minutes(same) > _minutes(start_time):
        return start_time, same
    opposite = "am" if start_meridiem == "pm" else "pm"
    return start_time, apply_meridiem(end_hour, end_minute, opposite)


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _from_minutes(minutes: int) -> time:
    wrapped = minutes % (24 * 60)
    return time(wrapped // 60, wrapped % 60)
