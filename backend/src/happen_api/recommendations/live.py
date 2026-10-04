"""Live recommendation orchestration. Fixture evidence is never substituted."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import date, datetime

import httpx

from happen_api.ai.prompt import EXTRACTION_SCHEMA_VERSION
from happen_api.catalog import CONTRACT_VERSION, SCORING_POLICY_VERSION
from happen_api.config import Settings
from happen_api.domain.models import NormalizedPlace
from happen_api.domain.timing import KOLKATA
from happen_api.providers.serpapi.client import ProviderSnapshot, SerpApiClient, SerpApiFailure
from happen_api.providers.serpapi.guard import CachedEvidence, LiveGuard
from happen_api.providers.serpapi.normalizer import select_candidates
from happen_api.recommendations.contracts import (
    NormalizedInput,
    Provenance,
    RecommendationRequest,
    RecommendationResponse,
    WarningItem,
)
from happen_api.recommendations.service import RecommendationFailure, payload_hash, score_places

_QUERY = "restaurants in Indiranagar, Bengaluru"
_SERVER_DEADLINE_SECONDS = 28.0
_PROVIDER_DEADLINE_SECONDS = 14.0
_PLACE_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_PLANNING = "Planning evidence—not live occupancy."
_PUBLIC_FAILURES = {
    "LIVE_MODE_DISABLED": (
        503,
        "Live evidence is unavailable.",
        "Use captured evidence, or try again after live evidence is configured.",
        False,
    ),
    "SERPAPI_QUOTA_EXHAUSTED": (
        503,
        "Live evidence is unavailable because the search allowance has been reached.",
        "Use captured evidence. Do not retry until the search allowance is available.",
        False,
    ),
    "SERPAPI_UNAVAILABLE": (
        503,
        "Live place evidence is temporarily unavailable.",
        "Try again.",
        True,
    ),
    "SERPAPI_INVALID_RESPONSE": (
        502,
        "Live place evidence could not be read.",
        "Try again later.",
        False,
    ),
    "PROCESSING_TIMEOUT": (
        504,
        "The request took too long.",
        "Try again.",
        True,
    ),
}
_PROVIDER_CODES = {
    "AUTHENTICATION_FAILED": "LIVE_MODE_DISABLED",
    "QUOTA_EXHAUSTED": "SERPAPI_QUOTA_EXHAUSTED",
    "LIVE_DISABLED": "LIVE_MODE_DISABLED",
    "TRANSIENT_DEPENDENCY": "SERPAPI_UNAVAILABLE",
    "CREDIT_BUDGET_EXCEEDED": "SERPAPI_QUOTA_EXHAUSTED",
    "INVALID_DEPENDENCY_RESPONSE": "SERPAPI_INVALID_RESPONSE",
    "PROVIDER_REJECTED": "SERPAPI_INVALID_RESPONSE",
    "INVALID_REQUEST": "SERPAPI_INVALID_RESPONSE",
}


def recommend_live(
    body: RecommendationRequest,
    *,
    settings: Settings,
    now: datetime,
    generate: Callable[[str], str] | None,
    request_id: str,
    guard: LiveGuard,
    monotonic: Callable[[], float],
    provider_factory: Callable[[int, float], SerpApiClient] | None = None,
    http_client: httpx.Client | None = None,
) -> RecommendationResponse:
    """Retrieve live evidence, score it, and keep provider failures explicit."""

    if not settings.live_configured:
        raise _public_failure("LIVE_MODE_DISABLED")
    started = monotonic()
    _check_deadline(started, monotonic)
    blocked = guard.blocked(started)
    if blocked is not None:
        raise _public_failure(blocked)

    visit_date = _visit_date(body, now)
    cache_key = f"{payload_hash(body)}:{visit_date.isoformat()}"
    cached = guard.get_snapshot(cache_key)
    if cached is not None:
        return _score(
            cached,
            body,
            settings=settings,
            now=now,
            generate=generate,
            request_id=request_id,
            visit_date=visit_date,
            started=started,
            monotonic=monotonic,
        )

    provider_budget = min(_PROVIDER_DEADLINE_SECONDS, _time_left(started, monotonic))
    if provider_budget <= 0:
        raise _public_failure("PROCESSING_TIMEOUT")
    provider = _provider(settings, guard, provider_budget, provider_factory, http_client)
    charged_before = provider.credits_charged
    try:
        evidence = _retrieve(provider, visit_date=visit_date, captured_at=now)
    except SerpApiFailure as exc:
        guard.note_failure(exc.code, monotonic())
        raise _public_failure(_PROVIDER_CODES.get(exc.code, "SERPAPI_UNAVAILABLE")) from None
    except RecommendationFailure:
        raise
    else:
        guard.note_success()
    finally:
        guard.spend(provider.credits_charged - charged_before)
        if getattr(provider, "owns_http", False):
            provider.close()

    guard.save_snapshot(cache_key, evidence)
    return _score(
        evidence,
        body,
        settings=settings,
        now=now,
        generate=generate,
        request_id=request_id,
        visit_date=visit_date,
        started=started,
        monotonic=monotonic,
    )


def fetch_live_evidence(
    *,
    settings: Settings,
    now: datetime,
    guard: LiveGuard,
    monotonic: Callable[[], float] | None = None,
) -> CachedEvidence:
    """Retrieve one bounded live snapshot. Scoring and storage stay with the caller."""

    if not settings.live_configured:
        raise _public_failure("LIVE_MODE_DISABLED")
    clock = monotonic or time.monotonic
    started = clock()
    _check_deadline(started, clock)
    blocked = guard.blocked(started)
    if blocked is not None:
        raise _public_failure(blocked)
    provider_budget = min(_PROVIDER_DEADLINE_SECONDS, _time_left(started, clock))
    if provider_budget <= 0:
        raise _public_failure("PROCESSING_TIMEOUT")
    provider = _provider(settings, guard, provider_budget, None, None)
    charged_before = provider.credits_charged
    try:
        evidence = _retrieve(
            provider,
            visit_date=now.astimezone(KOLKATA).date(),
            captured_at=now,
        )
    except SerpApiFailure as exc:
        guard.note_failure(exc.code, clock())
        raise _public_failure(_PROVIDER_CODES.get(exc.code, "SERPAPI_UNAVAILABLE")) from None
    except RecommendationFailure:
        raise
    else:
        guard.note_success()
    finally:
        guard.spend(provider.credits_charged - charged_before)
        provider.close()
    return evidence


def _retrieve(
    provider: SerpApiClient,
    *,
    visit_date: date,
    captured_at: datetime,
) -> CachedEvidence:
    search_ids: list[str] = []
    search = provider.search_places(_QUERY)
    _remember(search, search_ids)
    shortlist = select_candidates(search.payload, visit_date=visit_date, captured_at=captured_at)
    if shortlist.reason_codes != ["three_candidates"]:
        return _empty(search_ids, shortlist.reason_codes, captured_at)
    details: list[dict[str, object]] = []
    for place in shortlist.places:
        snapshot = _details(provider, place.provider_place_id)
        _remember(snapshot, search_ids)
        details.append(snapshot.payload)
    selected = select_candidates(
        search.payload,
        details,
        visit_date=visit_date,
        captured_at=captured_at,
    )
    if selected.reason_codes != ["three_candidates"]:
        return _empty(search_ids, selected.reason_codes, captured_at)
    review_payloads: list[dict[str, object]] = []
    for place in selected.places:
        if "missing_reviews" not in place.warnings:
            continue
        snapshot = _reviews(provider, place.provider_place_id)
        _remember(snapshot, search_ids)
        review_payloads.append(_review_payload(place.provider_place_id, snapshot))
    if review_payloads:
        selected = select_candidates(
            search.payload,
            details,
            review_payloads,
            visit_date=visit_date,
            captured_at=captured_at,
        )
        if selected.reason_codes != ["three_candidates"]:
            return _empty(search_ids, selected.reason_codes, captured_at)
    return CachedEvidence(
        places=list(selected.places),
        safe_request_ids=_unique(search_ids),
        source_urls=[place.source_url for place in selected.places],
        captured_at=captured_at,
        reason_codes=["three_candidates"],
    )


def _score(
    evidence: CachedEvidence,
    body: RecommendationRequest,
    *,
    settings: Settings,
    now: datetime,
    generate: Callable[[str], str] | None,
    request_id: str,
    visit_date: date,
    started: float,
    monotonic: Callable[[], float],
) -> RecommendationResponse:
    places = [place for place in evidence.places if isinstance(place, NormalizedPlace)]
    if len(places) != 3:
        _check_deadline(started, monotonic)
        return _insufficient_response(
            body,
            settings=settings,
            now=now,
            request_id=request_id,
            visit_date=visit_date,
            evidence=evidence,
        )
    return score_places(
        places,
        body,
        visit_date=visit_date,
        settings=settings,
        now=now,
        generate=generate,
        request_id=request_id,
        provenance=_provenance(evidence, settings, now),
        notices=[WarningItem(code="planning_evidence", message=_PLANNING)],
        before_excerpt=lambda: _check_deadline(started, monotonic),
    )


def _insufficient_response(
    body: RecommendationRequest,
    *,
    settings: Settings,
    now: datetime,
    request_id: str,
    visit_date: date,
    evidence: CachedEvidence,
) -> RecommendationResponse:
    warnings = [WarningItem(code="planning_evidence", message=_PLANNING)]
    warnings.extend(
        WarningItem(code=code, message=_reason_message(code))
        for code in evidence.reason_codes
        if code != "three_candidates"
    )
    return RecommendationResponse(
        request_id=request_id,
        outcome="insufficient_evidence",
        input=_input(body, visit_date),
        provenance=_provenance(evidence, settings, now),
        candidates=[],
        recommendation=None,
        fallback=None,
        warnings=warnings,
        rejected_evidence_count=0,
        duration_ms=0,
        evidence=[],
    )


def _provenance(evidence: CachedEvidence, settings: Settings, now: datetime) -> Provenance:
    captured_at = evidence.captured_at if isinstance(evidence.captured_at, datetime) else now
    return Provenance(
        mode="live",
        captured_at=captured_at,
        generated_at=now,
        timezone="Asia/Kolkata",
        source_count=len(evidence.source_urls),
        source_urls=list(evidence.source_urls),
        safe_request_ids=list(evidence.safe_request_ids),
        model_id=settings.hf_model_repo,
        adapter_id="none",
        extraction_schema_version=EXTRACTION_SCHEMA_VERSION,
        scoring_policy_version=SCORING_POLICY_VERSION,
        fixture_version="none",
        contract_version=CONTRACT_VERSION,
        stale=False,
        data_label="live",
    )


def _provider(
    settings: Settings,
    guard: LiveGuard,
    timeout_seconds: float,
    factory: Callable[[int, float], SerpApiClient] | None,
    http_client: httpx.Client | None,
) -> SerpApiClient:
    credit_limit = min(7, guard.remaining())
    if credit_limit < 1:
        raise _public_failure("SERPAPI_QUOTA_EXHAUSTED")
    if factory is not None:
        return factory(credit_limit, timeout_seconds)
    return SerpApiClient(
        settings.serpapi_api_key.get_secret_value(),
        credit_limit=credit_limit,
        total_timeout_seconds=timeout_seconds,
        http_client=http_client,
    )


def _details(provider: SerpApiClient, provider_id: str) -> ProviderSnapshot:
    if _PLACE_ID.fullmatch(provider_id):
        return provider.place_details(place_id=provider_id)
    return provider.place_details(data_id=provider_id)


def _reviews(provider: SerpApiClient, provider_id: str) -> ProviderSnapshot:
    if _PLACE_ID.fullmatch(provider_id):
        return provider.place_reviews(place_id=provider_id)
    return provider.place_reviews(data_id=provider_id)


def _review_payload(provider_id: str, snapshot: ProviderSnapshot) -> dict[str, object]:
    reviews = snapshot.payload.get("reviews", [])
    return {
        "search_parameters": {"place_id": provider_id},
        "reviews": reviews if isinstance(reviews, list) else [],
    }


def _remember(snapshot: ProviderSnapshot, search_ids: list[str]) -> None:
    if snapshot.search_id:
        search_ids.append(snapshot.search_id)


def _empty(search_ids: list[str], reason_codes: list[str], captured_at: datetime) -> CachedEvidence:
    if "invalid_search" in reason_codes:
        raise _public_failure("SERPAPI_INVALID_RESPONSE")
    return CachedEvidence(
        places=[],
        safe_request_ids=_unique(search_ids),
        source_urls=[],
        captured_at=captured_at,
        reason_codes=list(reason_codes),
    )


def _public_failure(code: str) -> RecommendationFailure:
    status_code, message, next_action, retryable = _PUBLIC_FAILURES[code]
    return RecommendationFailure(
        status_code,
        code,
        message,
        next_action,
        retryable=retryable,
    )


def _input(body: RecommendationRequest, visit_date: date) -> NormalizedInput:
    return NormalizedInput(
        neighborhood=body.neighborhood,
        restaurant_category=body.restaurant_category,
        arrival_start=body.arrival_start,
        arrival_end=body.arrival_end,
        desired_experience=body.desired_experience,
        priorities=[item.value for item in body.priorities],
        visit_date=visit_date,
    )


def _check_deadline(started: float, monotonic: Callable[[], float]) -> None:
    if _time_left(started, monotonic) <= 0:
        raise _public_failure("PROCESSING_TIMEOUT")


def _time_left(started: float, monotonic: Callable[[], float]) -> float:
    return _SERVER_DEADLINE_SECONDS - (monotonic() - started)


def _visit_date(body: RecommendationRequest, now: datetime) -> date:
    if body.visit_date is not None:
        return body.visit_date
    return now.astimezone(KOLKATA).date()


def _reason_message(code: str) -> str:
    messages = {
        "insufficient_candidates": "Fewer than three restaurants could be compared.",
        "empty_search": "The search returned no restaurants.",
        "hours_closed": "A restaurant was closed during the requested time.",
        "category_unknown": "A result did not name a restaurant category.",
        "category_not_restaurant": "A result was not a restaurant.",
        "duplicate_place": "A repeated restaurant was skipped.",
        "missing_source_url": "A result had no source link.",
        "unmatched_place_details": "Place details did not match the search.",
    }
    return messages.get(code, "Live evidence was not complete enough to compare.")


def _unique(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique
