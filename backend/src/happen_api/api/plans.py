"""Versioned planning routes. v1 recommendations stay registered separately."""

from __future__ import annotations

import hashlib
from datetime import date, time

import anyio
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from happen_api.errors import error_response
from happen_api.middleware import current_request_id
from happen_api.planning.clock import Clock, SystemClock
from happen_api.planning.contracts import (
    PendingDate,
    PlaceIntent,
    PlanningBrief,
    PlanningInputError,
    PlanningPromptRequest,
    ResolvedDestination,
)
from happen_api.planning.destination import (
    PLAN_BILLED_REQUEST_LIMIT,
    DestinationResolution,
    ResolutionStatus,
    resolve_destination,
)
from happen_api.planning.discovery import (
    CandidatePool,
    DiscoveryStatus,
    discover_places,
    discovery_cache_key,
)
from happen_api.planning.interpret import interpret
from happen_api.planning.itinerary import (
    assemble_itinerary,
    propose_revision,
)
from happen_api.planning.limits import PlanCache, PlanningThrottle
from happen_api.providers.serpapi.client import SerpApiClient, SerpApiFailure

router = APIRouter(prefix="/api/v2", tags=["plans"])


class ResolveRequest(BaseModel):
    """One destination query. Relative dates stay on the caller until a zone exists."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=120)
    pending_date: str | None = Field(default=None, pattern="^(today|tomorrow)$")
    local_date: date | None = None
    local_start: time | None = None

    @field_validator("query")
    @classmethod
    def _query(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("query is empty")
        return cleaned


class PlanRequest(BaseModel):
    """One resolved destination and the evening the caller wants to plan."""

    model_config = ConfigDict(extra="forbid")

    destination: ResolvedDestination
    intents: list[PlaceIntent] = Field(min_length=1, max_length=2)
    local_date: date
    local_start: time
    local_end: time | None = None
    preferences: list[str] = Field(default_factory=list, max_length=8)
    prior_billed_requests: int = Field(default=0, ge=0, le=PLAN_BILLED_REQUEST_LIMIT)

    @model_validator(mode="after")
    def _one_zone_and_ordered_intents(self) -> PlanRequest:
        if self.destination.timezone_name is None:
            raise ValueError("a plan needs one destination timezone")
        positions = [item.position for item in self.intents]
        if positions != list(range(1, len(positions) + 1)):
            raise ValueError("intent positions must be 1..n in order")
        if self.local_end is not None and self.local_end <= self.local_start:
            raise ValueError("local_end must be later than local_start")
        return self


class RefineRequest(BaseModel):
    """A current brief plus a revision. The current brief is not replaced."""

    model_config = ConfigDict(extra="forbid")

    current: PlanningBrief
    revision: str = Field(min_length=1, max_length=2000)


class _Unavailable:
    """A user-safe response produced before a provider client exists."""

    def __init__(self, response: object) -> None:
        self.response = response


class _Spent:
    """Reports credits already used by destination resolution plus new calls."""

    def __init__(self, inner: object, prior: int) -> None:
        self._inner = inner
        self._prior = prior

    @property
    def credits_charged(self) -> int:
        return self._prior + int(getattr(self._inner, "credits_charged", 0))

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


@router.post("/briefs/interpret")
def interpret_brief(body: PlanningPromptRequest, request: Request) -> object:
    """Read one prompt. This route does not retrieve places."""

    rejected = _begin(request, billed=False)
    if rejected is not None:
        return rejected
    try:
        return interpret(body.prompt, _clock(request))
    except PlanningInputError as exc:
        return _failure(
            request,
            422,
            exc.error.code.value,
            exc.error.message,
            exc.error.next_action,
            retryable=exc.error.retryable,
        )


@router.post("/destinations/resolve")
def resolve_place(body: ResolveRequest, request: Request) -> object:
    """Resolve one destination. Several matches stay as choices."""

    rejected = _begin(request, billed=True)
    if rejected is not None:
        return rejected
    client, owned = _client(request, PLAN_BILLED_REQUEST_LIMIT)
    if isinstance(client, _Unavailable):
        _end(request, billed=True)
        return client.response
    try:
        pending = PendingDate(phrase=body.pending_date) if body.pending_date else None
        resolution = resolve_destination(
            body.query,
            client,  # type: ignore[arg-type]
            clock=_clock(request),
            pending_date=pending,
            local_date=body.local_date,
            local_start=body.local_start,
        )
    except SerpApiFailure as exc:
        return _provider_failure(request, exc)
    finally:
        _close(client, owned)
        _end(request, billed=True)
    if resolution.status is ResolutionStatus.ambiguous:
        return _json(resolution, 409)
    if resolution.status is ResolutionStatus.budget_exhausted:
        return _failure(
            request,
            503,
            "QUOTA_EXHAUSTED",
            "The search allowance for this plan has been reached.",
            "Try again later.",
            retryable=False,
        )
    return resolution


@router.post("/plans")
def create_plan(body: PlanRequest, request: Request) -> object:
    """Discover places and select one or two stops. A model does not choose."""

    rejected = _begin(request, billed=True)
    if rejected is not None:
        return rejected
    remaining = PLAN_BILLED_REQUEST_LIMIT - body.prior_billed_requests
    if remaining < 1:
        _end(request, billed=True)
        return _failure(
            request,
            503,
            "QUOTA_EXHAUSTED",
            "The search allowance for this plan has been reached.",
            "Try again later.",
            retryable=False,
        )
    cache_key = discovery_cache_key(
        body.destination,
        local_date=body.local_date,
        start_time=body.local_start,
        end_time=body.local_end,
        intents=body.intents,
        preferences=body.preferences,
    )
    cached = _plan_cache(request).get(cache_key)
    if cached is not None:
        _end(request, billed=True)
        return assemble_itinerary(
            cached.places,
            body.intents,
            local_date=body.local_date,
            local_start=body.local_start,
            retrieved_at=_clock(request).now(),
            preferences=body.preferences,
        )
    client, owned = _client(request, remaining)
    if isinstance(client, _Unavailable):
        _end(request, billed=True)
        return client.response
    viewed = _Spent(client, body.prior_billed_requests)
    try:
        found = discover_places(
            body.destination,
            body.intents,
            viewed,  # type: ignore[arg-type]
            local_date=body.local_date,
            start_time=body.local_start,
            end_time=body.local_end,
            retrieved_at=_clock(request).now(),
            preferences=body.preferences,
        )
    except SerpApiFailure as exc:
        return _provider_failure(request, exc)
    finally:
        _close(client, owned)
        _end(request, billed=True)
    if found.places and found.stopped not in {DiscoveryStatus.timeout, DiscoveryStatus.quota}:
        _plan_cache(request).put(cache_key, CandidatePool(places=found.places))
    if found.status is DiscoveryStatus.timeout and not found.places:
        return _failure(
            request,
            504,
            "TIMEOUT",
            "Live place evidence did not respond in time.",
            "Try again.",
            retryable=True,
        )
    if found.status is DiscoveryStatus.quota and not found.places:
        return _failure(
            request,
            503,
            "QUOTA_EXHAUSTED",
            "The search allowance for this plan has been reached.",
            "Try again later.",
            retryable=False,
        )
    plan = assemble_itinerary(
        found.places,
        body.intents,
        local_date=body.local_date,
        local_start=body.local_start,
        retrieved_at=found.retrieved_at,
        preferences=body.preferences,
    )
    if found.stopped is DiscoveryStatus.timeout:
        plan.warnings.append("Some place evidence did not respond in time.")
    if found.stopped is DiscoveryStatus.quota:
        plan.warnings.append("The search allowance stopped further lookups.")
    return plan


@router.post("/plans/refine")
def refine_plan(body: RefineRequest, request: Request) -> object:
    """Return a proposed brief and a diff. The current brief stays as sent."""

    rejected = _begin(request, billed=False)
    if rejected is not None:
        return rejected
    try:
        return propose_revision(body.current, body.revision, _clock(request))
    except PlanningInputError as exc:
        return _failure(
            request,
            422,
            exc.error.code.value,
            exc.error.message,
            exc.error.next_action,
            retryable=exc.error.retryable,
        )


def _begin(request: Request, *, billed: bool) -> object | None:
    settings = request.app.state.settings
    throttle: PlanningThrottle = request.app.state.planning_throttle
    retry_after = throttle.start(
        _caller(request),
        limit=settings.recommendation_rate_limit,
        window_seconds=settings.recommendation_rate_window_seconds,
        billed=billed,
    )
    if retry_after is None:
        return None
    return _failure(
        request,
        429,
        "RATE_LIMITED",
        "Happen is handling too many planning requests.",
        "Wait and try again.",
        retryable=True,
        retry_after_seconds=retry_after,
    )


def _end(request: Request, *, billed: bool) -> None:
    throttle: PlanningThrottle = request.app.state.planning_throttle
    throttle.finish(billed)


def _plan_cache(request: Request) -> PlanCache:
    return request.app.state.plan_cache


def _caller(request: Request) -> str:
    host = request.client.host if request.client is not None else "unknown"
    return hashlib.sha256(host.encode("utf-8")).hexdigest()


def _disconnected(request: Request) -> bool:
    try:
        return bool(anyio.from_thread.run(request.is_disconnected))
    except RuntimeError:
        return False


def _clock(request: Request) -> Clock:
    clock: Clock | None = getattr(request.app.state, "clock", None)
    if clock is None:
        return SystemClock()
    return clock


def _client(request: Request, credit_limit: int) -> tuple[object, bool]:
    factory = getattr(request.app.state, "provider_factory", None)
    if factory is not None:
        return factory(credit_limit, 14.0), False
    settings = request.app.state.settings
    if not settings.live_configured:
        return (
            _Unavailable(
                _failure(
                    request,
                    503,
                    "QUOTA_EXHAUSTED",
                    "Live place evidence is not configured.",
                    "Try again later.",
                    retryable=False,
                )
            ),
            False,
        )
    http_client = getattr(request.app.state, "http_client", None)
    client = SerpApiClient(
        settings.serpapi_api_key.get_secret_value(),
        credit_limit=credit_limit,
        http_client=http_client,
        cancelled=lambda: _disconnected(request),
    )
    return client, http_client is None


def _close(client: object, owned: bool) -> None:
    if owned and hasattr(client, "close"):
        client.close()


def _provider_failure(request: Request, exc: SerpApiFailure) -> object:
    if exc.code == "TRANSIENT_DEPENDENCY":
        return _failure(
            request,
            504,
            "TIMEOUT",
            "Live place evidence did not respond in time.",
            "Try again.",
            retryable=True,
        )
    if exc.code in {"QUOTA_EXHAUSTED", "CREDIT_BUDGET_EXCEEDED"}:
        return _failure(
            request,
            503,
            "QUOTA_EXHAUSTED",
            "The search allowance for this plan has been reached.",
            "Try again later.",
            retryable=False,
        )
    if exc.code == "INVALID_REQUEST":
        return _failure(
            request,
            422,
            "INVALID_INPUT",
            "The destination could not be read.",
            "Correct the destination and try again.",
            retryable=False,
        )
    return _failure(
        request,
        503,
        "NO_RESULT",
        "The place search could not be completed.",
        "Try again.",
        retryable=True,
    )


def _failure(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    next_action: str,
    *,
    retryable: bool,
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
        retry_after_seconds=retry_after_seconds,
    )


def _json(resolution: DestinationResolution, status_code: int) -> object:
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(resolution.model_dump(mode="json")),
        headers={"X-Content-Type-Options": "nosniff"},
    )
