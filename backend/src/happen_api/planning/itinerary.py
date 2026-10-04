"""Choose one or two evening stops from retrieved places.

Selection, hours checks, and tie handling stay in Python. Verified fit is the
score. Provider order is only the tie-breaker when that fit is equal. This
module does not call a model and does not invent a travel duration.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from happen_api.planning.clock import Clock
from happen_api.planning.contracts import (
    BriefConfidence,
    BriefField,
    EssentialField,
    FollowUp,
    IntentKind,
    PlaceIntent,
    PlanningBrief,
)
from happen_api.planning.discovery import DiscoveredPlace
from happen_api.planning.follow_up import question_for, select_follow_up
from happen_api.planning.interpret import interpret

_DAY = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"
_HOURS = re.compile(rf"(?i)^({_DAY})\s*:\s*(\d{{1,2}}:\d{{2}})\s*[-–—]\s*(\d{{1,2}}:\d{{2}})$")
_CLOSED_DAY = re.compile(rf"(?i)^({_DAY})\s*:\s*closed$")
_OPEN_FIT = 100
_UNKNOWN_FIT = 20
_WEBSITE_FIT = 4
_MAPS_FIT = 2
_CONSTRAINT_FIT = 8
_CONSTRAINT_TERMS: dict[str, tuple[str, ...]] = {
    "quiet": ("quiet", "calm", "peaceful"),
    "vegetarian": ("vegetarian",),
    "vegan": ("vegan",),
    "romantic": ("romantic",),
    "outdoor seating": ("outdoor", "patio", "terrace"),
    "casual": ("casual",),
    "formal": ("formal",),
    "spicy": ("spicy",),
}


class EvidenceSource(StrEnum):
    """Where one explanation came from."""

    official = "official"
    maps = "maps"
    community = "community"


class PlanEvidence(BaseModel):
    """One traceable statement used to explain a stop."""

    model_config = ConfigDict(extra="forbid")

    source: EvidenceSource
    text: str = Field(min_length=1, max_length=300)
    url: HttpUrl | None = None
    retrieved_at: datetime


class PlanStop(BaseModel):
    """One selected place. The response has no numeric score."""

    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=1, le=2)
    intent: IntentKind
    label: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    place_id: str | None = Field(default=None, max_length=200)
    data_id: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    latitude: float | None = None
    longitude: float | None = None
    maps_link: HttpUrl | None = None
    website: HttpUrl | None = None
    confidence: Literal["high", "medium", "low"]
    hours_status: Literal["open", "unknown"]
    price: str | None = Field(default=None, max_length=40)
    busyness: Literal["listed", "unknown"] = "unknown"
    rating: float | None = None
    explanation: str = Field(min_length=1, max_length=300)
    evidence: list[PlanEvidence] = Field(max_length=8)
    unknown_fields: list[str] = Field(default_factory=list, max_length=8)
    warnings: list[str] = Field(default_factory=list, max_length=4)


class PlanTransition(BaseModel):
    """A link between two stops. Travel time stays absent until a source states it."""

    model_config = ConfigDict(extra="forbid")

    from_stop: int = Field(ge=1, le=2)
    to_stop: int = Field(ge=1, le=2)
    status: Literal["unverified"]
    directions_url: HttpUrl


class EveningPlan(BaseModel):
    """A source-backed evening of one or two stops."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["2"] = "2"
    outcome: Literal["planned", "no_results", "insufficient_evidence"]
    local_date: date
    local_start: time
    stops: list[PlanStop] = Field(default_factory=list, max_length=2)
    transition: PlanTransition | None = None
    warnings: list[str] = Field(default_factory=list, max_length=8)
    retrieved_at: datetime


class FieldChange(BaseModel):
    """One brief value that a proposal would replace."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=40)
    before: str | None = Field(default=None, max_length=200)
    after: str | None = Field(default=None, max_length=200)


class BriefDiff(BaseModel):
    """What a proposal would add, remove, or change. Nothing is applied here."""

    model_config = ConfigDict(extra="forbid")

    added: list[str] = Field(default_factory=list, max_length=12)
    removed: list[str] = Field(default_factory=list, max_length=12)
    changed: list[FieldChange] = Field(default_factory=list, max_length=12)


class RefinementProposal(BaseModel):
    """A validated next brief. The caller keeps the current plan until it applies this."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["2"] = "2"
    applied: Literal[False] = False
    current: PlanningBrief
    proposed: PlanningBrief
    follow_up: FollowUp | None = None
    diff: BriefDiff
    message: str = "The current plan was not changed."


def hours_status(
    place: DiscoveredPlace, local_date: date, arrival: time
) -> Literal["open", "closed", "unknown"]:
    """Return open, closed, or unknown for one destination-local arrival."""

    if not place.hours:
        return "unknown"
    parsed = _parse_hours(place.hours)
    weekday = local_date.strftime("%A").lower()
    if not parsed:
        if _listed_closed(place.hours, weekday):
            return "closed"
        return "unknown"
    previous = (local_date - timedelta(days=1)).strftime("%A").lower()
    for day, start, end in parsed:
        if end > start and day == weekday and start <= arrival < end:
            return "open"
        if end <= start and day == weekday and arrival >= start:
            return "open"
        if end <= start and day == previous and arrival < end:
            return "open"
    return "closed"


def constraint_terms(preferences: Sequence[str]) -> tuple[str, ...]:
    """Return requested preferences that review text can support."""

    found: list[str] = []
    for item in preferences:
        key = item.casefold().strip()
        if key in _CONSTRAINT_TERMS and key not in found:
            found.append(key)
    return tuple(found)


def constraint_supported(place: DiscoveredPlace, preference: str) -> bool:
    """Return whether place text already shows one requested constraint."""

    terms = _CONSTRAINT_TERMS.get(preference.casefold().strip(), ())
    if not terms:
        return False
    blob = " ".join([*place.highlights, *place.community_notes]).casefold()
    return any(term in blob for term in terms)


def unmet_constraint_gain(place: DiscoveredPlace, preferences: Sequence[str]) -> int:
    """Return the fit a review could still add for requested constraints."""

    return _CONSTRAINT_FIT * sum(
        1 for item in constraint_terms(preferences) if not constraint_supported(place, item)
    )


def verified_fit(
    place: DiscoveredPlace,
    state: Literal["open", "closed", "unknown"],
    preferences: Sequence[str] = (),
) -> int:
    """Score listed evidence. A missing field adds nothing.

    Open hours outrank unknown hours. A listed website, Maps link, rating, or
    supported constraint adds its own points. Closed hours do not.
    """

    if state == "open":
        score = _OPEN_FIT
    elif state == "unknown":
        score = _UNKNOWN_FIT
    else:
        score = 0
    if place.website is not None:
        score += _WEBSITE_FIT
    if place.maps_link is not None:
        score += _MAPS_FIT
    if place.rating is not None:
        score += round(place.rating * 10)
    for preference in constraint_terms(preferences):
        if constraint_supported(place, preference):
            score += _CONSTRAINT_FIT
    return score


def selection_key(
    place: DiscoveredPlace,
    *,
    local_date: date,
    arrival: time,
    preferences: Sequence[str] | None = None,
) -> tuple[int, int, str, str]:
    """Order one place. Provider rank breaks ties and is not the main score.

    The first value is verified fit. When that fit is equal, the earlier
    provider result wins. When that rank is also equal, the casefolded name
    and then the place id keep the order stable.
    """

    accepted = preferences or ()
    return (
        -verified_fit(place, hours_status(place, local_date, arrival), accepted),
        place.provider_rank,
        place.name.casefold(),
        place.place_id or place.data_id or "",
    )


def assemble_itinerary(
    places: list[DiscoveredPlace],
    intents: list[PlaceIntent],
    *,
    local_date: date,
    local_start: time,
    retrieved_at: datetime,
    preferences: list[str] | None = None,
) -> EveningPlan:
    """Select at most one place for each of up to two intents."""

    warnings: list[str] = []
    if not places:
        return EveningPlan(
            outcome="no_results",
            local_date=local_date,
            local_start=local_start,
            warnings=["No live places matched this evening."],
            retrieved_at=retrieved_at,
        )
    stops: list[PlanStop] = []
    for intent in intents[:2]:
        open_or_unknown = [
            (place, state)
            for place in places
            if place.intent == intent.kind
            and (place.place_id or place.data_id)
            and (state := hours_status(place, local_date, local_start)) != "closed"
        ]
        if not open_or_unknown:
            warnings.append(f"No open place matched {intent.label}.")
            continue
        place, state = min(
            open_or_unknown,
            key=lambda item: selection_key(
                item[0],
                local_date=local_date,
                arrival=local_start,
                preferences=preferences,
            ),
        )
        stops.append(_stop(place, intent, state, local_date, local_start, retrieved_at))
    outcome: Literal["planned", "no_results", "insufficient_evidence"] = (
        "planned" if stops else "insufficient_evidence"
    )
    if outcome == "insufficient_evidence":
        warnings.append("No open place had enough evidence for this evening.")
    return EveningPlan(
        outcome=outcome,
        local_date=local_date,
        local_start=local_start,
        stops=stops,
        transition=_transition(stops),
        warnings=warnings,
        retrieved_at=retrieved_at,
    )


def propose_revision(current: PlanningBrief, revision: str, clock: Clock) -> RefinementProposal:
    """Interpret a revision and return the diff without changing the current brief."""

    parsed = interpret(revision, clock).brief
    merged = _merge(current, parsed)
    return RefinementProposal(
        current=current,
        proposed=merged,
        follow_up=select_follow_up(merged),
        diff=_diff(current, merged),
    )


def _merge(current: PlanningBrief, revision: PlanningBrief) -> PlanningBrief:
    data = revision.model_dump()
    if revision.destination_text is None and not _blocking(revision, BriefField.destination):
        data["destination_text"] = current.destination_text
    if (
        revision.local_date is None
        and revision.pending_date is None
        and not _blocking(revision, BriefField.date)
    ):
        data["local_date"] = current.local_date
        data["pending_date"] = current.pending_date.model_dump() if current.pending_date else None
    if revision.local_start is None and not _blocking(revision, BriefField.time):
        data["local_start"] = current.local_start
    if revision.party_size is None:
        data["party_size"] = current.party_size
    if revision.budget is None:
        data["budget"] = current.budget.model_dump() if current.budget else None
    if not revision.intents and not _blocking(revision, BriefField.primary_intent):
        data["intents"] = [item.model_dump() for item in current.intents]
    if not revision.preferences:
        data["preferences"] = list(current.preferences)
    missing = []
    if not data["destination_text"]:
        missing.append(question_for(EssentialField.destination))
    if data["local_date"] is None and data["pending_date"] is None:
        missing.append(question_for(EssentialField.date))
    if data["local_start"] is None:
        missing.append(question_for(EssentialField.time))
    if not data["intents"]:
        missing.append(question_for(EssentialField.primary_intent))
    data["missing_essentials"] = [item.model_dump() for item in missing]
    data["ambiguities"] = [item.model_dump() for item in revision.ambiguities]
    data["confidence"] = (
        BriefConfidence.low if missing or revision.ambiguities else BriefConfidence.high
    )
    return PlanningBrief.model_validate(data)


def _blocking(revision: PlanningBrief, field: BriefField) -> bool:
    return any(item.blocking and item.field is field for item in revision.ambiguities)


def _diff(current: PlanningBrief, proposed: PlanningBrief) -> BriefDiff:
    added: list[str] = []
    removed: list[str] = []
    changed: list[FieldChange] = []
    pairs = (
        ("destination", current.destination_text, proposed.destination_text),
        ("date", _date_text(current), _date_text(proposed)),
        ("time", _time_text(current.local_start), _time_text(proposed.local_start)),
        ("intent", _intent_text(current), _intent_text(proposed)),
        ("preferences", _joined(current.preferences), _joined(proposed.preferences)),
    )
    for field, before, after in pairs:
        if before == after:
            continue
        if before is None:
            added.append(field)
        elif after is None:
            removed.append(field)
        else:
            changed.append(FieldChange(field=field, before=before, after=after))
    return BriefDiff(added=added, removed=removed, changed=changed)


def _date_text(brief: PlanningBrief) -> str | None:
    if brief.local_date is not None:
        return brief.local_date.isoformat()
    if brief.pending_date is not None:
        return brief.pending_date.phrase.value
    return None


def _time_text(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def _intent_text(brief: PlanningBrief) -> str | None:
    if not brief.intents:
        return None
    return ", ".join(item.label for item in brief.intents)


def _joined(values: list[str]) -> str | None:
    return ", ".join(values) if values else None


def _listed_closed(lines: list[str], weekday: str) -> bool:
    for line in lines:
        match = _CLOSED_DAY.match(line.strip())
        if match is not None and match.group(1).lower() == weekday:
            return True
    return False


def _stop(
    place: DiscoveredPlace,
    intent: PlaceIntent,
    state: str,
    local_date: date,
    arrival: time,
    retrieved_at: datetime,
) -> PlanStop:
    evidence: list[PlanEvidence] = []
    warnings: list[str] = []
    unknown = [field for field in ("price", "popular_times") if field in place.unknown_fields]
    if state == "open":
        explanation = f"Maps hours cover {arrival.strftime('%H:%M')} on {local_date.isoformat()}."
        confidence: Literal["high", "medium", "low"] = "high" if place.website else "medium"
        hours: Literal["open", "unknown"] = "open"
    else:
        explanation = "Opening hours were not listed, so this stop is less certain."
        confidence = "low"
        hours = "unknown"
        warnings.append(explanation)
    for line in place.hours[:4]:
        evidence.append(
            PlanEvidence(
                source=EvidenceSource.maps,
                text=line[:300],
                url=_http(place.maps_link),
                retrieved_at=retrieved_at,
            )
        )
    website = _http(place.website)
    if website is not None:
        evidence.append(
            PlanEvidence(
                source=EvidenceSource.official,
                text="Official site listed for this place.",
                url=website,
                retrieved_at=retrieved_at,
            )
        )
    for note in place.community_notes[:2]:
        evidence.append(
            PlanEvidence(
                source=EvidenceSource.community,
                text=note[:300],
                url=None,
                retrieved_at=retrieved_at,
            )
        )
    if place.conflicts:
        warnings.append("An official hours statement and a community statement disagree.")
    return PlanStop(
        position=intent.position,
        intent=intent.kind,
        label=intent.label,
        name=place.name,
        place_id=place.place_id,
        data_id=place.data_id,
        address=place.address,
        latitude=place.latitude,
        longitude=place.longitude,
        maps_link=_http(place.maps_link),
        website=website,
        confidence=confidence,
        hours_status=hours,
        price=place.price,
        busyness="listed" if place.popular_times_known else "unknown",
        rating=place.rating,
        explanation=explanation,
        evidence=evidence[:8],
        unknown_fields=unknown,
        warnings=warnings[:4],
    )


def _transition(stops: list[PlanStop]) -> PlanTransition | None:
    if len(stops) != 2:
        return None
    origin = _point(stops[0])
    destination = _point(stops[1])
    url = (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote(origin)}&destination={quote(destination)}"
    )
    return PlanTransition(
        from_stop=stops[0].position,
        to_stop=stops[1].position,
        status="unverified",
        directions_url=HttpUrl(url),
    )


def _point(stop: PlanStop) -> str:
    if stop.latitude is not None and stop.longitude is not None:
        return f"{stop.latitude},{stop.longitude}"
    return stop.name


def _http(value: str | None) -> HttpUrl | None:
    if value is None or not value.startswith(("http://", "https://")):
        return None
    try:
        return HttpUrl(value)
    except ValidationError:
        return None


def _parse_hours(lines: list[str]) -> list[tuple[str, time, time]]:
    parsed: list[tuple[str, time, time]] = []
    for line in lines:
        match = _HOURS.match(line.strip())
        if match is None:
            continue
        start = _clock(match.group(2))
        end = _clock(match.group(3))
        if start is None or end is None:
            continue
        parsed.append((match.group(1).lower(), start, end))
    return parsed


def _clock(value: str) -> time | None:
    hour_text, minute_text = value.split(":")
    hour = int(hour_text)
    minute = int(minute_text)
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def local_arrival(moment: datetime, timezone_name: str) -> tuple[date, time]:
    """Convert one aware instant into a destination-local date and clock time."""

    local = moment.astimezone(ZoneInfo(timezone_name))
    return local.date(), local.timetz().replace(tzinfo=None)
