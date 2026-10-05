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

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from happen_api.domain.hours import (
    HOURS_CLOSED,
    HOURS_CONTRADICTORY,
    HOURS_MISSING,
    apply_meridiem,
    day_intervals,
    normalize_hours,
    parse_clock,
    parse_range,
    twenty_four,
)
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
_BANDS = {
    TemporalHint.early_evening: (time(17, 0), time(19, 0)),
    TemporalHint.mid_evening: (time(19, 0), time(21, 0)),
    TemporalHint.late_evening: (time(21, 0), time(23, 0)),
}


def parse_hours_for_visit(
    entries: list[dict[str, str]],
    *,
    visit_date: date,
    source_url: str,
) -> HoursParse:
    """Read provider hour entries for one visit date through the canonical schedule."""

    _require_http_url(source_url)
    normalized = normalize_hours(entries)
    schedule = normalized.days.get(DayOfWeek(visit_date.strftime("%A").lower()))
    if schedule is None:
        if normalized.unrecognized:
            return HoursParse(
                status="uncertain",
                intervals=[],
                reason_codes=[
                    normalized.reason_codes[0] if normalized.reason_codes else HOURS_MISSING
                ],
            )
        return HoursParse(status="uncertain", intervals=[], reason_codes=[HOURS_MISSING])
    if schedule.status == "unknown":
        reasons = set(schedule.reason_codes)
        if HOURS_CONTRADICTORY in reasons:
            return HoursParse(status="uncertain", intervals=[], reason_codes=[HOURS_CONTRADICTORY])
        return HoursParse(
            status="uncertain",
            intervals=[],
            reason_codes=["hours_unparseable"],
        )
    if schedule.status == "closed":
        return HoursParse(status="closed", intervals=[], reason_codes=[HOURS_CLOSED])
    intervals = [
        OpeningInterval(
            date=visit_date,
            opens_at=interval.opens_at,
            closes_at=interval.closes_at,
            source_url=source_url,
            confidence=HoursConfidence.verified,
        )
        for interval in day_intervals(normalized, visit_date)
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
        parsed = parse_range(cleaned)
        if parsed is None:
            return Decimal(0)
        span_start = datetime.combine(starts_at.date(), parsed[0], tzinfo=starts_at.tzinfo)
        span_end = datetime.combine(starts_at.date(), parsed[1], tzinfo=starts_at.tzinfo)
        if parsed[1] <= parsed[0]:
            span_end += timedelta(days=1)
        if starts_at < span_end and ends_at > span_start:
            return Decimal(1)
        return Decimal(0)
    clock = parse_clock(cleaned)
    if clock is None:
        return Decimal(0)
    hour, minute, meridiem = clock
    if meridiem is None:
        resolved = twenty_four(hour, minute, allow_midnight_end=False)
    else:
        resolved = apply_meridiem(hour, minute, meridiem)
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
