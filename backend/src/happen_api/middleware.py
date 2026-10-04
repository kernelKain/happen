"""Request limits, correlation IDs, and safe access logs."""

from __future__ import annotations

import time
from contextvars import ContextVar
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from happen_api.catalog import MAX_BODY_BYTES
from happen_api.errors import error_response
from happen_api.logging import get_logger

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def current_request_id() -> str:
    return request_id_var.get() or uuid4().hex


class RequestContextMiddleware:
    """Assign a request ID, add safe headers, and log operational metadata."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers.setdefault("x-request-id", request_id)
                headers.setdefault("x-content-type-options", "nosniff")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            get_logger().info(
                "request complete",
                extra={
                    "request_id": request_id,
                    "endpoint": scope.get("path", ""),
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)


class BodyLimitMiddleware:
    """Reject bodies over 16 KB before the application parses them."""

    def __init__(self, app: ASGIApp, *, fixture_available: bool) -> None:
        self.app = app
        self.fixture_available = fixture_available

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        raw_length = headers.get("content-length")
        if raw_length is not None and _too_large(raw_length):
            await _reject(scope, receive, send, fixture_available=self.fixture_available)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY_BYTES:
                await _reject(scope, receive, send, fixture_available=self.fixture_available)
                return
            if not message.get("more_body", False):
                break

        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay, send)


def _too_large(raw_length: str) -> bool:
    try:
        return int(raw_length) > MAX_BODY_BYTES
    except ValueError:
        return True


async def _reject(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    fixture_available: bool,
) -> None:
    response = error_response(
        status_code=413,
        request_id=current_request_id(),
        code="REQUEST_TOO_LARGE",
        message="The request is too large.",
        retryable=False,
        next_action="Reduce the request and try again.",
        fixture_available=fixture_available,
    )
    await response(scope, receive, send)
