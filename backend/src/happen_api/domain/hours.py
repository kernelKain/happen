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
from dataclasses import dataclass
from datetime import date, time, timedelta
from enum import StrEnum
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
_DAY_PATTERN = "|".join(sorted(DAY_ALIASES, key=len, reverse=True))
_CLOCK = re.compile(
    r"^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>am|pm)?$",
    re.IGNORECASE,
)
_DAY_TOKEN = re.compile(rf"(?i)\b(?:{_DAY_PATTERN})\b\.?")
_SENTENCE_BREAK = re.compile(r"(?i)(?:[.;!?]|\bor\b|\balso\b|\bbut\b|\bthrough\b)")
_CONNECTIVE_BREAK = re.compile(r"(?i)(?:,|\bthen\b|&|/)")
_CLOSED_WORD = re.compile(r"(?i)\b(?:closed|shut)\b")
_ALL_DAY_CLAIM = re.compile(r"(?i)\b(?:24\s*(?:hours|hrs)|open\s+24)\b")
# One clock range, either side of it complete with an hours cue.
_RANGE = (
    r"(?P<open>\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:-|\\u2013|\\u2014|\\u2212|to)\s*"
    r"(?P<close>\d{1,2}(?::\d{2})?\s*(?:am|pm)?)"
)
# The range is only read as hours once the clause says it is talking about them.
_CUED_RANGE = re.compile(rf"(?i)\b(?:open(?:s|ing)?|hours?|from)\b[^0-9]{{0,12}}?{_RANGE}")
# An opening time with no closing bound, such as "opens at 6pm".
_OPEN_CUE = re.compile(
    r"(?i)\b(?:open(?:s|ing)?|hours?|from)\b[^0-9]{0,12}?"
    r"(?P<open>\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b"
)
# Words that say the clause is talking about opening times at all.
_HOURS_CUE = re.compile(r"(?i)\b(?:open|opens|opening|close|closes|closing|closed|shut|hours?)\b")
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


class HoursVerdict(StrEnum):
    """How two hours claims about the same weekday compare.

    Only `conflict` may accuse a place of being wrong. Agreement proves
    nothing extra and is never surfaced as a disagreement. `unverifiable`
    means the text could not be aligned, which leaves the claim unverified.
    """

    agreement = "agreement"
    conflict = "conflict"
    unverifiable = "unverifiable"


class ScheduleInterval(BaseModel):
    """One canonical opening interval. Equal bounds mean the whole day."""

    model_config = ConfigDict(extra="forbid")

    opens_at: time
    closes_at: time

    @property
    def overnight(self) -> bool:
        """An interval that closes at or before it opens runs into the next day."""

        return self.closes_at <= self.opens_at


_ALL_DAY_INTERVAL = ScheduleInterval(opens_at=time(0, 0), closes_at=time(0, 0))


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


def reconcile_hours(recorded: ProviderHours, statement: str) -> HoursVerdict:
    """Compare one free-text hours statement with a normalized weekly schedule.

    Two claims about the same weekday conflict only when they are provably
    incompatible: a weekday recorded open that the statement calls closed, or
    opening intervals that cannot both cover that weekday. Agreement is
    agreement, never a conflict, so it never raises a warning.

    Text that cannot be reliably aligned is not evidence either way. A clause
    that names no weekday, names no hours, or gives only one end of an interval
    all return `unverifiable`, which leaves the claim unverified rather than
    accusing the place of being wrong.
    """

    verdicts: list[HoursVerdict] = []
    for day, clause in _day_clauses(statement):
        claimed = _claimed_day(clause)
        if claimed is None:
            continue
        schedule = recorded.days.get(day)
        if schedule is None and recorded.unrecognized:
            # The listing could not be read, so there is nothing to compare to.
            continue
        verdicts.append(_compare_day(schedule, claimed))
    if HoursVerdict.conflict in verdicts:
        return HoursVerdict.conflict
    if HoursVerdict.agreement in verdicts:
        return HoursVerdict.agreement
    return HoursVerdict.unverifiable


def _compare_day(schedule: DaySchedule | None, claimed: _ClaimedDay) -> HoursVerdict:
    """Return whether one weekday's two claims can both be true."""

    if schedule is None:
        # The listing never named this weekday, so there is nothing to disagree
        # with. A closure agrees with silence; an opening does not follow from it.
        return HoursVerdict.agreement if claimed.closed else HoursVerdict.unverifiable
    if schedule.status == "unknown":
        # Unreadable provider text is not evidence of closure.
        return HoursVerdict.unverifiable
    if claimed.closed:
        return HoursVerdict.agreement if schedule.status == "closed" else HoursVerdict.conflict
    if schedule.status == "closed":
        return HoursVerdict.conflict
    if claimed.opens_early:
        return HoursVerdict.unverifiable
    if not claimed.intervals or not schedule.intervals:
        return HoursVerdict.unverifiable
    if any(
        _overlaps(claimed_interval, listed_interval)
        for claimed_interval in claimed.intervals
        for listed_interval in schedule.intervals
    ):
        return HoursVerdict.agreement
    return HoursVerdict.conflict


def _overlaps(claimed: ScheduleInterval, listed: ScheduleInterval) -> bool:
    """Whether two canonical intervals can both cover some time on one day.

    An interval that closes at or before it opens runs into the next day, so it
    covers both its own evening and the small hours that follow, which is how
    every other hours decision in this module already reads it.
    """

    if claimed.overnight or listed.overnight:
        # Two overnight windows, or one overnight and one same-day window, always
        # share the small hours after midnight.
        return (
            _spans_midnight(claimed)
            or _spans_midnight(listed)
            or _night_start(claimed) < _night_end(listed)
        )
    return claimed.opens_at < listed.closes_at and listed.opens_at < claimed.closes_at


def _spans_midnight(interval: ScheduleInterval) -> bool:
    return interval.overnight


def _night_start(interval: ScheduleInterval) -> time:
    """The moment an interval first reaches into the small hours."""

    return interval.closes_at


def _night_end(interval: ScheduleInterval) -> time:
    """The moment an interval stops reaching into the small hours."""

    return interval.opens_at if interval.overnight else time(0, 0)


@dataclass(frozen=True)
class _ClaimedDay:
    """What one clause asserts about one named weekday."""

    closed: bool
    intervals: tuple[ScheduleInterval, ...] = ()
    # A clause such as "opens at 6pm" states an opening without a closing bound.
    # That is too little to compare two open schedules, but it is already
    # enough to contradict a weekday the record lists as closed.
    opens_early: bool = False


def _day_clauses(text: str) -> list[tuple[DayOfWeek, str]]:
    """Return each named weekday with the clause that states something about it.

    A clause boundary is a sentence mark or a comma, or a connective such as
    `and`. `on` and `at` are not boundaries, because they sit between a weekday
    and its own hours, and "closed on Monday" must not lose the word `closed`.
    """

    found: list[tuple[DayOfWeek, str]] = []
    inherited: tuple[DayOfWeek, str] | None = None
    for sentence in _SENTENCE_BREAK.split(_flatten(text)):
        # The inherited clause is carried into the first piece of the next
        # sentence, so "closed on Monday. It is shut on Tuesday" is read the same
        # as "closed on Monday and Tuesday".
        for index, piece in enumerate(_CONNECTIVE_BREAK.split(sentence)):
            days = _days_named(piece)
            if not days:
                # A bare connective keeps the hours of the clause before it, so
                # "closed Monday and Tuesday" describes Tuesday as well.
                if piece and _is_bare_connector(piece) and inherited is not None:
                    found.append((inherited[0], f"{inherited[1]} {piece}"))
                continue
            text = piece if index or inherited is None else f"{inherited[1]} {piece}"
            for day in days:
                if any(item[0] is day for item in found):
                    continue
                found.append((day, text))
                inherited = (day, text)
    return [(day, clause) for day, clause in found if _stated_hours(clause)]


def _days_named(piece: str) -> list[DayOfWeek]:
    """Return every weekday a piece names, longest label first."""

    named: list[DayOfWeek] = []
    for match in _DAY_TOKEN.finditer(piece):
        label = match.group(0).casefold().rstrip(".")
        day = DAY_ALIASES.get(label)
        if day is not None and day not in named:
            named.append(day)
    return named


def _is_bare_connector(piece: str) -> bool:
    """Whether a piece only joins two clauses and asserts nothing itself."""

    return piece.strip(" ,.-").casefold() in {"and", "or", "also", "but", "then", "to", "&", "/"}


def _stated_hours(clause: str) -> bool:
    """Whether a clause asserts hours, rather than only naming a day."""

    body = _DAY_TOKEN.sub(" ", clause).strip(" ,.-")
    if _CLOSED_WORD.search(body) or _ALL_DAY_CLAIM.search(body):
        return True
    return _HOURS_CUE.search(body) is not None


def _claimed_day(clause: str) -> _ClaimedDay | None:
    """Read one clause about one weekday, or None when it states no hours.

    A closure is a complete claim. An opening interval is a claim only when the
    clause carries an hours cue, because half an interval cannot be shown to
    disagree with a full one, and because a bare clock time is usually a
    visitor's own visit rather than the opening hours.
    """

    body = _DAY_TOKEN.sub(" ", clause).strip(" ,.-")
    if _CLOSED_WORD.search(body):
        return _ClaimedDay(closed=True)
    if _ALL_DAY_CLAIM.search(body):
        return _ClaimedDay(closed=False, intervals=(_ALL_DAY_INTERVAL,))
    found = _CUED_RANGE.search(body)
    if found is None:
        return _open_without_close(body)
    opens = parse_clock(found.group(1))
    closes = parse_clock(found.group(2))
    if opens is None or closes is None:
        return None
    resolved = _resolve_clocks(opens, closes)
    if resolved is None:
        return None
    return _ClaimedDay(
        closed=False,
        intervals=(ScheduleInterval(opens_at=resolved[0], closes_at=resolved[1]),),
    )


def _open_without_close(body: str) -> _ClaimedDay | None:
    """Read an opening time that carries no closing bound, or None."""

    found = _OPEN_CUE.search(body)
    if found is None:
        return None
    opens = parse_clock(found.group(1))
    if opens is None:
        return None
    return _ClaimedDay(closed=False, opens_early=True)


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
