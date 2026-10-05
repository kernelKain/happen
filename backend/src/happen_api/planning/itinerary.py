"""Choose one or two evening stops from retrieved places.

Selection, hours checks, and tie handling stay in Python. Verified fit is the
score. Provider order is only the tie-breaker when that fit is equal. This
module does not call a model and does not invent a travel duration.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time
from enum import StrEnum
from typing import Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from happen_api.domain.hours import (
    ProviderHours,
    day_intervals,
    hours_reason,
    hours_state,
    schedule_from_lines,
)
from happen_api.planning.clock import Clock
from happen_api.planning.constraints import (
    EveningConstraints,
    Finding,
    assess,
    blocks_selection,
    constraint_points,
    hard_unverified,
    known_phrases,
    review_gain,
)
from happen_api.planning.contracts import (
    BriefConfidence,
    BriefField,
    EssentialField,
    FollowUp,
    IntentKind,
    PlaceIntent,
    PlanningBrief,
)
from happen_api.planning.discovery import DiscoveredPlace, _community_claim_for
from happen_api.planning.evidence import (
    ClaimField,
    EvidenceClaim,
    MatchMethod,
    Verification,
    safe_link,
)
from happen_api.planning.follow_up import question_for, select_follow_up
from happen_api.planning.interpret import interpret

_OPEN_FIT = 100
_UNKNOWN_FIT = 20
_WEBSITE_FIT = 4
_MAPS_FIT = 2


class EvidenceSource(StrEnum):
    """Where one explanation came from."""

    official = "official"
    maps = "maps"
    community = "community"


class PlanEvidence(BaseModel):
    """One traceable statement used to explain a stop.

    The claim carries its provenance: which kind of source it came from, what it
    supports, how the entity was matched, and whether it is verified. An
    unverified claim is shown as context, never as a fact.
    """

    model_config = ConfigDict(extra="forbid")

    source: EvidenceSource
    text: str = Field(min_length=1, max_length=300)
    url: HttpUrl | None = None
    retrieved_at: datetime
    field: ClaimField = ClaimField.description
    matched_by: MatchMethod = MatchMethod.none_found
    verification: Verification = Verification.unverified

    @classmethod
    def from_claim(cls, claim: EvidenceClaim) -> PlanEvidence:
        """Project a normalized claim into the response evidence shape."""

        return cls(
            source=EvidenceSource(claim.kind.value),
            text=claim.text,
            url=claim.url,
            retrieved_at=claim.retrieved_at,
            field=claim.field,
            matched_by=claim.matched_by,
            verification=claim.verification,
        )


class ConstraintAssessment(BaseModel):
    """Whether one requested constraint was verified for a stop."""

    model_config = ConfigDict(extra="forbid")

    constraint: str = Field(min_length=1, max_length=40)
    status: Literal["met", "unmet", "unknown", "not_applicable"]
    evidence: list[PlanEvidence] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _cite(self) -> ConstraintAssessment:
        cited = self.status in {"met", "unmet"}
        if cited and not self.evidence:
            raise ValueError("a met or unmet constraint cites evidence")
        if not cited and self.evidence:
            raise ValueError("an unknown constraint does not cite support")
        return self


class ScoringComponent(BaseModel):
    """One named check. The customer response has no numeric value."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    result: Literal["supports", "neutral", "unknown", "blocks"]
    detail: str = Field(min_length=1, max_length=200)


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
    constraints: list[ConstraintAssessment] = Field(default_factory=list, max_length=18)
    components: list[ScoringComponent] = Field(default_factory=list, max_length=18)
    unknown_fields: list[str] = Field(default_factory=list, max_length=8)
    warnings: list[str] = Field(default_factory=list, max_length=4)
    hours_reason: str | None = Field(default=None, max_length=40)
    arrival_planned: bool = True
    closes_at: time | None = None
    hours_for_day: str | None = Field(default=None, max_length=300)
    weekly_hours: list[str] = Field(default_factory=list, max_length=7)


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
    party_size: int | None = Field(default=None, ge=1, le=20)
    warnings: list[str] = Field(default_factory=list, max_length=8)
    retrieved_at: datetime
    billed_requests: int = Field(default=0, ge=0)
    remaining_requests: int = Field(default=0, ge=0)


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


class RefinementPurpose(StrEnum):
    """Which of the two refinement actions this request is.

    `follow_up` is the same submitted plan asking one more essential question,
    so it keeps the current plan identity and its remaining allowance.
    `plan_refinement` is a newly submitted plan, so it starts a fresh
    eight-request allowance and receives its own plan identity.
    """

    follow_up = "follow_up"
    plan_refinement = "plan_refinement"


class RefinementProposal(BaseModel):
    """A validated next brief. The caller keeps the current plan until it applies this."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["2"] = "2"
    applied: Literal[False] = False
    purpose: RefinementPurpose = RefinementPurpose.follow_up
    current: PlanningBrief
    proposed: PlanningBrief
    follow_up: FollowUp | None = None
    diff: BriefDiff
    message: str = "The current plan was not changed."


def hours_status(
    place: DiscoveredPlace, local_date: date, arrival: time
) -> Literal["open", "closed", "unknown"]:
    """Return open, closed, or unknown for one destination-local arrival.

    The decision reads the canonical schedule, never the display strings. A
    place that is definitely closed for that arrival is excluded. Hours that
    could not be normalized stay unknown rather than being guessed open.
    """

    return hours_state(place_schedule(place), local_date=local_date, arrival=arrival)


def place_schedule(place: DiscoveredPlace) -> ProviderHours | None:
    """Return the canonical schedule for one place, normalizing text if needed.

    Places built by the provider boundary already carry a normalized schedule.
    A place assembled elsewhere still normalizes its own display lines, so no
    second parser is needed and no caller silently loses its hours.
    """

    if place.hours_schedule is not None:
        return place.hours_schedule
    if not place.hours:
        return None
    return schedule_from_lines(place.hours)


def hours_decision_reason(place: DiscoveredPlace, local_date: date, arrival: time) -> str:
    """Return the structured reason behind one place's hours decision."""

    return hours_reason(place_schedule(place), local_date=local_date, arrival=arrival)


def constraint_terms(preferences: Sequence[str]) -> tuple[str, ...]:
    """Return requested phrases that review text can support."""

    return tuple(known_phrases(preferences))


def constraint_supported(place: DiscoveredPlace, preference: str) -> bool:
    """Return whether place text already verifies one requested constraint."""

    if preference.casefold().strip() not in set(known_phrases([preference])):
        return False
    return any(item.status == "met" for item in assess(place, _bundle([preference])))


def unmet_constraint_gain(
    place: DiscoveredPlace,
    preferences: Sequence[str] | EveningConstraints,
) -> int:
    """Return the fit a review could still add. Unknown evidence adds nothing."""

    return review_gain(place, _bundle(preferences))


def verified_fit(
    place: DiscoveredPlace,
    state: Literal["open", "closed", "unknown"],
    preferences: Sequence[str] | EveningConstraints = (),
) -> int:
    """Rank listed evidence. A missing field adds nothing.

    Open hours outrank unknown hours by more than any constraint bonus.
    A listed website, Maps link, or rating adds its own points. A constraint
    adds points only when the text verifies it. Closed hours do not.
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
    score += constraint_points(place, _bundle(preferences))
    return score


def selection_key(
    place: DiscoveredPlace,
    *,
    local_date: date,
    arrival: time,
    preferences: Sequence[str] | None = None,
    constraints: EveningConstraints | None = None,
) -> tuple[int, int, str, str]:
    """Order one place. Provider rank breaks ties and is not the main score.

    The first value is verified fit. A hard contradiction sorts last. When
    that fit is equal, the earlier provider result wins. When that rank is
    also equal, the casefolded name and then the place id keep the order stable.
    """

    bundle = constraints if constraints is not None else _bundle(preferences)
    state = hours_status(place, local_date, arrival)
    fit = 0 if blocks_selection(place, bundle) else verified_fit(place, state, bundle)
    return (
        -fit,
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
    constraints: EveningConstraints | None = None,
) -> EveningPlan:
    """Select at most one place for each of up to two intents."""

    bundle = constraints if constraints is not None else _bundle(preferences)
    warnings: list[str] = []
    if not places:
        return EveningPlan(
            outcome="no_results",
            local_date=local_date,
            local_start=local_start,
            party_size=bundle.party_size,
            warnings=["No live places matched this evening."],
            retrieved_at=retrieved_at,
        )
    stops: list[PlanStop] = []
    hard_missing = False
    blocked = False
    for intent in intents[:2]:
        open_or_unknown = [
            (place, state)
            for place in places
            if place.intent == intent.kind
            and (place.place_id or place.data_id)
            and (state := hours_status(place, local_date, local_start)) != "closed"
        ]
        eligible = [
            (place, state)
            for place, state in open_or_unknown
            if not blocks_selection(place, bundle)
        ]
        if not eligible:
            if open_or_unknown:
                blocked = True
                missing = [
                    name
                    for place, _state in open_or_unknown
                    for name in hard_unverified(assess(place, bundle))
                ]
                warnings.extend(_named_warnings(missing))
            else:
                warnings.append(f"No open place matched {intent.label}.")
            continue
        place, state = min(
            eligible,
            key=lambda item: selection_key(
                item[0],
                local_date=local_date,
                arrival=local_start,
                constraints=bundle,
            ),
        )
        findings = assess(place, bundle)
        missing = hard_unverified(findings)
        if missing:
            hard_missing = True
            warnings.extend(_named_warnings(missing))
        stops.append(
            _stop(
                place,
                intent,
                state,
                local_date,
                local_start,
                retrieved_at,
                findings,
                arrival_verified=intent.position == 1,
            )
        )
    outcome: Literal["planned", "no_results", "insufficient_evidence"] = "planned"
    if not stops:
        outcome = "insufficient_evidence"
        if not blocked:
            warnings.append("No open place had enough evidence for this evening.")
    elif hard_missing:
        outcome = "insufficient_evidence"
    return EveningPlan(
        outcome=outcome,
        local_date=local_date,
        local_start=local_start,
        stops=stops,
        transition=_transition(stops),
        party_size=bundle.party_size,
        warnings=_unique(warnings)[:8],
        retrieved_at=retrieved_at,
    )


def propose_revision(
    current: PlanningBrief,
    revision: str,
    clock: Clock,
    *,
    purpose: RefinementPurpose = RefinementPurpose.follow_up,
) -> RefinementProposal:
    """Interpret a revision and return the diff without changing the current brief.

    A `follow_up` is the same plan asking one more question, so it keeps the
    current plan identity and the allowance that identity has left. A
    `plan_refinement` is a newly submitted plan, so it receives a fresh
    eight-request allowance and the server issues a new identity for it.

    The plan identity is never taken from the request body. It is copied from
    the brief the server already issued, so a caller cannot raise its own
    budget by naming a token.
    """

    parsed = interpret(revision, clock).brief
    merged = _merge(current, parsed)
    if purpose is RefinementPurpose.follow_up:
        # Answering the destination question must continue on the same plan,
        # otherwise the follow-up response would invalidate the session.
        data = merged.model_dump()
        data["plan_token"] = current.plan_token
        merged = PlanningBrief.model_validate(data)
    return RefinementProposal(
        current=current,
        proposed=merged,
        purpose=purpose,
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
    if not revision.accessibility_needs:
        data["accessibility_needs"] = list(current.accessibility_needs)
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
        ("party size", _party_text(current.party_size), _party_text(proposed.party_size)),
        ("budget", _budget_text(current), _budget_text(proposed)),
        ("intent", _intent_text(current), _intent_text(proposed)),
        ("preferences", _joined(current.preferences), _joined(proposed.preferences)),
        (
            "accessibility",
            _joined(current.accessibility_needs),
            _joined(proposed.accessibility_needs),
        ),
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


def _party_text(value: int | None) -> str | None:
    return str(value) if value is not None else None


def _budget_text(brief: PlanningBrief) -> str | None:
    budget = brief.budget
    if budget is None:
        return None
    if budget.amount is not None and budget.currency:
        bound = budget.bound.value if budget.bound is not None else "amount"
        return f"{bound} {budget.amount} {budget.currency}"
    if budget.tier is not None:
        return budget.tier.value
    return None


def _stop(
    place: DiscoveredPlace,
    intent: PlaceIntent,
    state: str,
    local_date: date,
    arrival: time,
    retrieved_at: datetime,
    findings: list[Finding] | None = None,
    *,
    arrival_verified: bool = True,
) -> PlanStop:
    evidence: list[PlanEvidence] = []
    warnings: list[str] = []
    unknown = [field for field in ("price", "popular_times") if field in place.unknown_fields]
    maps_link = safe_link(place.maps_link)
    day_line = _day_line(place.hours, local_date)
    # Maps hours stay Maps evidence even when an official site exists. The
    # planned weekday is the only row that bears on this evening.
    for line in [day_line] if day_line else place.hours[:3]:
        evidence.append(
            PlanEvidence(
                source=EvidenceSource.maps,
                text=line[:300],
                url=maps_link,
                retrieved_at=retrieved_at,
                field=ClaimField.hours,
                matched_by=MatchMethod.place_record,
                verification=Verification.verified if state == "open" else Verification.unverified,
            )
        )
    website = safe_link(place.website)
    if website is not None:
        evidence.append(
            PlanEvidence(
                source=EvidenceSource.official,
                text="Official site listed for this place.",
                url=website,
                retrieved_at=retrieved_at,
                field=ClaimField.provenance,
                matched_by=MatchMethod.official_domain,
                verification=Verification.verified,
            )
        )
    for claim in place.claims[:4]:
        evidence.append(PlanEvidence.from_claim(claim))
    for note in place.community_notes[:2]:
        if any(item.text == note for item in evidence):
            continue
        evidence.append(
            PlanEvidence(
                source=EvidenceSource.community,
                text=note[:300],
                url=None,
                retrieved_at=retrieved_at,
                field=ClaimField.description,
                matched_by=MatchMethod.none_found,
                verification=Verification.unverified,
            )
        )
    if place.claim_conflicts:
        warnings.append("One source lists different opening hours than another.")
    reason = hours_decision_reason(place, local_date, arrival)
    if state == "open":
        clock = arrival.strftime("%H:%M")
        if arrival_verified:
            explanation = f"Maps hours cover {clock} on {local_date.isoformat()}."
        else:
            explanation = (
                f"Maps hours list this place open at {clock} on {local_date.isoformat()}. "
                "A separate arrival was not planned for this stop."
            )
        confidence: Literal["high", "medium", "low"] = "high" if place.website else "medium"
        hours: Literal["open", "unknown"] = "open"
    else:
        explanation = "Opening hours were not listed, so this stop is less certain."
        confidence = "low"
        hours = "unknown"
        warnings.append(explanation)
    checked = findings or []
    assessments = [_assessment(item, place, retrieved_at) for item in checked]
    if hard_unverified(checked):
        confidence = "low"
    for item in assessments:
        if len(evidence) >= 8:
            break
        evidence.extend(item.evidence[: 8 - len(evidence)])
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
        maps_link=maps_link,
        website=website,
        confidence=confidence,
        hours_status=hours,
        price=place.price,
        busyness="listed" if place.popular_times_known else "unknown",
        rating=place.rating,
        explanation=explanation,
        evidence=evidence[:8],
        constraints=assessments,
        components=_components(hours, reason, checked),
        unknown_fields=unknown,
        warnings=warnings[:4],
        hours_reason=reason[:40],
        arrival_planned=arrival_verified,
        closes_at=_closes_at(place, local_date, arrival) if hours == "open" else None,
        hours_for_day=day_line[:300] if day_line else None,
        weekly_hours=[line[:300] for line in place.hours[:7]],
    )


def _day_line(lines: Sequence[str], local_date: date) -> str | None:
    """Return the provider's hours row for the planned weekday, if it names one."""

    name = local_date.strftime("%A").casefold()
    for line in lines:
        label = line.split(":", 1)[0].strip().casefold().rstrip(".")
        if label and (label == name or (len(label) >= 3 and name.startswith(label))):
            return line
    return None


def _closes_at(place: DiscoveredPlace, local_date: date, arrival: time) -> time | None:
    """Return the listed closing time of the interval that covers the arrival."""

    for interval in day_intervals(place_schedule(place), local_date):
        if interval.opens_at == interval.closes_at:
            return None
        if interval.overnight:
            if arrival >= interval.opens_at:
                return interval.closes_at
        elif interval.opens_at <= arrival < interval.closes_at:
            return interval.closes_at
    return None


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


def _bundle(value: Sequence[str] | EveningConstraints | None) -> EveningConstraints:
    if isinstance(value, EveningConstraints):
        return value
    return EveningConstraints(preferences=list(value or ()))


def _assessment(
    item: Finding, place: DiscoveredPlace, retrieved_at: datetime
) -> ConstraintAssessment:
    evidence: list[PlanEvidence] = []
    if item.text and item.source and item.status in {"met", "unmet"}:
        source = EvidenceSource.maps if item.source == "maps" else EvidenceSource.community
        url = (
            safe_link(place.maps_link)
            if item.source == "maps"
            else _cited_claim_url(place, item.text)
        )
        claim = _community_claim_for(place, item.text)
        evidence.append(
            PlanEvidence(
                source=source,
                text=item.text[:300],
                url=url,
                retrieved_at=retrieved_at,
                field=ClaimField.constraint,
                matched_by=claim.matched_by if claim is not None else MatchMethod.place_record,
                verification=Verification.unverified,
            )
        )
    return ConstraintAssessment(constraint=item.constraint, status=item.status, evidence=evidence)


def _cited_claim_url(place: DiscoveredPlace, text: str) -> HttpUrl | None:
    """Return the safe URL the cited community passage came from."""

    claim = _community_claim_for(place, text)
    return claim.url if claim is not None else None


def _components(
    hours: Literal["open", "unknown"], reason: str, findings: list[Finding]
) -> list[ScoringComponent]:
    detail = (
        f"Hours: opening hours cover this arrival ({reason})."
        if hours == "open"
        else f"Hours: opening hours were not listed ({reason})."
    )
    rows = [
        ScoringComponent(
            name="hours", result="supports" if hours == "open" else "unknown", detail=detail
        )
    ]
    for item in findings:
        rows.append(
            ScoringComponent(
                name=item.constraint[:40],
                result=_component_result(item.status),
                detail=_component_detail(item.constraint, item.status),
            )
        )
    return rows[:18]


def _component_result(status: str) -> Literal["supports", "neutral", "unknown", "blocks"]:
    if status == "met":
        return "supports"
    if status == "unmet":
        return "blocks"
    if status == "not_applicable":
        return "neutral"
    return "unknown"


def _component_detail(name: str, status: str) -> str:
    label = name[:1].upper() + name[1:] if name else name
    if status == "met":
        return f"{label} was verified from the retrieved evidence."
    if status == "unmet":
        return f"{label} was not supported by the retrieved evidence."
    if status == "not_applicable":
        return f"{label} does not apply to this stop."
    return f"{label} was not shown in the retrieval."


def _named_warnings(labels: list[str]) -> list[str]:
    notes: list[str] = []
    for label in labels:
        note = f"{label} was requested and was not verified."
        if note not in notes:
            notes.append(note)
    return notes


def _unique(items: list[str]) -> list[str]:
    found: list[str] = []
    for item in items:
        if item not in found:
            found.append(item)
    return found


def local_arrival(moment: datetime, timezone_name: str) -> tuple[date, time]:
    """Convert one aware instant into a destination-local date and clock time."""

    local = moment.astimezone(ZoneInfo(timezone_name))
    return local.date(), local.timetz().replace(tzinfo=None)
