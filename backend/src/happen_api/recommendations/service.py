"""Assemble a fixture recommendation from validated evidence and deterministic scoring."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime, time

from happen_api.ai.extractor import ExtractionError, extract_excerpt
from happen_api.ai.prompt import EXTRACTION_SCHEMA_VERSION
from happen_api.ai.validation import ValidatedExtraction, accepted_scoring_signals
from happen_api.catalog import CONTRACT_VERSION, SCORING_POLICY_VERSION
from happen_api.config import Settings
from happen_api.domain.models import (
    AcceptedSignal,
    ArrivalWindow,
    CandidateEvidence,
    Dimension,
    NormalizedPlace,
    Outcome,
    ReviewExcerpt,
    WindowAssessment,
)
from happen_api.domain.scoring import decide
from happen_api.domain.timing import KOLKATA, generate_arrival_windows, temporal_relevance
from happen_api.fixtures.loader import load_fixture
from happen_api.fixtures.schema import FixtureError, FixtureRequest, LoadedFixture
from happen_api.recommendations.contracts import (
    NormalizedInput,
    Provenance,
    PublicCandidate,
    PublicEvidence,
    PublicWindow,
    RecommendationRequest,
    RecommendationResponse,
    SelectedMoment,
    WarningItem,
)
from happen_api.recommendations.memory import RecommendationMemory

_EXCERPTS_PER_CANDIDATE = 3
_EXCERPTS_PER_RECOMMENDATION = 9


class RecommendationFailure(Exception):
    """A recommendation could not be completed. The message omits paths and secrets."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        next_action: str,
        *,
        retryable: bool,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.next_action = next_action
        self.retryable = retryable
        super().__init__(message)


def recommend_demo(
    body: RecommendationRequest,
    *,
    settings: Settings,
    now: datetime,
    generate: Callable[[str], str] | None,
    memory: RecommendationMemory,
    request_id: str,
) -> RecommendationResponse:
    """Load the matching fixture, reuse a cached result, or score it."""

    try:
        loaded = load_fixture(_fixture_request(body), visit_date=body.visit_date, as_of=now)
    except FixtureError as exc:
        raise _fixture_failure(exc) from None
    cache_key = _cache_key(body, loaded, settings)
    cached = memory.get_result(cache_key)
    if cached is not None:
        return _refresh(cached, request_id=request_id, now=now)
    response = build_recommendation(
        loaded,
        body,
        settings=settings,
        now=now,
        generate=generate,
        request_id=request_id,
    )
    memory.save_result(cache_key, response)
    return response


def build_recommendation(
    loaded: LoadedFixture,
    body: RecommendationRequest,
    *,
    settings: Settings,
    now: datetime,
    generate: Callable[[str], str] | None,
    request_id: str,
) -> RecommendationResponse:
    """Validate excerpts, score windows, and shape the public response."""

    signals_by_candidate: dict[str, list[AcceptedSignal]] = {}
    evidence: list[PublicEvidence] = []
    rejected = 0
    remaining = _EXCERPTS_PER_RECOMMENDATION
    extracted: list[
        tuple[NormalizedPlace, ReviewExcerpt, ValidatedExtraction, list[AcceptedSignal]]
    ] = []
    for place in loaded.places:
        collected: list[AcceptedSignal] = []
        for excerpt in place.review_excerpts[:_EXCERPTS_PER_CANDIDATE]:
            if remaining == 0:
                break
            remaining -= 1
            try:
                validated = extract_excerpt(excerpt, settings=settings, generate=generate)
            except ExtractionError as exc:
                raise RecommendationFailure(
                    503,
                    exc.code,
                    str(exc),
                    "Try again after the evidence model is available.",
                    retryable=True,
                ) from None
            rejected += validated.rejected_signal_count
            if validated.malformed:
                rejected += 1
            accepted = accepted_scoring_signals(validated, excerpt)
            collected.extend(accepted)
            extracted.append((place, excerpt, validated, accepted))
        signals_by_candidate[place.candidate_id] = collected

    candidates = [
        _candidate_evidence(
            place,
            loaded.visit_date,
            body,
            signals_by_candidate[place.candidate_id],
        )
        for place in loaded.places
    ]
    windows_by_candidate = {candidate.candidate_id: candidate.windows for candidate in candidates}
    for place, excerpt, validated, accepted in extracted:
        evidence.extend(
            _public_evidence(
                excerpt,
                validated,
                accepted,
                windows_by_candidate[place.candidate_id],
            )
        )
    decision = decide(candidates, list(body.priorities), as_of=now)
    assessments = {item.window_id: item for item in decision.candidate_assessments}
    public_candidates = [
        _public_candidate(
            place,
            candidate.windows,
            assessments,
            signals_by_candidate[place.candidate_id],
        )
        for place, candidate in zip(loaded.places, candidates, strict=True)
    ]
    names = {place.candidate_id: place.name for place in loaded.places}
    return RecommendationResponse(
        request_id=request_id,
        outcome=decision.outcome,
        input=_input(body, loaded),
        provenance=_provenance(loaded, settings, now),
        candidates=public_candidates,
        recommendation=_selected(decision.primary_window_id, assessments, names),
        fallback=_selected(decision.fallback_window_id, assessments, names),
        warnings=_warnings(loaded, decision.outcome),
        rejected_evidence_count=rejected,
        duration_ms=0,
        evidence=evidence,
    )


def payload_hash(body: RecommendationRequest) -> str:
    """Return a stable hash of the normalized request."""

    encoded = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def refresh_response(
    response: RecommendationResponse,
    *,
    request_id: str,
    now: datetime,
    duration_ms: int,
) -> RecommendationResponse:
    """Keep the decision and replace this request's correlation, clock, and duration."""

    refreshed = _refresh(response, request_id=request_id, now=now)
    return refreshed.model_copy(update={"duration_ms": duration_ms})


def _refresh(
    response: RecommendationResponse,
    *,
    request_id: str,
    now: datetime,
) -> RecommendationResponse:
    return response.model_copy(
        update={
            "request_id": request_id,
            "provenance": response.provenance.model_copy(update={"generated_at": now}),
        }
    )


def _fixture_request(body: RecommendationRequest) -> FixtureRequest:
    return FixtureRequest(
        neighborhood=body.neighborhood,
        restaurant_category=body.restaurant_category,
        arrival_start=body.arrival_start,
        arrival_end=body.arrival_end,
        desired_experience=body.desired_experience,
        priorities=list(body.priorities),
    )


def _fixture_failure(exc: FixtureError) -> RecommendationFailure:
    if exc.code == "FIXTURE_NOT_AVAILABLE" and "matches this request" in str(exc):
        return RecommendationFailure(
            409,
            "FIXTURE_NOT_AVAILABLE",
            "No installed fixture matches this request.",
            "Use the verified Indiranagar dinner preset.",
            retryable=False,
        )
    return RecommendationFailure(
        503,
        "FIXTURE_NOT_AVAILABLE",
        str(exc),
        "Try again after the fixture is available.",
        retryable=True,
    )


def _cache_key(
    body: RecommendationRequest,
    loaded: LoadedFixture,
    settings: Settings,
) -> tuple[str, ...]:
    return (
        "captured_fixture",
        loaded.checksum,
        settings.model_sha256,
        SCORING_POLICY_VERSION,
        EXTRACTION_SCHEMA_VERSION,
        payload_hash(body),
    )


def _candidate_evidence(
    place: NormalizedPlace,
    visit_date: date,
    body: RecommendationRequest,
    signals: list[AcceptedSignal],
) -> CandidateEvidence:
    windows = generate_arrival_windows(
        candidate_id=place.candidate_id,
        visit_date=visit_date,
        arrival_start=time.fromisoformat(body.arrival_start),
        arrival_end=time.fromisoformat(body.arrival_end),
        intervals=place.opening_intervals,
        busyness=place.busyness_observations,
    )
    return CandidateEvidence(
        candidate_id=place.candidate_id,
        name=place.name,
        windows=windows,
        signals=signals,
        busyness=place.busyness_observations,
    )


def _public_candidate(
    place: NormalizedPlace,
    windows: list[ArrivalWindow],
    assessments: dict[str, WindowAssessment],
    signals: list[AcceptedSignal],
) -> PublicCandidate:
    public_windows: list[PublicWindow] = []
    covered: set[Dimension] = set()
    for window in windows:
        assessment = assessments[window.window_id]
        for signal in signals:
            if signal.signal_id in assessment.evidence_refs:
                covered.add(signal.dimension)
        if window.busyness_refs:
            covered.add(Dimension.short_wait)
        public_windows.append(
            PublicWindow(
                window_id=window.window_id,
                arrival_start=_clock(window.starts_at),
                arrival_end=_clock(window.ends_at),
                feasibility="verified_open",
                status=assessment.fit_label,
                fit_label=assessment.fit_label,
                confidence_label=assessment.confidence_label,
                evidence_references=list(assessment.evidence_refs),
                reason_codes=list(assessment.reason_codes),
            )
        )
    missing = [dimension for dimension in Dimension if dimension not in covered]
    count = len(signals)
    summary = f"{count} accepted review signals" if count else "No accepted review evidence"
    return PublicCandidate(
        candidate_id=place.candidate_id,
        name=place.name,
        source_url=place.source_url,
        hours_summary=_hours_summary(place),
        evidence_summary=summary,
        windows=public_windows,
        missing_dimensions=missing,
        warnings=list(place.warnings),
    )


def _public_evidence(
    excerpt: ReviewExcerpt,
    validated: ValidatedExtraction,
    accepted: list[AcceptedSignal],
    windows: list[ArrivalWindow],
) -> list[PublicEvidence]:
    if validated.validation_status == "rejected":
        return []
    by_id = {signal.signal_id: signal for signal in accepted}
    records: list[PublicEvidence] = []
    for index, signal in enumerate(validated.signals, start=1):
        evidence_id = f"{excerpt.excerpt_id}:{index}"
        scoring_signal = by_id.get(evidence_id)
        if scoring_signal is None:
            continue
        records.append(
            PublicEvidence(
                evidence_id=evidence_id,
                dimension=signal.dimension,
                polarity=signal.polarity,
                temporal_hint=signal.temporal_hint,
                quoted_span=signal.quoted_span,
                source_url=excerpt.source_url,
                captured_at=excerpt.captured_at,
                extraction_confidence=signal.confidence,
                validation_status=validated.validation_status,
                candidate_id=excerpt.candidate_id,
                window_ids=_applicable_windows(windows, scoring_signal),
            )
        )
    return records


def _applicable_windows(windows: list[ArrivalWindow], signal: AcceptedSignal) -> list[str]:
    return [
        window.window_id
        for window in windows
        if temporal_relevance(
            signal.temporal_hint,
            signal.temporal_span,
            starts_at=window.starts_at,
            ends_at=window.ends_at,
        )
        > 0
    ]


def _selected(
    window_id: str | None,
    assessments: dict[str, WindowAssessment],
    names: dict[str, str],
) -> SelectedMoment | None:
    if window_id is None:
        return None
    assessment = assessments[window_id]
    candidate_id = assessment.candidate_id
    arrival_start, arrival_end = _bounds_from_window_id(window_id)
    fit_label = assessment.fit_label
    confidence_label = assessment.confidence_label
    return SelectedMoment(
        candidate_id=candidate_id,
        window_id=window_id,
        restaurant_name=names[candidate_id],
        arrival_start=arrival_start,
        arrival_end=arrival_end,
        fit_label=fit_label,
        confidence_label=confidence_label,
        explanation=_explanation(
            names[candidate_id],
            arrival_start,
            arrival_end,
            fit_label.value,
            confidence_label.value,
        ),
        evidence_references=list(assessment.evidence_refs),
    )


def _warnings(loaded: LoadedFixture, outcome: Outcome) -> list[WarningItem]:
    warnings = [
        WarningItem(code="synthetic_development", message=loaded.disclaimer),
    ]
    if loaded.stale:
        warnings.append(
            WarningItem(
                code="stale_evidence",
                message="This evidence is older than seven days.",
            )
        )
    if outcome is Outcome.insufficient_evidence:
        warnings.append(
            WarningItem(
                code="insufficient_evidence",
                message=(
                    "Fewer than two restaurants have enough comparable evidence. "
                    "Use the verified demo set to see a complete comparison."
                ),
            )
        )
    elif outcome is Outcome.partial_evidence:
        warnings.append(
            WarningItem(
                code="partial_evidence",
                message="Some restaurants or times still lack enough evidence.",
            )
        )
    return warnings


def _input(body: RecommendationRequest, loaded: LoadedFixture) -> NormalizedInput:
    return NormalizedInput(
        neighborhood=body.neighborhood,
        restaurant_category=body.restaurant_category,
        arrival_start=body.arrival_start,
        arrival_end=body.arrival_end,
        desired_experience=body.desired_experience,
        priorities=[item.value for item in body.priorities],
        visit_date=loaded.visit_date,
    )


def _provenance(loaded: LoadedFixture, settings: Settings, now: datetime) -> Provenance:
    return Provenance(
        mode="captured_fixture",
        captured_at=loaded.captured_at,
        generated_at=now,
        timezone="Asia/Kolkata",
        source_count=len(loaded.source_urls),
        source_urls=list(loaded.source_urls),
        safe_request_ids=list(loaded.safe_request_ids),
        model_id=settings.hf_model_repo,
        adapter_id="none",
        extraction_schema_version=EXTRACTION_SCHEMA_VERSION,
        scoring_policy_version=SCORING_POLICY_VERSION,
        fixture_version=loaded.fixture_version,
        contract_version=CONTRACT_VERSION,
        stale=loaded.stale,
        data_label=loaded.data_label,
    )


def _hours_summary(place: NormalizedPlace) -> str:
    parts = [
        f"{interval.opens_at.strftime('%H:%M')}–{interval.closes_at.strftime('%H:%M')}"
        for interval in place.opening_intervals
    ]
    return ", ".join(parts)


def _explanation(name: str, start: str, end: str, fit: str, confidence: str) -> str:
    return f"{name} from {start} to {end}. Fit is {fit} and confidence is {confidence}."


def _clock(value: datetime) -> str:
    return value.astimezone(KOLKATA).strftime("%H:%M")


def _bounds_from_window_id(window_id: str) -> tuple[str, str]:
    stamp = window_id.rsplit("T", 1)[-1]
    hour, minute = stamp.split(":")
    start = time(int(hour), int(minute))
    end_minutes = start.hour * 60 + start.minute + 30
    end = time(end_minutes // 60, end_minutes % 60)
    return start.strftime("%H:%M"), end.strftime("%H:%M")
