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
from happen_api.planning.constraints import EveningConstraints
from happen_api.planning.contracts import (
    Budget,
    PendingDate,
    PlaceIntent,
    PlanningBrief,
    PlanningInputError,
    PlanningPromptRequest,
    ResolvedDestination,
)
from happen_api.planning.deadline import (
    DESTINATION_SECONDS,
    PLANNING_DEADLINE_SECONDS,
    DeadlineExceeded,
    PlanningDeadline,
    Stage,
)
from happen_api.planning.destination import (
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
    RefinementPurpose,
    assemble_itinerary,
    propose_revision,
)
from happen_api.planning.limits import (
    PLAN_BILLED_REQUEST_LIMIT,
    AllowanceError,
    AllowanceStore,
    MeteredProvider,
    PlanCache,
    PlanningThrottle,
)
from happen_api.providers.serpapi.client import SerpApiClient, SerpApiFailure

router = APIRouter(prefix="/api/v2", tags=["plans"])


class ResolveRequest(BaseModel):
    """One destination query. Relative dates stay on the caller until a zone exists."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=120)
    pending_date: str | None = Field(default=None, pattern="^(today|tomorrow)$")
    local_date: date | None = None
    local_start: time | None = None
    plan_token: str = Field(min_length=16, max_length=128)

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
    party_size: int | None = Field(default=None, ge=1, le=20)
    budget: Budget | None = None
    preferences: list[str] = Field(default_factory=list, max_length=8)
    accessibility_needs: list[str] = Field(default_factory=list, max_length=8)
    plan_token: str = Field(min_length=16, max_length=128)

    @field_validator("preferences", "accessibility_needs")
    @classmethod
    def _phrases(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item or len(item) > 40:
                raise ValueError("constraint text is too long")
            if any(ord(char) < 32 and char not in "\n\t\r" for char in item):
                raise ValueError("constraint text contains a control character")
        return value

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
    """One current brief plus a revision, and which of the two actions this is.

    `plan_token` is accepted for symmetry with the other planning routes, but
    it is never trusted. The server resolves the plan identity from the brief
    it already issued, so a browser cannot raise its own allowance.
    """

    model_config = ConfigDict(extra="forbid")

    current: PlanningBrief
    revision: str = Field(min_length=1, max_length=2000)
    purpose: RefinementPurpose = RefinementPurpose.follow_up
    plan_token: str | None = Field(default=None, min_length=16, max_length=128)


class _Unavailable:
    """A user-safe response produced before a provider client exists."""

    def __init__(self, response: object) -> None:
        self.response = response


@router.post("/briefs/interpret")
def interpret_brief(body: PlanningPromptRequest, request: Request) -> object:
    """Read one prompt. This route does not retrieve places.

    It issues the opaque token that the next two calls must present. Reading a
    prompt is free; the token is not a credential and grants nothing by itself.
    """

    rejected = _begin(request, billed=False)
    if rejected is not None:
        return rejected
    try:
        response = interpret(body.prompt, _clock(request))
    except PlanningInputError as exc:
        return _failure(
            request,
            422,
            exc.error.code.value,
            exc.error.message,
            exc.error.next_action,
            retryable=exc.error.retryable,
        )
    response.brief.plan_token = _allowances(request).issue()
    return response


@router.post("/destinations/resolve")
def resolve_place(body: ResolveRequest, request: Request) -> object:
    """Resolve one destination. Several matches stay as choices.

    The billed lookups come out of the plan's own allowance, so destination
    resolution and discovery share one budget rather than each getting eight.
    """

    rejected = _begin(request, billed=True)
    if rejected is not None:
        return rejected
    denied = _unknown_token(request, body.plan_token)
    if denied is not None:
        _end(request, billed=True)
        return denied
    deadline = _deadline(request)
    metered, owned = _metered(request, body.plan_token, deadline)
    if isinstance(metered, _Unavailable):
        _end(request, billed=True)
        return metered.response
    client = metered
    try:
        pending = PendingDate(phrase=body.pending_date) if body.pending_date else None
        with deadline.stage(Stage.destination, DESTINATION_SECONDS):
            resolution = resolve_destination(
                body.query,
                client,  # type: ignore[arg-type]
                clock=_clock(request),
                pending_date=pending,
                local_date=body.local_date,
                local_start=body.local_start,
            )
    except DeadlineExceeded:
        _end(request, billed=True)
        return _timed_out(request)
    except AllowanceError:
        _end(request, billed=True)
        return _exhausted(request)
    except SerpApiFailure as exc:
        return _provider_failure(request, exc)
    finally:
        _close(client, owned)
        _end(request, billed=True)
    if resolution.status is ResolutionStatus.ambiguous:
        return _json(_stamp(resolution, _allowances(request), body.plan_token), 409)
    if resolution.status is ResolutionStatus.budget_exhausted:
        return _failure(
            request,
            503,
            "QUOTA_EXHAUSTED",
            "The search allowance for this plan has been reached.",
            "Try again later.",
            retryable=False,
        )
    return _stamp(resolution, _allowances(request), body.plan_token)


@router.post("/plans")
def create_plan(body: PlanRequest, request: Request) -> object:
    """Discover places and select one or two stops. A model does not choose."""

    rejected = _begin(request, billed=True)
    if rejected is not None:
        return rejected
    denied = _unknown_token(request, body.plan_token)
    if denied is not None:
        _end(request, billed=True)
        return denied
    constraints = _constraints(body)
    cache_key = discovery_cache_key(
        body.destination,
        local_date=body.local_date,
        start_time=body.local_start,
        end_time=body.local_end,
        intents=body.intents,
    )
    store = _allowances(request)
    cached = _plan_cache(request).get(cache_key)
    if cached is not None:
        _end(request, billed=True)
        # A recomputation sends nothing, so it costs nothing.
        plan = assemble_itinerary(
            cached.places,
            body.intents,
            local_date=body.local_date,
            local_start=body.local_start,
            retrieved_at=_clock(request).now(),
            constraints=constraints,
        )
        return _stamp(plan, store, body.plan_token)
    metered, owned = _metered(request, body.plan_token, _deadline(request))
    if isinstance(metered, _Unavailable):
        _end(request, billed=True)
        return metered.response
    client = metered
    try:
        found = discover_places(
            body.destination,
            body.intents,
            client,  # type: ignore[arg-type]
            local_date=body.local_date,
            start_time=body.local_start,
            end_time=body.local_end,
            retrieved_at=_clock(request).now(),
            constraints=constraints,
        )
    except AllowanceError:
        _end(request, billed=True)
        return _exhausted(request)
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
        constraints=constraints,
    )
    if found.stopped is DiscoveryStatus.timeout:
        plan.warnings.append("Some place evidence did not respond in time.")
    if found.stopped is DiscoveryStatus.quota:
        plan.warnings.append("The search allowance stopped further lookups.")
    return _stamp(plan, store, body.plan_token)


@router.post("/plans/refine")
def refine_plan(body: RefineRequest, request: Request) -> object:
    """Return a proposed brief and a diff. The current brief stays as sent.

    A `follow_up` continues the current plan, so its plan identity and its
    remaining allowance survive. A `plan_refinement` is the user accepting a
    post-result change, which the contract treats as a newly submitted plan, so
    it receives a fresh eight-request allowance under a new plan identity.
    """

    rejected = _begin(request, billed=False)
    if rejected is not None:
        return rejected
    store = _allowances(request)
    try:
        proposal = propose_revision(
            body.current,
            body.revision,
            _clock(request),
            purpose=body.purpose,
        )
    except PlanningInputError as exc:
        return _failure(
            request,
            422,
            exc.error.code.value,
            exc.error.message,
            exc.error.next_action,
            retryable=exc.error.retryable,
        )
    if body.purpose is RefinementPurpose.plan_refinement:
        current_token = proposal.current.plan_token
        token = store.issue()
        data = proposal.proposed.model_dump()
        data["plan_token"] = token
        proposal = proposal.model_copy(update={"proposed": PlanningBrief.model_validate(data)})
        # The previous plan's identity is spent once its refinement is applied.
        if current_token is not None and current_token != token:
            store.forget(current_token)
    return proposal


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


def _allowances(request: Request) -> AllowanceStore:
    return request.app.state.plan_allowances


def _unknown_token(request: Request, token: str) -> object | None:
    """Refuse an unknown, expired, or malformed token before any provider call."""

    store = _allowances(request)
    try:
        store.remaining(token)
    except AllowanceError:
        return _failure(
            request,
            403,
            "PLAN_TOKEN_INVALID",
            "This plan session is no longer valid.",
            "Start a new search.",
            retryable=False,
        )
    return None


def _exhausted(request: Request) -> object:
    return _failure(
        request,
        503,
        "QUOTA_EXHAUSTED",
        "The search allowance for this plan has been reached.",
        "Try again later.",
        retryable=False,
    )


def _timed_out(request: Request) -> object:
    """The shared planning deadline ran out before the answer was complete."""

    return _failure(
        request,
        504,
        "TIMEOUT",
        "Live place evidence did not respond in time.",
        "Try again.",
        retryable=True,
    )


def _stamp(plan: object, store: AllowanceStore, token: str) -> object:
    """Stamp a response with this plan's real spend and what is left.

    The count comes from the store, never from the request body, so a caller
    cannot lower its own reported spend.
    """

    try:
        plan.billed_requests = store.spent(token)
        plan.remaining_requests = store.remaining(token)
    except AllowanceError:
        plan.billed_requests = 0
        plan.remaining_requests = 0
    return plan


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


def _deadline(request: Request) -> PlanningDeadline:
    """Build the one monotonic budget that every stage of this request shares.

    A caller that disconnected cancels the request. The deadline is monotonic,
    so a host clock change cannot lengthen or shorten it, and it is passed to
    the provider so no stage can restart its own clock.
    """

    return PlanningDeadline(
        budget_seconds=PLANNING_DEADLINE_SECONDS,
        cancel=lambda: _disconnected(request),
    ).start()


def _metered(
    request: Request, token: str, deadline: PlanningDeadline | None = None
) -> tuple[object, bool]:
    """Build a provider client whose every outbound attempt draws on this plan.

    The allowance gate is installed on the inner client, not on a wrapper, so a
    retry inside that client claims its own request. The shared deadline is
    installed beside it and runs first, so an attempt the caller cancelled or
    the budget stopped is never sent and never charged. A scripted test
    provider without either gate is charged per billed call instead.
    """

    factory = getattr(request.app.state, "provider_factory", None)
    if factory is not None:
        built = factory(PLAN_BILLED_REQUEST_LIMIT, 14.0)
        # A test factory may hand back a bare client or a (client, owned) pair.
        if isinstance(built, tuple):
            inner, owned = built
        else:
            inner, owned = built, False
    else:
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
        inner = SerpApiClient(
            settings.serpapi_api_key.get_secret_value(),
            credit_limit=PLAN_BILLED_REQUEST_LIMIT,
            http_client=http_client,
            cancelled=lambda: _disconnected(request),
        )
        owned = http_client is None
    if deadline is not None:
        # The send gate runs before the allowance gate, so work the deadline or
        # a disconnection stopped never reaches the network and costs nothing.
        setter = getattr(inner, "set_send_gate", None)
        if callable(setter):
            setter(lambda: deadline.allow_send())
        cap = getattr(inner, "set_attempt_cap", None)
        if callable(cap):
            cap(DESTINATION_SECONDS)
    return MeteredProvider(inner, _allowances(request), token), owned


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


def _constraints(body: PlanRequest) -> EveningConstraints:
    return EveningConstraints(
        party_size=body.party_size,
        budget=body.budget,
        preferences=list(body.preferences),
        accessibility_needs=list(body.accessibility_needs),
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
