"""Application factory. Invalid settings fail before the app is returned."""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from happen_api import __version__
from happen_api.api.health import router
from happen_api.config import Settings, get_settings
from happen_api.errors import error_response, message_for, public_field_errors
from happen_api.logging import configure_logging, get_logger
from happen_api.middleware import BodyLimitMiddleware, RequestContextMiddleware, current_request_id


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings if settings is not None else get_settings()
    configure_logging(resolved.log_level)
    application = FastAPI(
        title="Happen",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.settings = resolved
    application.state.started_at = time.monotonic()
    application.state.fixture_available = False

    application.add_middleware(BodyLimitMiddleware, fixture_available=False)
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
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    return application


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> object:
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
