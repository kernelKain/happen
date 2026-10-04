"""Resolve one destination with SerpApi, then read its local time offline."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, time
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field

from happen_api.planning.clock import Clock
from happen_api.planning.contracts import (
    BriefConfidence,
    PendingDate,
    ResolutionSource,
    ResolvedDestination,
    SourceProvenance,
)
from happen_api.planning.local_time import LocalTimeResult, resolve_local_time
from happen_api.providers.serpapi.client import (
    MapsCoordinate,
    SerpApiClient,
    SerpApiFailure,
    SupportedLocation,
)

PLAN_BILLED_REQUEST_LIMIT = 8
_LOCATIONS_URL = "https://serpapi.com/locations.json"
_MAPS_URL = "https://serpapi.com/search.json"
_CHOICE_LIMIT = 3
ZoneLookup = Callable[[float, float], str | None]
_TIMEZONE_FINDER: object | None = None


class ResolutionStatus(StrEnum):
    resolved = "resolved"
    ambiguous = "ambiguous"
    unsupported = "unsupported"
    missing_coordinates = "missing_coordinates"
    unknown_timezone = "unknown_timezone"
    budget_exhausted = "budget_exhausted"


class DestinationResolution(BaseModel):
    """The place outcome and, when one zone is known, the destination-local time."""

    model_config = ConfigDict(extra="forbid")

    status: ResolutionStatus
    destination: ResolvedDestination | None = None
    choices: list[ResolvedDestination] = Field(default_factory=list, max_length=_CHOICE_LIMIT)
    billed_requests: int = Field(ge=0)
    local_time: LocalTimeResult | None = None


def resolve_destination(
    query: str,
    client: SerpApiClient,
    *,
    clock: Clock,
    pending_date: PendingDate | None = None,
    local_date: date | None = None,
    local_start: time | None = None,
    billed_limit: int = PLAN_BILLED_REQUEST_LIMIT,
    zone_at: ZoneLookup | None = None,
) -> DestinationResolution:
    """Match a place with the free Locations API, then one billed Maps lookup if needed.

    Several matches become at most three choices. Relative dates are applied
    only after one destination timezone is known.
    """

    cleaned = " ".join(query.split())
    if not cleaned:
        raise SerpApiFailure(
            "INVALID_REQUEST",
            "A location search needs a query.",
            retryable=False,
        )
    lookup = zone_at or timezone_at_coordinates
    started = client.credits_charged
    matches = _place_matches(client.supported_locations(cleaned, limit=5))
    if len(matches) > 1:
        return _finish(
            status=ResolutionStatus.ambiguous,
            choices=[
                _from_location(cleaned, item, lookup, clock) for item in matches[:_CHOICE_LIMIT]
            ],
            billed=client.credits_charged - started,
        )
    known = matches[0] if matches else None
    if known is not None and _has_coordinates(known):
        return _settle(
            _from_location(cleaned, known, lookup, clock),
            clock,
            pending_date,
            local_date,
            local_start,
            client.credits_charged - started,
        )
    if client.credits_charged >= billed_limit:
        partial = _from_location(cleaned, known, lookup, clock) if known is not None else None
        return _finish(
            status=ResolutionStatus.budget_exhausted,
            destination=partial,
            billed=client.credits_charged - started,
        )
    try:
        points = client.lookup_maps_coordinates(_maps_query(cleaned, known))
    except SerpApiFailure as failure:
        if failure.code != "CREDIT_BUDGET_EXCEEDED":
            raise
        partial = _from_location(cleaned, known, lookup, clock) if known is not None else None
        return _finish(
            status=ResolutionStatus.budget_exhausted,
            destination=partial,
            billed=client.credits_charged - started,
        )
    billed = client.credits_charged - started
    if known is not None:
        return _settle(
            _with_maps_coordinates(cleaned, known, points, lookup, clock),
            clock,
            pending_date,
            local_date,
            local_start,
            billed,
        )
    if not points:
        return _finish(status=ResolutionStatus.unsupported, billed=billed)
    if len(points) > 1:
        return _finish(
            status=ResolutionStatus.ambiguous,
            choices=[_from_maps(cleaned, point, lookup, clock) for point in points[:_CHOICE_LIMIT]],
            billed=billed,
        )
    return _settle(
        _from_maps(cleaned, points[0], lookup, clock),
        clock,
        pending_date,
        local_date,
        local_start,
        billed,
    )


def timezone_at_coordinates(latitude: float, longitude: float) -> str | None:
    """Return the IANA zone for a coordinate, or None when the dataset has none."""

    global _TIMEZONE_FINDER
    from timezonefinder import TimezoneFinder

    if not isinstance(_TIMEZONE_FINDER, TimezoneFinder):
        _TIMEZONE_FINDER = TimezoneFinder()
    found = _TIMEZONE_FINDER.timezone_at(lng=longitude, lat=latitude)
    if not isinstance(found, str) or not found:
        return None
    try:
        ZoneInfo(found)
    except ZoneInfoNotFoundError:
        return None
    return found


def _place_matches(locations: list[SupportedLocation]) -> list[SupportedLocation]:
    cities = [item for item in locations if (item.target_type or "").casefold() == "city"]
    return cities or locations


def _has_coordinates(location: SupportedLocation) -> bool:
    return location.latitude is not None and location.longitude is not None


def _maps_query(query: str, known: SupportedLocation | None) -> str:
    if known is None:
        return query
    return known.canonical_name or known.name


def _with_maps_coordinates(
    query: str,
    location: SupportedLocation,
    points: list[MapsCoordinate],
    lookup: ZoneLookup,
    clock: Clock,
) -> ResolvedDestination:
    destination = _from_location(query, location, lookup, clock)
    if _has_coordinates(location) or len(points) != 1:
        return destination
    point = points[0]
    zone = lookup(point.latitude, point.longitude)
    return destination.model_copy(
        update={
            "latitude": point.latitude,
            "longitude": point.longitude,
            "timezone_name": zone,
            "confidence": BriefConfidence.medium,
            "resolution_source": ResolutionSource.maps_lookup,
            "provenance": _provenance(clock, maps=True),
        }
    )


def _settle(
    destination: ResolvedDestination,
    clock: Clock,
    pending_date: PendingDate | None,
    local_date: date | None,
    local_start: time | None,
    billed: int,
) -> DestinationResolution:
    if destination.latitude is None or destination.longitude is None:
        return _finish(
            status=ResolutionStatus.missing_coordinates,
            destination=destination,
            billed=billed,
        )
    if destination.timezone_name is None:
        return _finish(
            status=ResolutionStatus.unknown_timezone,
            destination=destination,
            billed=billed,
        )
    return _finish(
        status=ResolutionStatus.resolved,
        destination=destination,
        billed=billed,
        local_time=resolve_local_time(
            timezone_name=destination.timezone_name,
            instant=clock.now(),
            explicit_date=local_date,
            pending_date=pending_date,
            local_start=local_start,
        ),
    )


def _from_location(
    query: str,
    location: SupportedLocation,
    lookup: ZoneLookup,
    clock: Clock,
) -> ResolvedDestination:
    latitude = location.latitude
    longitude = location.longitude
    zone = lookup(latitude, longitude) if latitude is not None and longitude is not None else None
    complete = (
        zone is not None
        and location.country_code is not None
        and location.canonical_name is not None
        and latitude is not None
    )
    return ResolvedDestination(
        label=_display(location.name, location.canonical_name),
        source_text=query[:120],
        locality=_clip(location.name, 80),
        region=_region(location.canonical_name),
        country_code=location.country_code,
        timezone_name=zone,
        latitude=latitude,
        longitude=longitude,
        serpapi_location=_clip(location.canonical_name, 120) if location.canonical_name else None,
        confidence=BriefConfidence.high if complete else BriefConfidence.medium,
        resolution_source=ResolutionSource.locations_api,
        provenance=_provenance(clock, maps=False),
    )


def _from_maps(
    query: str,
    point: MapsCoordinate,
    lookup: ZoneLookup,
    clock: Clock,
) -> ResolvedDestination:
    label = _clip(point.title, 120) or query[:120]
    return ResolvedDestination(
        label=label,
        source_text=query[:120],
        locality=_clip(point.title, 80),
        timezone_name=lookup(point.latitude, point.longitude),
        latitude=point.latitude,
        longitude=point.longitude,
        confidence=BriefConfidence.medium,
        resolution_source=ResolutionSource.maps_lookup,
        provenance=_provenance(clock, maps=True),
    )


def _provenance(clock: Clock, *, maps: bool) -> SourceProvenance:
    return SourceProvenance(
        provider="serpapi",
        source_url=_MAPS_URL if maps else _LOCATIONS_URL,
        retrieved_at=clock.now(),
        label="SerpApi maps" if maps else "SerpApi locations",
    )


def _finish(
    *,
    status: ResolutionStatus,
    billed: int,
    destination: ResolvedDestination | None = None,
    choices: list[ResolvedDestination] | None = None,
    local_time: LocalTimeResult | None = None,
) -> DestinationResolution:
    return DestinationResolution(
        status=status,
        destination=destination,
        choices=choices or [],
        billed_requests=billed,
        local_time=local_time,
    )


def _display(name: str, canonical: str | None) -> str:
    if canonical:
        parts = [part.strip() for part in canonical.split(",") if part.strip()]
        if parts:
            return _clip(", ".join(parts), 120) or name[:120]
    return name[:120]


def _region(canonical: str | None) -> str | None:
    if not canonical:
        return None
    parts = [part.strip() for part in canonical.split(",") if part.strip()]
    if len(parts) < 3:
        return None
    return _clip(parts[-2], 80)


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:limit]
