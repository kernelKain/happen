"""Hours parsing, feasible arrival windows, and temporal relevance.

Evening bands are local to Asia/Kolkata and follow the window start:

- early evening is 17:00 inclusive through 19:00 exclusive;
- mid evening is 19:00 inclusive through 21:00 exclusive;
- late evening is 21:00 inclusive through 23:00 exclusive.

Saturday and Sunday are the weekend. A verified window is emitted only when its
full 30 minutes sit inside both the requested range and a verified opening
interval. Unparseable or contradictory hours produce no verified interval.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from happen_api.domain.models import (
    ArrivalWindow,
    BusynessObservation,
    DayOfWeek,
    HoursConfidence,
    HoursParse,
    OpeningInterval,
    OpenStatus,
    TemporalHint,
)

KOLKATA = ZoneInfo("Asia/Kolkata")
_DAY_ALIASES = {
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
_BANDS = {
    TemporalHint.early_evening: (time(17, 0), time(19, 0)),
    TemporalHint.mid_evening: (time(19, 0), time(21, 0)),
    TemporalHint.late_evening: (time(21, 0), time(23, 0)),
}
_CLOSED = {"closed"}
_ALL_DAY = {"open 24 hours", "open 24 hrs", "24 hours"}


def parse_hours_for_visit(
    entries: list[dict[str, str]],
    *,
    visit_date: date,
    source_url: str,
) -> HoursParse:
    """Parse provider hour lines for one Bengaluru visit date."""

    _require_http_url(source_url)
    grouped: dict[DayOfWeek, list[str]] = {}
    for day, hours in _normalize_entries(entries):
        grouped.setdefault(day, []).append(hours)
    visit_day = DayOfWeek(visit_date.strftime("%A").lower())
    lines = grouped.get(visit_day)
    if not lines:
        return HoursParse(status="uncertain", intervals=[], reason_codes=["hours_missing"])

    parsed_sets = [_parse_day_text(line) for line in lines]
    first = parsed_sets[0]
    if any(item != first for item in parsed_sets[1:]):
        return HoursParse(
            status="uncertain",
            intervals=[],
            reason_codes=["hours_contradictory"],
        )
    status, ranges = first
    if status == "uncertain":
        return HoursParse(status="uncertain", intervals=[], reason_codes=["hours_unparseable"])
    if status == "closed":
        return HoursParse(status="closed", intervals=[], reason_codes=["hours_closed"])
    intervals = [
        OpeningInterval(
            date=visit_date,
            opens_at=opens_at,
            closes_at=closes_at,
            source_url=source_url,
            confidence=HoursConfidence.verified,
        )
        for opens_at, closes_at in ranges
    ]
    return HoursParse(status="verified", intervals=intervals, reason_codes=["hours_verified"])


def generate_arrival_windows(
    *,
    candidate_id: str,
    visit_date: date,
    arrival_start: time,
    arrival_end: time,
    intervals: list[OpeningInterval],
    busyness: list[BusynessObservation],
) -> list[ArrivalWindow]:
    """Build verified 30-minute windows inside the request and the open intervals."""

    range_start, range_end = _range_bounds(visit_date, arrival_start, arrival_end)
    verified = [
        interval
        for interval in intervals
        if interval.date == visit_date and interval.confidence is HoursConfidence.verified
    ]
    windows: list[ArrivalWindow] = []
    cursor = range_start
    while cursor + timedelta(minutes=30) <= range_end:
        window_end = cursor + timedelta(minutes=30)
        if _inside_verified(cursor, window_end, verified):
            refs = _overlapping_busyness(cursor, window_end, busyness)
            windows.append(
                ArrivalWindow(
                    window_id=f"{candidate_id}:{cursor.strftime('%Y-%m-%dT%H:%M')}",
                    candidate_id=candidate_id,
                    starts_at=cursor,
                    ends_at=window_end,
                    open_status=OpenStatus.verified_open,
                    busyness_refs=refs,
                    evidence_refs=[],
                )
            )
        cursor += timedelta(minutes=30)
    return windows


def windows_from_hours(
    entries: list[dict[str, str]],
    *,
    candidate_id: str,
    visit_date: date,
    arrival_start: time,
    arrival_end: time,
    source_url: str,
    busyness: list[BusynessObservation] | None = None,
) -> tuple[HoursParse, list[ArrivalWindow]]:
    """Parse hours and generate the verified windows those hours allow."""

    parsed = parse_hours_for_visit(entries, visit_date=visit_date, source_url=source_url)
    windows = generate_arrival_windows(
        candidate_id=candidate_id,
        visit_date=visit_date,
        arrival_start=arrival_start,
        arrival_end=arrival_end,
        intervals=parsed.intervals,
        busyness=busyness or [],
    )
    return parsed, windows


def temporal_relevance(
    hint: TemporalHint,
    temporal_span: str | None,
    *,
    starts_at: datetime,
    ends_at: datetime,
) -> Decimal:
    """Return the locked temporal multiplier for one signal on one window."""

    if hint is TemporalHint.general:
        return Decimal("0.50")
    if hint is TemporalHint.unknown:
        return Decimal("0.35")
    if hint in _BANDS:
        band_start, band_end = _BANDS[hint]
        start_clock = starts_at.timetz().replace(tzinfo=None)
        if band_start <= start_clock < band_end:
            return Decimal(1)
        return Decimal(0)
    if hint is TemporalHint.weekday:
        return Decimal("0.75") if starts_at.weekday() < 5 else Decimal(0)
    if hint is TemporalHint.weekend:
        return Decimal("0.75") if starts_at.weekday() >= 5 else Decimal(0)
    if hint is TemporalHint.specific_time:
        return _specific_time_relevance(temporal_span, starts_at, ends_at)
    return Decimal(0)


def _normalize_entries(entries: list[dict[str, str]]) -> list[tuple[DayOfWeek, str]]:
    normalized: list[tuple[DayOfWeek, str]] = []
    for entry in entries:
        if "day" in entry and "hours" in entry:
            day_text, hours = entry["day"], entry["hours"]
        elif len(entry) == 1:
            day_text, hours = next(iter(entry.items()))
        else:
            raise ValueError("each hours entry must name one day")
        day = _DAY_ALIASES.get(day_text.strip().casefold())
        if day is None:
            raise ValueError("hours entry uses an unrecognized day")
        normalized.append((day, hours))
    return normalized


def _parse_day_text(text: str) -> tuple[str, list[tuple[time, time]]]:
    cleaned = " ".join(text.replace("–", "-").replace("—", "-").split())
    lowered = cleaned.casefold().rstrip(".")
    if lowered in _CLOSED:
        return "closed", []
    if lowered in _ALL_DAY:
        return "open", [(time(0, 0), time(0, 0))]
    ranges: list[tuple[time, time]] = []
    for part in [piece.strip() for piece in cleaned.split(",") if piece.strip()]:
        parsed = _parse_range(part)
        if parsed is None:
            return "uncertain", []
        ranges.append(parsed)
    if not ranges:
        return "uncertain", []
    return "open", ranges


def _parse_range(part: str) -> tuple[time, time] | None:
    pieces = re.split(r"\s+-\s+|\s+to\s+", part, maxsplit=1, flags=re.IGNORECASE)
    if len(pieces) != 2:
        pieces = part.split("-", maxsplit=1)
        if len(pieces) != 2:
            return None
    start = _parse_clock(pieces[0])
    end = _parse_clock(pieces[1])
    if start is None or end is None:
        return None
    return _resolve_clocks(start, end)


def _parse_clock(token: str) -> tuple[int, int, str | None] | None:
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


def _resolve_clocks(
    start: tuple[int, int, str | None],
    end: tuple[int, int, str | None],
) -> tuple[time, time] | None:
    start_hour, start_minute, start_meridiem = start
    end_hour, end_minute, end_meridiem = end
    if start_meridiem is not None and end_meridiem is not None:
        return (
            _apply_meridiem(start_hour, start_minute, start_meridiem),
            _apply_meridiem(end_hour, end_minute, end_meridiem),
        )
    if start_meridiem is None and end_meridiem is None:
        start_time = _twenty_four(start_hour, start_minute, allow_midnight_end=False)
        end_time = _twenty_four(end_hour, end_minute, allow_midnight_end=True)
        if start_time is None or end_time is None:
            return None
        return start_time, end_time
    if start_meridiem is None and end_meridiem is not None:
        start_time = _apply_meridiem(start_hour, start_minute, end_meridiem)
        end_time = _apply_meridiem(end_hour, end_minute, end_meridiem)
        if _minutes(start_time) >= _minutes(end_time):
            start_time = _from_minutes(_minutes(start_time) - 12 * 60)
        return start_time, end_time
    start_time = _apply_meridiem(start_hour, start_minute, start_meridiem or "am")
    same = _apply_meridiem(end_hour, end_minute, start_meridiem or "am")
    if _minutes(same) > _minutes(start_time):
        return start_time, same
    opposite = "am" if start_meridiem == "pm" else "pm"
    return start_time, _apply_meridiem(end_hour, end_minute, opposite)


def _twenty_four(hour: int, minute: int, *, allow_midnight_end: bool) -> time | None:
    if hour == 24:
        if allow_midnight_end and minute == 0:
            return time(0, 0)
        return None
    if hour > 23:
        return None
    return time(hour, minute)


def _apply_meridiem(hour: int, minute: int, meridiem: str) -> time:
    base = 0 if hour == 12 else hour
    if meridiem == "pm":
        base += 12
    return time(base, minute)


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _from_minutes(minutes: int) -> time:
    wrapped = minutes % (24 * 60)
    return time(wrapped // 60, wrapped % 60)


def _range_bounds(
    visit_date: date, arrival_start: time, arrival_end: time
) -> tuple[datetime, datetime]:
    for bound in (arrival_start, arrival_end):
        if bound.minute not in {0, 30} or bound.second or bound.microsecond:
            raise ValueError("arrival times must sit on 30-minute boundaries")
    start = datetime.combine(visit_date, arrival_start, tzinfo=KOLKATA)
    end = datetime.combine(visit_date, arrival_end, tzinfo=KOLKATA)
    if arrival_end <= arrival_start:
        end += timedelta(days=1)
    duration = end - start
    if duration < timedelta(hours=1) or duration > timedelta(hours=4):
        raise ValueError("arrival range must be one to four hours")
    return start, end


def _interval_bounds(interval: OpeningInterval) -> tuple[datetime, datetime]:
    start = datetime.combine(interval.date, interval.opens_at, tzinfo=KOLKATA)
    end = datetime.combine(interval.date, interval.closes_at, tzinfo=KOLKATA)
    if interval.closes_at <= interval.opens_at:
        end += timedelta(days=1)
    return start, end


def _inside_verified(start: datetime, end: datetime, intervals: list[OpeningInterval]) -> bool:
    for interval in intervals:
        open_start, open_end = _interval_bounds(interval)
        if start >= open_start and end <= open_end:
            return True
    return False


def _overlapping_busyness(
    start: datetime,
    end: datetime,
    observations: list[BusynessObservation],
) -> list[str]:
    refs: list[str] = []
    window_day = DayOfWeek(start.strftime("%A").lower())
    for observation in observations:
        if observation.day_of_week is not window_day:
            continue
        observed_start = datetime.combine(start.date(), observation.hour_start, tzinfo=KOLKATA)
        observed_end = observed_start + timedelta(hours=1)
        if start < observed_end and end > observed_start:
            refs.append(
                f"{observation.day_of_week.value}:{observation.hour_start.strftime('%H:%M')}"
            )
    return sorted(set(refs))


def _specific_time_relevance(
    temporal_span: str | None,
    starts_at: datetime,
    ends_at: datetime,
) -> Decimal:
    if temporal_span is None:
        return Decimal(0)
    cleaned = " ".join(temporal_span.replace("–", "-").replace("—", "-").split())
    if "-" in cleaned or " to " in cleaned.casefold():
        parsed = _parse_range(cleaned)
        if parsed is None:
            return Decimal(0)
        span_start = datetime.combine(starts_at.date(), parsed[0], tzinfo=starts_at.tzinfo)
        span_end = datetime.combine(starts_at.date(), parsed[1], tzinfo=starts_at.tzinfo)
        if parsed[1] <= parsed[0]:
            span_end += timedelta(days=1)
        if starts_at < span_end and ends_at > span_start:
            return Decimal(1)
        return Decimal(0)
    clock = _parse_clock(cleaned)
    if clock is None:
        return Decimal(0)
    hour, minute, meridiem = clock
    if meridiem is None:
        resolved = _twenty_four(hour, minute, allow_midnight_end=False)
    else:
        resolved = _apply_meridiem(hour, minute, meridiem)
    if resolved is None:
        return Decimal(0)
    instant = datetime.combine(starts_at.date(), resolved, tzinfo=starts_at.tzinfo)
    if starts_at <= instant < ends_at:
        return Decimal(1)
    return Decimal(0)


def _require_http_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source_url must be an http or https URL")
