"""Destination-local dates and wall times. Python zoneinfo owns the arithmetic."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from happen_api.planning.contracts import DatePhrase, PendingDate


class DateStatus(StrEnum):
    resolved = "resolved"
    ambiguous = "ambiguous"
    missing = "missing"


class WallTimeStatus(StrEnum):
    unique = "unique"
    gap = "gap"
    ambiguous = "ambiguous"
    not_checked = "not_checked"


class LocalTimeResult(BaseModel):
    """A destination-local date and, when a start time was stated, its wall-clock status."""

    model_config = ConfigDict(extra="forbid")

    date_status: DateStatus
    wall_status: WallTimeStatus
    local_date: date | None = None
    local_start: time | None = None
    timezone_name: str
    offsets: list[str] = Field(default_factory=list, max_length=2)
    date_candidates: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("timezone_name")
    @classmethod
    def _zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone_name must be an IANA zone") from exc
        return value


def resolve_local_time(
    *,
    timezone_name: str,
    instant: datetime,
    explicit_date: date | None,
    pending_date: PendingDate | None,
    local_start: time | None,
) -> LocalTimeResult:
    """Apply a relative date in the destination zone, then classify the stated start time."""

    zone = ZoneInfo(timezone_name)
    zone_name = timezone_name
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("clock moment must be timezone-aware")
    resolved_date, candidates = _calendar_date(explicit_date, pending_date, instant, zone)
    if candidates:
        return LocalTimeResult(
            date_status=DateStatus.ambiguous,
            wall_status=WallTimeStatus.not_checked,
            local_start=local_start,
            timezone_name=zone_name,
            date_candidates=[item.isoformat() for item in candidates],
        )
    if resolved_date is None:
        return LocalTimeResult(
            date_status=DateStatus.missing,
            wall_status=WallTimeStatus.not_checked,
            local_start=local_start,
            timezone_name=zone_name,
        )
    if local_start is None:
        return LocalTimeResult(
            date_status=DateStatus.resolved,
            wall_status=WallTimeStatus.not_checked,
            local_date=resolved_date,
            timezone_name=zone_name,
        )
    wall_status, offsets = classify_wall_time(resolved_date, local_start, zone)
    return LocalTimeResult(
        date_status=DateStatus.resolved,
        wall_status=wall_status,
        local_date=resolved_date,
        local_start=local_start,
        timezone_name=zone_name,
        offsets=offsets,
    )


def classify_wall_time(
    local_date: date,
    local_start: time,
    zone: ZoneInfo,
) -> tuple[WallTimeStatus, list[str]]:
    """Tell a unique local time from a DST gap or a repeated local time.

    An ambiguous time keeps both offsets. A gap keeps neither, and neither case
    invents a replacement clock time.
    """

    naive = datetime.combine(local_date, local_start)
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    first_back = first.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    second_back = second.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    if first_back != naive and second_back != naive:
        return WallTimeStatus.gap, []
    first_offset = first.utcoffset()
    second_offset = second.utcoffset()
    if (
        first_back == naive
        and second_back == naive
        and first_offset is not None
        and second_offset is not None
        and first_offset != second_offset
    ):
        return WallTimeStatus.ambiguous, [
            _format_offset(first_offset),
            _format_offset(second_offset),
        ]
    if first_offset is None or first_back != naive:
        return WallTimeStatus.gap, []
    return WallTimeStatus.unique, [_format_offset(first_offset)]


def _calendar_date(
    explicit_date: date | None,
    pending_date: PendingDate | None,
    instant: datetime,
    zone: ZoneInfo,
) -> tuple[date | None, list[date]]:
    if explicit_date is not None:
        return explicit_date, []
    if pending_date is None:
        return None, []
    today = instant.astimezone(zone).date()
    phrase = pending_date.phrase
    if phrase in {DatePhrase.today, DatePhrase.tonight}:
        return today, []
    if phrase is DatePhrase.tomorrow:
        return today + timedelta(days=1), []
    if phrase is DatePhrase.weekday:
        return _upcoming(pending_date.weekday, today), []
    if phrase is DatePhrase.next_weekday:
        soon = _upcoming(pending_date.weekday, today)
        return None, [soon, soon + timedelta(days=7)]
    if today.weekday() == 6:
        return today, []
    saturday = _upcoming(5, today)
    return None, [saturday, saturday + timedelta(days=1)]


def _upcoming(weekday: int | None, today: date) -> date:
    if weekday is None:
        raise ValueError("a weekday phrase names a weekday")
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def _format_offset(offset: timedelta) -> str:
    seconds = int(offset.total_seconds())
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"
