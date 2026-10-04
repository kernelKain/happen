"""Health, metadata, CORS, and safe error contracts."""

from __future__ import annotations

import hashlib
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from happen_api import __version__
from happen_api.app import create_app
from happen_api.catalog import CONTRACT_VERSION, SCORING_POLICY_VERSION
from happen_api.config import Settings


class ExampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


HEALTH_FIELDS = {
    "status",
    "service_version",
    "contract_version",
    "model_status",
    "fixture_status",
    "uptime_seconds",
}
META_FIELDS = {
    "contract_version",
    "service_version",
    "supported_neighborhoods",
    "supported_categories",
    "supported_experiences",
    "priority_dimensions",
    "canonical_preset",
    "fixture_available",
    "live_available",
    "model_status",
    "scoring_policy_version",
    "timezone",
}
ERROR_FIELDS = {"code", "message", "retryable", "next_action", "fixture_available"}


@pytest.fixture
def client(settings: Settings) -> TestClient:
    """Create a test client that returns server errors as responses instead of raising them."""

    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_health_is_degraded_without_loading_the_model(
    settings_factory: Callable[..., Settings],
) -> None:
    """Verify health responds quickly with degraded readiness without importing the model runtime."""

    missing = settings_factory(MODEL_FILENAME="missing-evidence-model.gguf")
    missing_client = TestClient(create_app(missing), raise_server_exceptions=False)
    assert "llama_cpp" not in sys.modules
    started = time.perf_counter()
    response = missing_client.get("/healthz")
    elapsed = time.perf_counter() - started

    assert elapsed < 1
    assert response.status_code == 200
    body = response.json()
    assert set(body) == HEALTH_FIELDS
    assert body["status"] == "degraded"
    assert body["service_version"] == __version__
    assert body["contract_version"] == CONTRACT_VERSION
    assert body["model_status"] == "not_loaded"
    assert body["fixture_status"] == "ready"
    assert body["uptime_seconds"] >= 0
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "llama_cpp" not in sys.modules


def test_matching_model_file_is_ready_without_loading_llama(
    settings_factory: Callable[..., Settings],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a checksum match reports the model ready without importing the runtime."""

    blob = b"not-a-real-model"
    path = tmp_path / "tiny.gguf"
    path.write_bytes(blob)
    monkeypatch.setattr("happen_api.readiness.model_file", lambda _settings: path)
    ready = settings_factory(
        MODEL_FILENAME="tiny.gguf", MODEL_SHA256=hashlib.sha256(blob).hexdigest()
    )
    ready_client = TestClient(create_app(ready), raise_server_exceptions=False)
    response = ready_client.get("/healthz")
    body = response.json()
    assert response.status_code == 200
    assert body["model_status"] == "ready"
    assert body["fixture_status"] == "ready"
    assert body["status"] == "ok"
    assert "llama_cpp" not in sys.modules

    mismatch = settings_factory(MODEL_FILENAME="tiny.gguf", MODEL_SHA256="0" * 64)
    mismatch_client = TestClient(create_app(mismatch), raise_server_exceptions=False)
    rejected = mismatch_client.get("/healthz")
    assert rejected.status_code == 200
    assert rejected.json()["model_status"] == "unavailable"
    assert rejected.json()["status"] == "degraded"
    assert "llama_cpp" not in sys.modules


def test_metadata_exposes_the_canonical_preset(
    settings_factory: Callable[..., Settings],
) -> None:
    """Verify metadata matches the locked planner preset, choices, and availability contract."""

    missing = settings_factory(MODEL_FILENAME="missing-evidence-model.gguf")
    response = TestClient(create_app(missing)).get("/api/v1/meta")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == META_FIELDS
    assert body["supported_neighborhoods"] == ["indiranagar"]
    assert body["supported_categories"] == ["restaurants"]
    assert body["supported_experiences"] == ["easier_conversation"]
    assert body["priority_dimensions"] == ["conversation", "short_wait", "seating"]
    assert body["canonical_preset"] == {
        "neighborhood": "indiranagar",
        "restaurant_category": "restaurants",
        "arrival_start": "18:00",
        "arrival_end": "21:00",
        "desired_experience": "easier_conversation",
        "priorities": ["conversation", "short_wait", "seating"],
    }
    assert body["fixture_available"] is True
    assert body["live_available"] is False
    assert body["model_status"] == "not_loaded"
    assert body["scoring_policy_version"] == SCORING_POLICY_VERSION
    assert body["timezone"] == "Asia/Kolkata"
    assert body["contract_version"] == CONTRACT_VERSION


def test_metadata_reports_live_availability_without_the_key(
    settings_factory: Callable[..., Settings],
) -> None:
    """Verify configured live availability is public while the provider key stays private."""

    configured = settings_factory(HAPPEN_LIVE_ENABLED=True, SERPAPI_API_KEY="live-key-value")
    live_client = TestClient(create_app(configured))
    response = live_client.get("/api/v1/meta")
    rendered = response.text
    assert response.status_code == 200
    assert response.json()["live_available"] is True
    assert "live-key-value" not in rendered
    assert "live-key-value" not in repr(response.headers)


def test_cors_allows_only_the_configured_origin(client: TestClient) -> None:
    """Verify allowed and denied origins plus the supported preflight methods and headers."""

    allowed = client.get("/healthz", headers={"Origin": "http://127.0.0.1:5173"})
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "access-control-allow-credentials" not in allowed.headers

    denied = client.get("/healthz", headers={"Origin": "https://elsewhere.example"})
    assert "access-control-allow-origin" not in denied.headers

    preflight = client.options(
        "/api/v1/meta",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type,idempotency-key",
        },
    )
    assert preflight.status_code == 200
    allow_methods = preflight.headers["access-control-allow-methods"]
    allow_headers = preflight.headers["access-control-allow-headers"].lower()
    assert "GET" in allow_methods
    assert "POST" in allow_methods
    assert "content-type" in allow_headers
    assert "idempotency-key" in allow_headers
    assert "access-control-allow-credentials" not in preflight.headers


def test_unknown_path_uses_the_error_envelope(client: TestClient) -> None:
    """Verify unknown routes return the public error envelope without a traceback."""

    response = client.get("/missing")
    assert response.status_code == 404
    body = response.json()
    assert body["contract_version"] == CONTRACT_VERSION
    assert set(body["error"]) == ERROR_FIELDS
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["fixture_available"] is True
    assert "Traceback" not in response.text


def test_oversized_body_is_rejected_before_parsing(client: TestClient) -> None:
    """Verify oversized requests receive HTTP 413 without reflecting the submitted body."""

    response = client.post("/healthz", content=b"x" * (16 * 1024 + 1))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert "xxxx" not in response.text


def test_validation_errors_do_not_echo_submitted_values(settings: Settings) -> None:
    """Verify validation errors identify rejected fields without disclosing their values."""

    app = create_app(settings)

    @app.post("/example")
    def example(item: ExampleRequest) -> ExampleRequest:
        """Echo a validated request to exercise rejection of unexpected fields."""

        return item

    client = TestClient(app)
    response = client.post("/example", json={"name": "ok", "secret_note": "live-key-value"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_INPUT"
    assert body["error"]["fields"] == [
        {"field": "secret_note", "message": "This value is not allowed."}
    ]
    assert "live-key-value" not in response.text


def test_unhandled_errors_hide_internals(
    caplog: pytest.LogCaptureFixture,
    settings: Settings,
) -> None:
    """Verify unexpected errors omit exception secrets and paths from responses and logs."""

    app = create_app(settings)

    @app.get("/boom")
    def boom() -> None:
        """Raise an exception containing synthetic sensitive details to test error sanitization."""

        raise RuntimeError("authorization=live-key-value path=/tmp/model.gguf")

    caplog.set_level(logging.ERROR, logger="happen")
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["retryable"] is True
    assert "live-key-value" not in response.text
    assert "/tmp/model.gguf" not in response.text
    assert "Traceback" not in response.text
    assert "live-key-value" not in caplog.text
    assert "/tmp/model.gguf" not in caplog.text


def test_access_log_omits_authorization_header(
    caplog: pytest.LogCaptureFixture,
    settings: Settings,
) -> None:
    """Verify access logs retain the endpoint without recording authorization values."""

    app = create_app(settings)
    caplog.set_level(logging.INFO, logger="happen")
    client = TestClient(app)
    response = client.get("/healthz", headers={"Authorization": "Bearer live-key-value"})
    assert response.status_code == 200
    assert "live-key-value" not in caplog.text
    assert caplog.records[-1].endpoint == "/healthz"
