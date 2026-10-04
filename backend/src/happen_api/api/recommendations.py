"""Live recommendation route. A provider failure does not load fixture evidence."""

from __future__ import annotations

import re
import time
from datetime import datetime

from fastapi import APIRouter, Header, Request

from happen_api.domain.timing import KOLKATA
from happen_api.errors import error_response
from happen_api.middleware import current_request_id
from happen_api.providers.serpapi.guard import LiveGuard
from happen_api.recommendations.contracts import RecommendationRequest, RecommendationResponse
from happen_api.recommendations.live import recommend_live
from happen_api.recommendations.memory import MemoryError, RecommendationMemory
from happen_api.recommendations.service import RecommendationFailure, payload_hash, refresh_response

router = APIRouter()
_IDEMPOTENCY_KEY = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@router.post("/api/v1/recommendations", response_model=RecommendationResponse)
def recommendations(
    body: RecommendationRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RecommendationResponse | object:
    """Score current SerpApi evidence. Fixture mode is a separate endpoint."""

    if idempotency_key is None or not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        return _failure(
            request,
            status_code=422,
            code="INVALID_INPUT",
            message="The request is not valid.",
            next_action="Send a new idempotency key.",
            retryable=False,
            fields=[{"field": "Idempotency-Key", "message": "Provide a new idempotency key."}],
        )
    memory: RecommendationMemory = request.app.state.recommendation_memory
    settings = request.app.state.settings
    started = time.perf_counter()
    reserved = False
    finished = False
    try:
        replay = memory.begin(
            idempotency_key,
            payload_hash(body),
            client=_client(request),
            limit=settings.recommendation_rate_limit,
            window_seconds=settings.recommendation_rate_window_seconds,
        )
        if replay is not None:
            return _timed(
                replay, request_id=current_request_id(), now=_now(request), started=started
            )
        reserved = True
        result = recommend_live(
            body,
            settings=settings,
            now=_now(request),
            generate=request.app.state.excerpt_generate,
            request_id=current_request_id(),
            guard=_guard(request),
            monotonic=_monotonic(request),
            provider_factory=request.app.state.provider_factory,
        )
        memory.finish(idempotency_key, payload_hash(body), result)
        finished = True
        return _timed(result, request_id=current_request_id(), now=_now(request), started=started)
    except MemoryError as exc:
        return _failure(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            next_action=exc.next_action,
            retryable=exc.retryable,
            retry_after_seconds=exc.retry_after_seconds,
        )
    except RecommendationFailure as exc:
        return _failure(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            next_action=exc.next_action,
            retryable=exc.retryable,
        )
    finally:
        if reserved and not finished:
            memory.abort(idempotency_key)


def _guard(request: Request) -> LiveGuard:
    guard = request.app.state.live_guard
    if isinstance(guard, LiveGuard):
        return guard
    created = LiveGuard(budget=request.app.state.settings.serpapi_search_budget)
    request.app.state.live_guard = created
    return created


def _monotonic(request: Request):
    clock = request.app.state.monotonic
    if clock is None:
        return time.monotonic
    return clock


def _timed(
    response: RecommendationResponse,
    *,
    request_id: str,
    now: datetime,
    started: float,
) -> RecommendationResponse:
    duration_ms = int((time.perf_counter() - started) * 1000)
    return refresh_response(response, request_id=request_id, now=now, duration_ms=duration_ms)


def _now(request: Request) -> datetime:
    clock = request.app.state.clock
    if clock is None:
        return datetime.now(KOLKATA)
    current = clock()
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        return datetime.now(KOLKATA)
    return current.astimezone(KOLKATA)


def _client(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host


def _failure(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    next_action: str,
    retryable: bool,
    fields: list[dict[str, str]] | None = None,
    retry_after_seconds: int | None = None,
) -> object:
    return error_response(
        status_code=status_code,
        request_id=current_request_id(),
        code=code,
        message=message,
        retryable=retryable,
        next_action=next_action,
        fixture_available=bool(request.app.state.fixture_available),
        fields=fields,
        retry_after_seconds=retry_after_seconds,
    )
