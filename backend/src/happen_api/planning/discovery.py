"""Global place discovery. Queries come from the destination and the intents.

The provider chooses language. A search keeps a bounded candidate pool, and
Python ranks that pool. Provider order is only a tie-breaker. Missing facts
stay unknown. Official hours override a community statement, and a
disagreement stays on the place.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import date, datetime, time
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from happen_api.planning.contracts import IntentKind, PlaceIntent, ResolvedDestination
from happen_api.planning.destination import PLAN_BILLED_REQUEST_LIMIT
from happen_api.providers.serpapi.client import SerpApiClient, SerpApiFailure

_INTENT_QUERY = {
    IntentKind.dinner: "dinner",
    IntentKind.drinks: "drinks",
    IntentKind.coffee: "coffee",
    IntentKind.dessert: "dessert",
    IntentKind.show: "show",
    IntentKind.walk: "walk",
    IntentKind.live_music: "live music",
    IntentKind.museum: "museum",
}
_COMMUNITY_HOSTS = {
    "reddit.com",
    "www.reddit.com",
    "instagram.com",
    "www.instagram.com",
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "facebook.com",
    "www.facebook.com",
}
_PHONE = re.compile(r"(?:\+\d|\(\d|\b\d)[\d\s().-]{7,}\d")
_LABEL = re.compile(r"[^0-9a-z]+")
_MAX_WEB_SEARCHES = 2
_MAX_INTENTS = 2
_POOL_LIMIT = 5
_POOL_TOTAL = _MAX_INTENTS * _POOL_LIMIT
_DESTINATION_RADIUS_KM = 80.0


class DiscoveryStatus(StrEnum):
    ready = "ready"
    partial_evidence = "partial_evidence"
    no_result = "no_result"
    timeout = "timeout"
    quota = "quota"


class EvidenceConflict(BaseModel):
    """A community statement that does not match the official hours."""

    model_config = ConfigDict(extra="forbid")

    field: str = "hours"
    official: str | None = Field(default=None, max_length=200)
    community: str | None = Field(default=None, max_length=200)


class DiscoveredPlace(BaseModel):
    """One place. Absent provider fields are listed as unknown."""

    model_config = ConfigDict(extra="forbid")

    intent: IntentKind
    provider_rank: int = Field(default=0, ge=0, le=100)
    place_id: str | None = Field(default=None, max_length=120)
    data_id: str | None = Field(default=None, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    address: str | None = Field(default=None, max_length=200)
    latitude: float | None = None
    longitude: float | None = None
    rating: float | None = None
    review_count: int | None = Field(default=None, ge=0)
    price: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=80)
    hours: list[str] = Field(default_factory=list, max_length=8)
    popular_times_known: bool = False
    website: str | None = Field(default=None, max_length=300)
    maps_link: str | None = Field(default=None, max_length=300)
    thumbnail: str | None = Field(default=None, max_length=300)
    events: list[str] = Field(default_factory=list, max_length=8)
    highlights: list[str] = Field(default_factory=list, max_length=8)
    provider_language: str | None = Field(default=None, max_length=16)
    unknown_fields: list[str] = Field(default_factory=list, max_length=16)
    conflicts: list[EvidenceConflict] = Field(default_factory=list, max_length=4)
    community_notes: list[str] = Field(default_factory=list, max_length=4)


class CandidatePool(BaseModel):
    """Normalized places kept so a later selection can compare them."""

    model_config = ConfigDict(extra="forbid")

    places: list[DiscoveredPlace] = Field(default_factory=list, max_length=_POOL_TOTAL)


class DiscoveryResult(BaseModel):
    """Candidate places for one evening, plus the billed requests this call spent."""

    model_config = ConfigDict(extra="forbid")

    status: DiscoveryStatus
    places: list[DiscoveredPlace] = Field(default_factory=list, max_length=_POOL_TOTAL)
    cache_key: str = Field(min_length=64, max_length=64)
    billed_requests: int = Field(ge=0)
    queries: list[str] = Field(default_factory=list, max_length=8)
    retrieved_at: datetime
    stopped: DiscoveryStatus | None = None


def discovery_cache_key(
    destination: ResolvedDestination,
    *,
    local_date: date,
    start_time: time,
    end_time: time | None,
    intents: list[PlaceIntent],
    preferences: list[str] | None = None,
) -> str:
    """Identify one retrieval by destination, local evening, intents, and constraints."""

    canonical = (destination.serpapi_location or destination.label).casefold()
    window = start_time.isoformat()
    if end_time is not None:
        window = f"{window}/{end_time.isoformat()}"
    ordered = ",".join(item.kind.value for item in sorted(intents, key=lambda item: item.position))
    prefs = ",".join(
        sorted({item.casefold().strip() for item in preferences or [] if item.strip()})
    )
    material = f"{canonical}|{local_date.isoformat()}|{window}|{ordered}|{prefs}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def maps_query(intent: PlaceIntent, destination: ResolvedDestination) -> str:
    """Build one Maps query from the intent and the canonical destination."""

    place = " ".join((destination.serpapi_location or destination.label).split())
    word = _INTENT_QUERY[intent.kind]
    return f"{word} in {place}"


def discover_places(
    destination: ResolvedDestination,
    intents: list[PlaceIntent],
    client: SerpApiClient,
    *,
    local_date: date,
    start_time: time,
    end_time: time | None = None,
    retrieved_at: datetime,
    billed_limit: int = PLAN_BILLED_REQUEST_LIMIT,
    preferences: list[str] | None = None,
) -> DiscoveryResult:
    """Search up to two intents and keep a ranked pool inside the shared budget."""

    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    ordered = sorted(intents, key=lambda item: item.position)[:_MAX_INTENTS]
    if not ordered:
        raise ValueError("discovery needs at least one intent")
    chosen = [item for item in preferences or [] if item.strip()]
    cache_key = discovery_cache_key(
        destination,
        local_date=local_date,
        start_time=start_time,
        end_time=end_time,
        intents=ordered,
        preferences=chosen,
    )
    started = client.credits_charged
    queries: list[str] = []
    found: list[DiscoveredPlace] = []
    failure: DiscoveryStatus | None = None
    for intent in ordered:
        if not _within_budget(client, billed_limit):
            failure = DiscoveryStatus.quota
            break
        query = maps_query(intent, destination)
        queries.append(query)
        try:
            snapshot = client.search_places(
                query,
                latitude=destination.latitude,
                longitude=destination.longitude,
            )
        except SerpApiFailure as exc:
            failure = _failure_status(exc)
            break
        rows = snapshot.payload.get("local_results")
        if isinstance(rows, list):
            found.extend(
                _candidate_pool(
                    rows,
                    intent.kind,
                    destination,
                    local_date=local_date,
                    arrival=start_time,
                    preferences=chosen,
                )
            )
    if failure is None:
        failure = _enrich(
            found,
            ordered,
            destination,
            client,
            queries,
            billed_limit=billed_limit,
            local_date=local_date,
            arrival=start_time,
            preferences=chosen,
        )
    _sort_pool(
        found,
        ordered,
        local_date=local_date,
        arrival=start_time,
        preferences=chosen,
    )
    status = _status(found, failure)
    stopped = failure if failure in {DiscoveryStatus.timeout, DiscoveryStatus.quota} else None
    return DiscoveryResult(
        status=status,
        places=found,
        cache_key=cache_key,
        billed_requests=client.credits_charged - started,
        queries=queries,
        retrieved_at=retrieved_at,
        stopped=stopped if found else None,
    )


def _candidate_pool(
    rows: list[object],
    intent: IntentKind,
    destination: ResolvedDestination,
    *,
    local_date: date,
    arrival: time,
    preferences: list[str],
) -> list[DiscoveredPlace]:
    """Keep up to five in-destination places. Search order is not the rank."""

    accepted: list[DiscoveredPlace] = []
    seen_place: set[str] = set()
    seen_data: set[str] = set()
    seen_labels: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        place = _place_from_record(row, intent, provider_rank=index)
        if place is None or _outside_destination(place, destination):
            continue
        if _is_duplicate(place, seen_place, seen_data, seen_labels):
            continue
        _remember(place, seen_place, seen_data, seen_labels)
        accepted.append(place)
    accepted.sort(
        key=lambda place: _order_key(
            place,
            local_date=local_date,
            arrival=arrival,
            preferences=preferences,
        )
    )
    return accepted[:_POOL_LIMIT]


def _enrich(
    places: list[DiscoveredPlace],
    intents: list[PlaceIntent],
    destination: ResolvedDestination,
    client: SerpApiClient,
    queries: list[str],
    *,
    billed_limit: int,
    local_date: date,
    arrival: time,
    preferences: list[str],
) -> DiscoveryStatus | None:
    """Enrich in rank order. A closed finalist yields to the next place."""

    failure: DiscoveryStatus | None = None
    web_used = 0
    removed: set[int] = set()
    for intent in intents:
        group = [place for place in places if place.intent == intent.kind]
        for index, place in enumerate(group):
            if _outside_destination(place, destination):
                removed.add(id(place))
                continue
            state = _visit_state(place, local_date, arrival)
            if state != "closed" and _needs_feasibility(place, destination):
                failure, stop = _merge_status(failure, _spend_details(place, client, billed_limit))
                if stop:
                    _drop(places, removed)
                    return failure
                if _outside_destination(place, destination):
                    removed.add(id(place))
                    continue
                state = _visit_state(place, local_date, arrival)
            if state == "closed":
                continue
            failure, stop = _merge_status(
                failure,
                _compare_runner_up(
                    group,
                    index,
                    place,
                    destination,
                    client,
                    billed_limit=billed_limit,
                    local_date=local_date,
                    arrival=arrival,
                    preferences=preferences,
                    removed=removed,
                ),
            )
            if stop:
                _drop(places, removed)
                return failure
            failure, stop = _merge_status(
                failure,
                _reviews_if_needed(
                    group,
                    index,
                    place,
                    client,
                    billed_limit=billed_limit,
                    local_date=local_date,
                    arrival=arrival,
                    preferences=preferences,
                ),
            )
            if stop:
                _drop(places, removed)
                return failure
            if not place.hours and web_used < _MAX_WEB_SEARCHES:
                before = len(queries)
                failure, stop = _merge_status(
                    failure,
                    _spend_web(place, destination, client, queries, billed_limit),
                )
                if len(queries) > before:
                    web_used += 1
                if stop:
                    _drop(places, removed)
                    return failure
            break
    _drop(places, removed)
    return failure


def _compare_runner_up(
    group: list[DiscoveredPlace],
    index: int,
    leader: DiscoveredPlace,
    destination: ResolvedDestination,
    client: SerpApiClient,
    *,
    billed_limit: int,
    local_date: date,
    arrival: time,
    preferences: list[str],
    removed: set[int],
) -> DiscoveryStatus | None:
    runner = _next_viable(group, index, local_date, arrival)
    if runner is None or id(runner) in removed:
        return None
    if not _needs_feasibility(runner, destination):
        return None
    if _open_ceiling(runner, preferences) < _current_fit(leader, local_date, arrival, preferences):
        return None
    failure = _spend_details(runner, client, billed_limit)
    if failure in {DiscoveryStatus.timeout, DiscoveryStatus.quota}:
        return failure
    if _outside_destination(runner, destination):
        removed.add(id(runner))
    return failure


def _reviews_if_needed(
    group: list[DiscoveredPlace],
    index: int,
    leader: DiscoveredPlace,
    client: SerpApiClient,
    *,
    billed_limit: int,
    local_date: date,
    arrival: time,
    preferences: list[str],
) -> DiscoveryStatus | None:
    from happen_api.planning.itinerary import (
        constraint_supported,
        constraint_terms,
        unmet_constraint_gain,
        verified_fit,
    )

    constraints = constraint_terms(preferences)
    if not constraints:
        return None
    targets = [leader]
    runner = _next_viable(group, index, local_date, arrival)
    if runner is not None:
        leader_fit = verified_fit(leader, _visit_state(leader, local_date, arrival), preferences)
        runner_fit = verified_fit(runner, _visit_state(runner, local_date, arrival), preferences)
        if runner_fit + unmet_constraint_gain(runner, preferences) >= leader_fit:
            targets.append(runner)
    failure: DiscoveryStatus | None = None
    for target in targets:
        if all(constraint_supported(target, item) for item in constraints):
            continue
        failure = _spend_reviews(target, client, billed_limit) or failure
        if failure in {DiscoveryStatus.timeout, DiscoveryStatus.quota}:
            return failure
    return failure


def _next_viable(
    group: list[DiscoveredPlace],
    index: int,
    local_date: date,
    arrival: time,
) -> DiscoveredPlace | None:
    for candidate in group[index + 1 :]:
        if _visit_state(candidate, local_date, arrival) != "closed":
            return candidate
    return None


def _needs_feasibility(place: DiscoveredPlace, destination: ResolvedDestination) -> bool:
    if not place.hours:
        return True
    return place.latitude is None and destination.latitude is not None


def _spend_details(
    place: DiscoveredPlace,
    client: SerpApiClient,
    billed_limit: int,
) -> DiscoveryStatus | None:
    if not _within_budget(client, billed_limit):
        return DiscoveryStatus.quota
    return _fill_details(place, client)


def _spend_reviews(
    place: DiscoveredPlace,
    client: SerpApiClient,
    billed_limit: int,
) -> DiscoveryStatus | None:
    if not _within_budget(client, billed_limit):
        return DiscoveryStatus.quota
    return _fill_reviews(place, client)


def _spend_web(
    place: DiscoveredPlace,
    destination: ResolvedDestination,
    client: SerpApiClient,
    queries: list[str],
    billed_limit: int,
) -> DiscoveryStatus | None:
    if not _within_budget(client, billed_limit):
        return DiscoveryStatus.quota
    query = _web_query(place, destination)
    queries.append(query)
    try:
        snapshot = client.web_search(query)
    except SerpApiFailure as exc:
        return _failure_status(exc)
    _apply_web(place, snapshot.payload.get("organic_results"), destination)
    return None


def _merge_status(
    current: DiscoveryStatus | None,
    new: DiscoveryStatus | None,
) -> tuple[DiscoveryStatus | None, bool]:
    failure = new or current
    return failure, failure in {DiscoveryStatus.timeout, DiscoveryStatus.quota}


def _drop(places: list[DiscoveredPlace], removed: set[int]) -> None:
    if removed:
        places[:] = [place for place in places if id(place) not in removed]


def _sort_pool(
    places: list[DiscoveredPlace],
    intents: list[PlaceIntent],
    *,
    local_date: date,
    arrival: time,
    preferences: list[str],
) -> None:
    ordered: list[DiscoveredPlace] = []
    for intent in intents:
        group = [place for place in places if place.intent == intent.kind]
        group.sort(
            key=lambda place: _order_key(
                place,
                local_date=local_date,
                arrival=arrival,
                preferences=preferences,
            )
        )
        ordered.extend(group[:_POOL_LIMIT])
    places[:] = ordered


def _order_key(
    place: DiscoveredPlace,
    *,
    local_date: date,
    arrival: time,
    preferences: list[str],
) -> tuple[int, int, str, str]:
    from happen_api.planning.itinerary import selection_key

    return selection_key(
        place,
        local_date=local_date,
        arrival=arrival,
        preferences=preferences,
    )


def _visit_state(place: DiscoveredPlace, local_date: date, arrival: time) -> str:
    from happen_api.planning.itinerary import hours_status

    return hours_status(place, local_date, arrival)


def _current_fit(
    place: DiscoveredPlace,
    local_date: date,
    arrival: time,
    preferences: list[str],
) -> int:
    from happen_api.planning.itinerary import verified_fit

    return verified_fit(place, _visit_state(place, local_date, arrival), preferences)


def _open_ceiling(place: DiscoveredPlace, preferences: list[str]) -> int:
    from happen_api.planning.itinerary import verified_fit

    return verified_fit(place, "open", preferences)


def _fill_details(place: DiscoveredPlace, client: SerpApiClient) -> DiscoveryStatus | None:
    try:
        if place.place_id:
            snapshot = client.place_details(place_id=place.place_id)
        else:
            snapshot = client.place_details(data_id=place.data_id)
    except SerpApiFailure as exc:
        return _failure_status(exc)
    body = snapshot.payload.get("place_results")
    if isinstance(body, dict):
        _overlay_official(place, body)
    return None


def _fill_reviews(place: DiscoveredPlace, client: SerpApiClient) -> DiscoveryStatus | None:
    try:
        if place.place_id:
            snapshot = client.place_reviews(place_id=place.place_id)
        else:
            snapshot = client.place_reviews(data_id=place.data_id)
    except SerpApiFailure as exc:
        return _failure_status(exc)
    reviews = snapshot.payload.get("reviews")
    if isinstance(reviews, list):
        _add_highlights(place, reviews)
    return None


def _within_budget(client: SerpApiClient, billed_limit: int) -> bool:
    return client.credits_charged < billed_limit


def _failure_status(exc: SerpApiFailure) -> DiscoveryStatus:
    if exc.code in {"CREDIT_BUDGET_EXCEEDED", "QUOTA_EXHAUSTED"}:
        return DiscoveryStatus.quota
    if exc.code == "TRANSIENT_DEPENDENCY":
        return DiscoveryStatus.timeout
    return DiscoveryStatus.partial_evidence


def _status(places: list[DiscoveredPlace], failure: DiscoveryStatus | None) -> DiscoveryStatus:
    if not places:
        if failure in {DiscoveryStatus.timeout, DiscoveryStatus.quota}:
            return failure
        return DiscoveryStatus.no_result
    if failure is not None or any(place.unknown_fields for place in places):
        return DiscoveryStatus.partial_evidence
    return DiscoveryStatus.ready


def _place_from_record(
    record: dict[str, object],
    intent: IntentKind,
    provider_rank: int = 0,
) -> DiscoveredPlace | None:
    name = _clean(record.get("title")) or _clean(record.get("name"))
    place_id = _identifier(record.get("place_id"))
    data_id = _identifier(record.get("data_id"))
    if name is None or (place_id is None and data_id is None):
        return None
    latitude, longitude = _coordinates(record.get("gps_coordinates"))
    hours = _hours(record)
    highlights = _inline_highlights(record)
    place = DiscoveredPlace(
        intent=intent,
        provider_rank=provider_rank,
        place_id=place_id,
        data_id=data_id,
        name=name,
        address=_clean(record.get("address")),
        latitude=latitude,
        longitude=longitude,
        rating=_rating(record.get("rating")),
        review_count=_review_count(record.get("reviews")),
        price=_clean(record.get("price")),
        category=_category(record),
        hours=hours,
        popular_times_known=_present(record.get("popular_times")),
        website=_http_url(record.get("website")),
        maps_link=_http_url(record.get("gps_link") or record.get("link")),
        thumbnail=_http_url(record.get("thumbnail")),
        events=_events(record.get("events")),
        highlights=highlights,
        provider_language=_language(record.get("language")),
    )
    return place.model_copy(update={"unknown_fields": _unknown(place)})


def _is_duplicate(
    place: DiscoveredPlace,
    seen_place: set[str],
    seen_data: set[str],
    seen_labels: set[tuple[str, str]],
) -> bool:
    if place.place_id and place.place_id in seen_place:
        return True
    if place.data_id and place.data_id in seen_data:
        return True
    label = _label_key(place)
    return label is not None and label in seen_labels


def _remember(
    place: DiscoveredPlace,
    seen_place: set[str],
    seen_data: set[str],
    seen_labels: set[tuple[str, str]],
) -> None:
    if place.place_id:
        seen_place.add(place.place_id)
    if place.data_id:
        seen_data.add(place.data_id)
    label = _label_key(place)
    if label is not None:
        seen_labels.add(label)


def _label_key(place: DiscoveredPlace) -> tuple[str, str] | None:
    name = _normalized_label(place.name)
    address = _normalized_label(place.address)
    if not name or not address:
        return None
    return name, address


def _normalized_label(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(_LABEL.sub(" ", value.casefold()).split())


def _outside_destination(place: DiscoveredPlace, destination: ResolvedDestination) -> bool:
    if (
        place.latitude is None
        or place.longitude is None
        or destination.latitude is None
        or destination.longitude is None
    ):
        return False
    distance = _distance_km(
        place.latitude,
        place.longitude,
        destination.latitude,
        destination.longitude,
    )
    return distance > _DESTINATION_RADIUS_KM


def _distance_km(
    left_latitude: float,
    left_longitude: float,
    right_latitude: float,
    right_longitude: float,
) -> float:
    radius = 6371.0
    phi_left = math.radians(left_latitude)
    phi_right = math.radians(right_latitude)
    delta_phi = math.radians(right_latitude - left_latitude)
    delta_lon = math.radians(right_longitude - left_longitude)
    chord = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_left) * math.cos(phi_right) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius * math.asin(min(1.0, math.sqrt(chord)))


def _overlay_official(place: DiscoveredPlace, record: dict[str, object]) -> None:
    hours = _hours(record)
    if hours:
        place.hours = hours
    if place.address is None:
        place.address = _clean(record.get("address"))
    if place.latitude is None:
        place.latitude, place.longitude = _coordinates(record.get("gps_coordinates"))
    if place.rating is None:
        place.rating = _rating(record.get("rating"))
    if place.review_count is None:
        place.review_count = _review_count(record.get("reviews"))
    if place.price is None:
        place.price = _clean(record.get("price"))
    if place.category is None:
        place.category = _category(record)
    if place.website is None:
        place.website = _http_url(record.get("website"))
    if place.maps_link is None:
        place.maps_link = _http_url(record.get("gps_link") or record.get("link"))
    if place.thumbnail is None:
        place.thumbnail = _http_url(record.get("thumbnail"))
    if not place.events:
        place.events = _events(record.get("events"))
    if _present(record.get("popular_times")):
        place.popular_times_known = True
    if place.provider_language is None:
        place.provider_language = _language(record.get("language"))
    place.unknown_fields = _unknown(place)


def _apply_web(
    place: DiscoveredPlace,
    rows: object,
    destination: ResolvedDestination,
) -> None:
    if not isinstance(rows, list):
        return
    official = ""
    community = ""
    for row in rows:
        if not isinstance(row, dict) or not _matches_entity(row, place, destination):
            continue
        link = _http_url(row.get("link"))
        snippet = _clean(row.get("snippet")) or ""
        host = _host(link)
        if host in _COMMUNITY_HOSTS:
            if snippet and not community:
                community = snippet
            continue
        if (
            place.website
            and link
            and _same_domain(link, place.website)
            and snippet
            and not official
        ):
            official = snippet
    if community and place.hours:
        place.conflicts.append(
            EvidenceConflict(official="; ".join(place.hours), community=community[:200])
        )
    elif community:
        place.community_notes.append(community[:200])
    elif official and not place.hours:
        place.community_notes.append(official[:200])
    place.unknown_fields = _unknown(place)


def _matches_entity(
    row: dict[str, object],
    place: DiscoveredPlace,
    destination: ResolvedDestination,
) -> bool:
    link = _http_url(row.get("link")) or ""
    if place.place_id and place.place_id in link:
        return True
    if place.website and _same_domain(link, place.website):
        return True
    blob = " ".join(
        part for part in (_clean(row.get("title")), _clean(row.get("snippet"))) if part is not None
    ).casefold()
    if place.name.casefold() not in blob:
        return False
    anchors = [place.address, destination.locality, destination.label, destination.serpapi_location]
    return any(anchor and anchor.casefold() in blob for anchor in anchors)


def _web_query(place: DiscoveredPlace, destination: ResolvedDestination) -> str:
    where = destination.locality or destination.label
    return f'"{place.name}" {where} hours'


def _add_highlights(place: DiscoveredPlace, reviews: list[object]) -> None:
    for review in reviews:
        if not isinstance(review, dict):
            continue
        text = _clean(review.get("snippet")) or _clean(review.get("text"))
        if text is None or _PHONE.search(text):
            continue
        if text not in place.highlights:
            place.highlights.append(text[:160])
        if len(place.highlights) == 8:
            break
    place.unknown_fields = _unknown(place)


def _unknown(place: DiscoveredPlace) -> list[str]:
    missing: list[str] = []
    if place.address is None:
        missing.append("address")
    if place.latitude is None:
        missing.append("coordinates")
    if place.rating is None:
        missing.append("rating")
    if place.review_count is None:
        missing.append("review_count")
    if place.price is None:
        missing.append("price")
    if place.category is None:
        missing.append("category")
    if not place.hours:
        missing.append("hours")
    if not place.popular_times_known:
        missing.append("popular_times")
    if place.website is None:
        missing.append("website")
    if place.maps_link is None:
        missing.append("maps_link")
    if place.thumbnail is None:
        missing.append("thumbnail")
    if not place.events:
        missing.append("events")
    if not place.highlights:
        missing.append("highlights")
    if place.provider_language is None:
        missing.append("language")
    return missing


def _inline_highlights(record: dict[str, object]) -> list[str]:
    found: list[str] = []
    description = _clean(record.get("description"))
    if description and not _PHONE.search(description):
        found.append(description[:160])
    reviews = record.get("reviews")
    if isinstance(reviews, list):
        for item in reviews:
            if not isinstance(item, dict):
                continue
            text = _clean(item.get("snippet"))
            if text and text not in found:
                found.append(text[:160])
            if len(found) == 8:
                return found
    extensions = record.get("extensions")
    if isinstance(extensions, list):
        for item in extensions:
            text = _clean(item) if not isinstance(item, dict) else _clean(item.get("title"))
            if text and not _PHONE.search(text) and text not in found:
                found.append(text[:80])
            if len(found) == 8:
                break
    return found


def _hours(record: dict[str, object]) -> list[str]:
    value = record.get("operating_hours")
    if value is None:
        value = record.get("hours")
    lines: list[str] = []
    if isinstance(value, dict):
        for day, span in value.items():
            text = _clean(span)
            label = _clean(day)
            if text and label:
                lines.append(f"{label}: {text}"[:80])
    elif isinstance(value, list):
        for item in value:
            text = _clean(item)
            if text:
                lines.append(text[:80])
    return lines[:8]


def _events(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    titles: list[str] = []
    for item in value:
        text = _clean(item.get("title")) if isinstance(item, dict) else _clean(item)
        if text:
            titles.append(text[:80])
    return titles[:8]


def _category(record: dict[str, object]) -> str | None:
    for key in ("type", "category"):
        text = _clean(record.get(key))
        if text:
            return text[:80]
    types = record.get("types")
    if isinstance(types, list):
        for item in types:
            text = _clean(item)
            if text:
                return text[:80]
    return None


def _coordinates(value: object) -> tuple[float | None, float | None]:
    if not isinstance(value, dict):
        return None, None
    latitude = value.get("latitude")
    longitude = value.get("longitude")
    if (
        isinstance(latitude, int | float)
        and isinstance(longitude, int | float)
        and -90 <= float(latitude) <= 90
        and -180 <= float(longitude) <= 180
    ):
        return float(latitude), float(longitude)
    return None, None


def _rating(value: object) -> float | None:
    if isinstance(value, int | float) and 0 <= float(value) <= 5:
        return float(value)
    return None


def _review_count(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _language(value: object) -> str | None:
    if isinstance(value, str) and value.strip() and len(value.strip()) <= 16:
        return value.strip()
    return None


def _identifier(value: object) -> str | None:
    text = _clean(value)
    if text is None or len(text) > 120:
        return None
    return text


def _http_url(value: object) -> str | None:
    text = _clean(value)
    if text is None:
        return None
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or "api_key" in parsed.query.casefold():
        return None
    return text[:300]


def _host(url: str | None) -> str:
    if not url:
        return ""
    hostname = urlsplit(url).hostname or ""
    return hostname.casefold()


def _same_domain(left: str, right: str) -> bool:
    return _host(left).removeprefix("www.") == _host(right).removeprefix("www.") and bool(
        _host(left)
    )


def _present(value: object) -> bool:
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, list):
        return bool(value)
    return False


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text or _PHONE.search(text):
        return None
    if any(ord(char) < 32 for char in text):
        return None
    return text[:200]
