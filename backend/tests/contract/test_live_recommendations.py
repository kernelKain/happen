"""Live recommendation failures stay explicit. These tests do not call SerpApi."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from happen_api.app import create_app
from happen_api.catalog import CANONICAL_PRESET
from happen_api.config import Settings
from happen_api.domain.timing import KOLKATA
from happen_api.providers.serpapi.client import ProviderSnapshot, SerpApiFailure

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=KOLKATA)
KEY = "22222222-2222-4222-8222-222222222222"
_PHONE = "+91 99999 00000"


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


def _row(place_id: str, title: str) -> dict[str, object]:
    return {
        "title": title,
        "place_id": place_id,
        "type": "Italian restaurant",
        "phone": _PHONE,
        "hours": [{"saturday": "6 pm - 11 pm"}],
        "user_reviews": [
            {
                "username": "Ada Reviewer",
                "snippet": "Quiet tables around 7 pm.",
                "iso_date": "2026-09-01",
                "link": "https://maps.google.com/reviews/example",
            }
        ],
    }


def _snapshot(kind: str, search_id: str, payload: dict[str, object]) -> ProviderSnapshot:
    return ProviderSnapshot(
        kind=kind,  # type: ignore[arg-type]
        search_id=search_id,
        empty=False,
        attempts=1,
        credits_charged=1,
        payload=payload,
    )


class FakeProvider:
    """Scripted provider. It records calls and can fail before any network."""

    def __init__(
        self,
        credit_limit: int,
        failure: SerpApiFailure | None = None,
        search_payload: dict[str, object] | None = None,
    ) -> None:
        self.credit_limit = credit_limit
        self.failure = failure
        self.search_payload = search_payload
        self.credits_charged = 0
        self.calls: list[tuple[str, str]] = []

    def search_places(self, query: str) -> ProviderSnapshot:
        self._charge("search", query)
        if self.failure is not None:
            raise self.failure
        if self.search_payload is not None:
            return _snapshot("search", "search-scripted", self.search_payload)
        rows = [
            _row("ChIJalpha001", "Alpha Atrium"),
            _row("ChIJbravo0002", "Bravo Bistro"),
            _row("ChIJcharlie03", "Charlie Cafe"),
        ]
        return _snapshot("search", "search-1", {"local_results": rows})

    def place_details(
        self,
        *,
        data_id: str | None = None,
        place_id: str | None = None,
    ) -> ProviderSnapshot:
        identifier = place_id or data_id or ""
        self._charge("place", identifier)
        names = {
            "ChIJalpha001": "Alpha Atrium",
            "ChIJbravo0002": "Bravo Bistro",
            "ChIJcharlie03": "Charlie Cafe",
        }
        row = _row(identifier, names.get(identifier, "Unknown"))
        return _snapshot("place", f"place-{identifier}", {"place_results": row})

    def place_reviews(
        self,
        *,
        data_id: str | None = None,
        place_id: str | None = None,
    ) -> ProviderSnapshot:
        identifier = place_id or data_id or ""
        self._charge("reviews", identifier)
        return _snapshot("reviews", f"reviews-{identifier}", {"reviews": []})

    def _charge(self, kind: str, value: str) -> None:
        if self.credits_charged >= self.credit_limit:
            raise SerpApiFailure(
                "CREDIT_BUDGET_EXCEEDED",
                "The SerpApi credit budget for this recommendation is exhausted.",
                retryable=False,
            )
        self.credits_charged += 1
        self.calls.append((kind, value))


def _client(
    settings: Settings,
    *,
    failure: SerpApiFailure | None = None,
    search_payload: dict[str, object] | None = None,
    providers: list[FakeProvider] | None = None,
    script: dict[str, object] | None = None,
) -> TestClient:
    application = create_app(settings)
    application.state.clock = lambda: NOW
    application.state.excerpt_generate = _unknown
    created: list[FakeProvider] = providers if providers is not None else []
    holder = script if script is not None else {"failure": failure, "payload": search_payload}

    def factory(credit_limit: int, _timeout: float) -> FakeProvider:
        current = holder.get("failure")
        payload = holder.get("payload")
        provider = FakeProvider(
            credit_limit,
            current if isinstance(current, SerpApiFailure) else None,
            payload if isinstance(payload, dict) else None,
        )
        created.append(provider)
        return provider

    application.state.provider_factory = factory
    application.state.created_providers = created
    return TestClient(application, raise_server_exceptions=False)


def _post(client: TestClient, key: str, body: dict[str, object] | None = None):
    return client.post(
        "/api/v1/recommendations",
        headers={"Idempotency-Key": key},
        json=body or CANONICAL_PRESET,
    )


def test_live_mode_disabled_does_not_call_a_provider_or_the_fixture(
    settings: Settings,
) -> None:
    """Verify a disabled live mode returns an error instead of fixture evidence."""

    application = create_app(settings)
    application.state.provider_factory = lambda *_args: (_ for _ in ()).throw(AssertionError)
    client = TestClient(application, raise_server_exceptions=False)
    response = _post(client, KEY)

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "LIVE_MODE_DISABLED"
    assert body["error"]["fixture_available"] is True
    assert body["error"]["next_action"] == "Try again after live evidence is configured."
    assert "captured" not in body["error"]["next_action"].lower()
    assert "North Gallery" not in response.text
    assert "captured_fixture" not in response.text
    assert "live-key-value" not in response.text


def test_live_search_scores_three_places_without_fixture_labels(
    settings_factory,
) -> None:
    """Verify a successful provider response is labeled live and can be replayed."""

    settings = settings_factory(HAPPEN_LIVE_ENABLED=True, SERPAPI_API_KEY="live-key-value")
    providers: list[FakeProvider] = []
    client = _client(settings, providers=providers)
    first = _post(client, KEY)
    second = _post(client, str(uuid4()))

    assert first.status_code == 200
    body = first.json()
    assert body["provenance"]["mode"] == "live"
    assert body["provenance"]["data_label"] == "live"
    assert body["provenance"]["fixture_version"] == "none"
    assert any(item["code"] == "planning_evidence" for item in body["warnings"])
    assert body["outcome"] == "insufficient_evidence"
    assert [item["name"] for item in body["candidates"]] == [
        "Alpha Atrium",
        "Bravo Bistro",
        "Charlie Cafe",
    ]
    assert _PHONE not in first.text
    assert "Ada Reviewer" not in first.text
    assert "North Gallery" not in first.text
    assert "search-1" in body["provenance"]["safe_request_ids"]
    assert providers[0].calls[0] == ("search", "restaurants in Indiranagar, Bengaluru")
    assert second.status_code == 200
    assert len(providers) == 1


def test_provider_failure_stays_an_error_and_opens_the_circuit(settings_factory) -> None:
    """Verify transient provider failures never fall through to fixture evidence."""

    settings = settings_factory(HAPPEN_LIVE_ENABLED=True, SERPAPI_API_KEY="live-key-value")
    failure = SerpApiFailure(
        "TRANSIENT_DEPENDENCY",
        "SerpApi did not respond before the deadline.",
        retryable=True,
        immediate_retry=True,
    )
    providers: list[FakeProvider] = []
    client = _client(settings, failure=failure, providers=providers)
    statuses = [_post(client, str(uuid4())).status_code for _ in range(3)]
    blocked = _post(client, str(uuid4()))

    assert statuses == [503, 503, 503]
    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "SERPAPI_UNAVAILABLE"
    assert blocked.json()["error"]["fixture_available"] is True
    assert "North Gallery" not in blocked.text
    assert len(providers) == 3


def test_authentication_failure_disables_later_live_calls(settings_factory) -> None:
    """Verify a rejected key disables live mode without another provider call."""

    settings = settings_factory(HAPPEN_LIVE_ENABLED=True, SERPAPI_API_KEY="live-key-value")
    failure = SerpApiFailure(
        "AUTHENTICATION_FAILED",
        "SerpApi rejected the API key.",
        retryable=False,
    )
    providers: list[FakeProvider] = []
    client = _client(settings, failure=failure, providers=providers)
    first = _post(client, KEY)
    second = _post(client, str(uuid4()))

    assert first.status_code == 503
    assert first.json()["error"]["code"] == "LIVE_MODE_DISABLED"
    assert "live-key-value" not in first.text
    assert second.status_code == 503
    assert len(providers) == 1


def test_soft_budget_stops_a_later_live_request(settings_factory) -> None:
    """Verify the process search budget is enforced before another provider call."""

    settings = settings_factory(
        HAPPEN_LIVE_ENABLED=True,
        SERPAPI_API_KEY="live-key-value",
        HAPPEN_SERPAPI_SEARCH_BUDGET=1,
    )
    providers: list[FakeProvider] = []
    client = _client(settings, providers=providers)
    first = _post(client, KEY)
    second = _post(client, str(uuid4()))

    assert first.status_code == 503
    assert first.json()["error"]["code"] == "SERPAPI_QUOTA_EXHAUSTED"
    assert first.json()["error"]["next_action"] == "Try again later."
    assert "captured" not in first.json()["error"]["next_action"].lower()
    assert second.status_code == 503
    assert second.json()["error"]["code"] == "SERPAPI_QUOTA_EXHAUSTED"
    assert len(providers) == 1


def test_deadline_expires_before_a_provider_call(settings_factory) -> None:
    """Verify an exhausted deadline returns a timeout and does not load the fixture."""

    settings = settings_factory(HAPPEN_LIVE_ENABLED=True, SERPAPI_API_KEY="live-key-value")
    providers: list[FakeProvider] = []
    client = _client(settings, providers=providers)
    ticks = iter((0.0, 29.0))
    client.app.state.monotonic = lambda: next(ticks)
    response = _post(client, KEY)

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "PROCESSING_TIMEOUT"
    assert response.json()["error"]["fixture_available"] is True
    assert providers == []
    assert "North Gallery" not in response.text


def test_empty_search_is_insufficient_live_evidence(settings_factory) -> None:
    """Verify an empty provider search is not replaced with fixture restaurants."""

    settings = settings_factory(HAPPEN_LIVE_ENABLED=True, SERPAPI_API_KEY="live-key-value")
    client = _client(settings, search_payload={"local_results": []})
    response = _post(client, KEY)

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "insufficient_evidence"
    assert body["candidates"] == []
    assert body["provenance"]["mode"] == "live"
    assert body["recommendation"] is None
    assert "North Gallery" not in response.text


def test_unreadable_search_stays_an_invalid_response(settings_factory) -> None:
    """Verify a search without place rows is an error, not fixture evidence."""

    settings = settings_factory(HAPPEN_LIVE_ENABLED=True, SERPAPI_API_KEY="live-key-value")
    client = _client(settings, search_payload={})
    response = _post(client, KEY)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "SERPAPI_INVALID_RESPONSE"
    assert response.json()["error"]["fixture_available"] is True
    assert "North Gallery" not in response.text


def test_circuit_allows_one_probe_after_the_open_interval(settings_factory) -> None:
    """Verify the circuit stays open, then allows one later provider call."""

    settings = settings_factory(HAPPEN_LIVE_ENABLED=True, SERPAPI_API_KEY="live-key-value")
    failure = SerpApiFailure(
        "TRANSIENT_DEPENDENCY",
        "SerpApi did not respond before the deadline.",
        retryable=True,
        immediate_retry=True,
    )
    script: dict[str, object] = {"failure": failure, "payload": None}
    providers: list[FakeProvider] = []
    client = _client(settings, providers=providers, script=script)
    clock = {"now": 1_000.0}
    client.app.state.monotonic = lambda: clock["now"]
    for _ in range(3):
        failed = _post(client, str(uuid4()))
        assert failed.status_code == 503
        clock["now"] += 1
    blocked = _post(client, str(uuid4()))
    assert blocked.status_code == 503
    assert len(providers) == 3
    clock["now"] += 121
    script["failure"] = None
    probe = _post(client, str(uuid4()))

    assert probe.status_code == 200
    assert probe.json()["provenance"]["mode"] == "live"
    assert len(providers) == 4


def test_same_key_with_a_different_payload_conflicts(settings_factory) -> None:
    """Verify a live idempotency key cannot be reused for another request."""

    settings = settings_factory(HAPPEN_LIVE_ENABLED=True, SERPAPI_API_KEY="live-key-value")
    client = _client(settings)
    first = _post(client, KEY)
    second = _post(client, KEY, {**CANONICAL_PRESET, "arrival_end": "20:00"})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_rate_limit_blocks_a_second_live_request(settings_factory) -> None:
    """Verify the live route uses the existing request limit."""

    settings = settings_factory(
        HAPPEN_LIVE_ENABLED=True,
        SERPAPI_API_KEY="live-key-value",
        HAPPEN_RATE_LIMIT=1,
    )
    providers: list[FakeProvider] = []
    client = _client(settings, providers=providers)
    first = _post(client, KEY)
    second = _post(client, str(uuid4()))

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"
    assert len(providers) == 1
