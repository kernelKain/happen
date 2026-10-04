"""Stable public error envelope. Responses omit internals and secrets."""

from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from happen_api.catalog import CONTRACT_VERSION


class FieldError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    message: str


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool
    next_action: str
    fixture_available: bool
    fields: list[FieldError] | None = None
    retry_after_seconds: int | None = None


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    contract_version: str = CONTRACT_VERSION
    error: ErrorBody


def error_response(
    *,
    status_code: int,
    request_id: str,
    code: str,
    message: str,
    retryable: bool,
    next_action: str,
    fixture_available: bool,
    fields: list[dict[str, str]] | None = None,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    envelope = ErrorEnvelope(
        request_id=request_id,
        error=ErrorBody(
            code=code,
            message=message,
            retryable=retryable,
            next_action=next_action,
            fixture_available=fixture_available,
            fields=[FieldError.model_validate(item) for item in fields] if fields else None,
            retry_after_seconds=retry_after_seconds,
        ),
    )
    payload = envelope.model_dump(exclude_none=True)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(payload),
        headers={"X-Content-Type-Options": "nosniff"},
    )


def public_field_errors(errors: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Keep field locations and drop submitted values."""

    public: list[dict[str, str]] = []
    for item in errors:
        location = [str(part) for part in item.get("loc", ()) if part not in {"body", "__root__"}]
        public.append(
            {
                "field": ".".join(location) if location else "body",
                "message": "This value is not allowed.",
            }
        )
    return public


MESSAGES: dict[int, tuple[str, str, str, bool]] = {
    404: (
        "NOT_FOUND",
        "That path is not part of the Happen API.",
        "Check the request path.",
        False,
    ),
    405: (
        "INVALID_INPUT",
        "That method is not supported for this path.",
        "Use a supported method.",
        False,
    ),
    413: (
        "REQUEST_TOO_LARGE",
        "The request is too large.",
        "Reduce the request and try again.",
        False,
    ),
    422: (
        "INVALID_INPUT",
        "The request is not valid.",
        "Correct the highlighted fields and try again.",
        False,
    ),
    500: (
        "INTERNAL_ERROR",
        "Happen could not complete that request.",
        "Try again in a moment.",
        True,
    ),
}


def message_for(status_code: int) -> tuple[str, str, str, bool]:
    return MESSAGES.get(status_code, MESSAGES[500])
