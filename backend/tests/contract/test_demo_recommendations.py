"""Fixture recommendation API contracts. These tests do not load the model."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from happen_api.app import create_app
from happen_api.catalog import CANONICAL_PRESET, CONTRACT_VERSION
from happen_api.config import Settings
from happen_api.domain.timing import KOLKATA

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=KOLKATA)
KEY = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def demo_client(settings: Settings) -> TestClient:
    """Create an API client with a fixed clock and a scripted extractor."""

    application = create_app(settings)
    application.state.clock = lambda: NOW
    application.state.excerpt_generate = _unknown
    return TestClient(application, raise_server_exceptions=False)


def test_matching_fixture_returns_three_rows_and_no_invented_winner(
    demo_client: TestClient,
) -> None:
    """Verify an all-unknown extraction stays an honest insufficient result."""

    response = demo_client.post(
        "/api/v1/demo-recommendations",
        headers={"Idempotency-Key": KEY},
        json=CANONICAL_PRESET,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == CONTRACT_VERSION
    assert body["outcome"] == "insufficient_evidence"
    assert body["recommendation"] is None
    assert body["fallback"] is None
    assert len(body["candidates"]) == 3
    assert body["provenance"]["mode"] == "captured_fixture"
    assert body["provenance"]["data_label"] == "captured_fixture"
    assert body["provenance"]["adapter_id"] == "none"
    assert "Planning evidence—not live occupancy." in body["warnings"][0]["message"]
    assert body["input"]["visit_date"] == "2026-10-04"
    assert {candidate["name"] for candidate in body["candidates"]} == {
        "Bombay Brasserie",
        "Truffles - Indiranagar",
        "Chianti, Indiranagar",
    }
    assert "synthetic" not in response.text.lower()
    labels = [
        window["fit_label"] for candidate in body["candidates"] for window in candidate["windows"]
    ]
    assert labels
    assert set(labels) <= {"unknown", "weak"}
    assert all(
        window["status"] == window["fit_label"]
        for candidate in body["candidates"]
        for window in candidate["windows"]
    )
    assert "prompt" not in response.text
    assert "SERPAPI" not in response.text
    assert "llama_cpp" not in sys.modules


def test_repeated_key_reuses_the_decision_and_refreshes_the_clock(demo_client: TestClient) -> None:
    """Verify the same key and payload skip a second extraction."""

    calls = {"count": 0}
    original = demo_client.app.state.excerpt_generate

    def counting(prompt: str) -> str:
        calls["count"] += 1
        return original(prompt)

    demo_client.app.state.excerpt_generate = counting
    first = demo_client.post(
        "/api/v1/demo-recommendations",
        headers={"Idempotency-Key": KEY},
        json=CANONICAL_PRESET,
    )
    second_key = str(uuid4())
    second = demo_client.post(
        "/api/v1/demo-recommendations",
        headers={"Idempotency-Key": second_key},
        json=CANONICAL_PRESET,
    )
    replay = demo_client.post(
        "/api/v1/demo-recommendations",
        headers={"Idempotency-Key": KEY},
        json=CANONICAL_PRESET,
    )
    assert first.status_code == 200
    assert calls["count"] == 9
    assert second.status_code == 200
    assert replay.status_code == 200
    assert calls["count"] == 9
    assert first.json()["outcome"] == replay.json()["outcome"]
    assert first.json()["request_id"] != replay.json()["request_id"]


def test_same_key_with_a_different_payload_conflicts(demo_client: TestClient) -> None:
    """Verify an idempotency key cannot be reused for another planner request."""

    first = demo_client.post(
        "/api/v1/demo-recommendations",
        headers={"Idempotency-Key": KEY},
        json=CANONICAL_PRESET,
    )
    other = {**CANONICAL_PRESET, "arrival_end": "20:00"}
    second = demo_client.post(
        "/api/v1/demo-recommendations",
        headers={"Idempotency-Key": KEY},
        json=other,
    )
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_invalid_input_does_not_extract(demo_client: TestClient) -> None:
    """Verify validation fails before fixture loading or extraction."""

    calls = {"count": 0}

    def counting(prompt: str) -> str:
        calls["count"] += 1
        return _unknown(prompt)

    demo_client.app.state.excerpt_generate = counting
    missing_key = demo_client.post("/api/v1/demo-recommendations", json=CANONICAL_PRESET)
    unknown = demo_client.post(
        "/api/v1/demo-recommendations",
        headers={"Idempotency-Key": KEY},
        json={**CANONICAL_PRESET, "winner": True},
    )
    short = demo_client.post(
        "/api/v1/demo-recommendations",
        headers={"Idempotency-Key": KEY},
        json={**CANONICAL_PRESET, "arrival_end": "18:30"},
    )
    assert missing_key.status_code == 422
    assert missing_key.json()["error"]["code"] == "INVALID_INPUT"
    assert unknown.status_code == 422
    assert short.status_code == 422
    assert calls["count"] == 0


def test_unmatched_request_does_not_extract(demo_client: TestClient) -> None:
    """Verify a valid planner request with no fixture match stops before extraction."""

    calls = {"count": 0}

    def counting(prompt: str) -> str:
        calls["count"] += 1
        return _unknown(prompt)

    demo_client.app.state.excerpt_generate = counting
    response = demo_client.post(
        "/api/v1/demo-recommendations",
        headers={"Idempotency-Key": KEY},
        json={**CANONICAL_PRESET, "arrival_start": "17:00", "arrival_end": "20:00"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FIXTURE_NOT_AVAILABLE"
    assert calls["count"] == 0


def test_rate_limit_reports_when_to_retry(settings_factory: Callable[..., Settings]) -> None:
    """Verify the configured rolling limit rejects the next recommendation."""

    limited = settings_factory(HAPPEN_RATE_LIMIT=1)
    application = create_app(limited)
    application.state.clock = lambda: NOW
    application.state.excerpt_generate = _unknown
    client = TestClient(application, raise_server_exceptions=False)
    first = client.post(
        "/api/v1/demo-recommendations",
        headers={"Idempotency-Key": KEY},
        json=CANONICAL_PRESET,
    )
    second = client.post(
        "/api/v1/demo-recommendations",
        headers={"Idempotency-Key": str(uuid4())},
        json=CANONICAL_PRESET,
    )
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"
    assert second.json()["error"]["retry_after_seconds"] >= 1


def test_missing_model_file_is_unavailable_without_loading_llama(
    settings_factory: Callable[..., Settings],
) -> None:
    """Verify a missing artifact returns the model error and does not import llama."""

    unavailable = settings_factory(MODEL_FILENAME="missing-evidence-model.gguf")
    application = create_app(unavailable)
    application.state.clock = lambda: NOW
    client = TestClient(application, raise_server_exceptions=False)
    response = client.post(
        "/api/v1/demo-recommendations",
        headers={"Idempotency-Key": KEY},
        json=CANONICAL_PRESET,
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_UNAVAILABLE"
    assert "llama_cpp" not in sys.modules
    assert "/" not in response.json()["error"]["message"]


def _unknown(prompt: str) -> str:
    excerpt_id = "excerpt"
    for line in prompt.splitlines():
        if line.startswith("excerpt_id:"):
            excerpt_id = line.split(":", 1)[1].strip()
    return (
        '{"schema_version":"1","excerpt_id":"'
        + excerpt_id
        + '","signals":[],"unknown_dimensions":["conversation","short_wait","seating"]}'
    )
