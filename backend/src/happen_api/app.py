"""Application factory. Invalid settings fail before the app is returned."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from happen_api import __version__
from happen_api.ai.extractor import release_model
from happen_api.api.demo import router as demo_router
from happen_api.api.health import router
from happen_api.api.plans import router as plan_router
from happen_api.api.recommendations import router as live_router
from happen_api.config import Settings, get_settings
from happen_api.errors import error_response, message_for, public_field_errors
from happen_api.logging import configure_logging, get_logger
from happen_api.middleware import BodyLimitMiddleware, RequestContextMiddleware, current_request_id
from happen_api.planning.limits import AllowanceStore, PlanCache, PlanningThrottle
from happen_api.providers.serpapi.guard import LiveGuard
from happen_api.readiness import captured_fixture_status
from happen_api.recommendations.memory import RecommendationMemory


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Open the shared SerpApi HTTP client and close it when the app stops."""

    client = httpx.Client(trust_env=False, follow_redirects=False, timeout=httpx.Timeout(8.0))
    application.state.http_client = client
    try:
        yield
    finally:
        client.close()
        release_model()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API with validated settings, request limits, CORS, and error handlers."""

    resolved = settings if settings is not None else get_settings()
    configure_logging(resolved.log_level)
    application = FastAPI(
        title="Happen",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )
    application.state.settings = resolved
    application.state.started_at = time.monotonic()
    _, fixture_ready = captured_fixture_status()
    # Production does not advertise a captured fixture as a user-facing fallback.
    application.state.fixture_available = fixture_ready and resolved.app_env != "production"
    application.state.recommendation_memory = RecommendationMemory()
    application.state.planning_throttle = PlanningThrottle()
    application.state.plan_cache = PlanCache()
    application.state.plan_allowances = AllowanceStore()
    application.state.live_guard = LiveGuard(budget=resolved.serpapi_search_budget)
    application.state.excerpt_generate = None
    application.state.provider_factory = None
    application.state.clock = None
    application.state.monotonic = None

    application.add_middleware(
        BodyLimitMiddleware,
        fixture_available=bool(application.state.fixture_available),
    )
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key"],
        expose_headers=[],
    )
    application.include_router(router)
    if resolved.app_env != "production":
        application.include_router(demo_router)
        application.include_router(live_router)
    application.include_router(plan_router)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    return application


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> object:
    """Translate an HTTP exception into the public error envelope."""

    code, message, next_action, retryable = message_for(exc.status_code)
    return error_response(
        status_code=exc.status_code,
        request_id=current_request_id(),
        code=code,
        message=message,
        retryable=retryable,
        next_action=next_action,
        fixture_available=bool(request.app.state.fixture_available),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> object:
    """Return validation errors with field locations and no submitted values."""

    code, message, next_action, retryable = message_for(422)
    return error_response(
        status_code=422,
        request_id=current_request_id(),
        code=code,
        message=message,
        retryable=retryable,
        next_action=next_action,
        fixture_available=bool(request.app.state.fixture_available),
        fields=public_field_errors(list(exc.errors())),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> object:
    """Log the exception type and return a generic retryable error response."""

    get_logger().error(
        "request failed",
        extra={
            "request_id": current_request_id(),
            "endpoint": request.url.path,
            "status_code": 500,
            "error_code": "INTERNAL_ERROR",
            "exception_type": type(exc).__name__,
        },
    )
    code, message, next_action, retryable = message_for(500)
    return error_response(
        status_code=500,
        request_id=current_request_id(),
        code=code,
        message=message,
        retryable=retryable,
        next_action=next_action,
        fixture_available=bool(request.app.state.fixture_available),
    )
