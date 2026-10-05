"""Server-side plan allowance. The caller cannot raise or reset its own budget.

The allowance is per submitted plan, held in a bounded process-local store and
keyed by an opaque random token. These tests cover the accounting rules and the
concurrent case that a plain counter would get wrong.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from happen_api.app import create_app
from happen_api.config import Settings
from happen_api.planning.limits import (
    PLAN_BILLED_REQUEST_LIMIT,
    AllowanceError,
    AllowanceStore,
    MeteredProvider,
)
from happen_api.providers.serpapi.client import SerpApiClient, SerpApiFailure

TOKYO = {"label": "Tokyo", "source_text": "Tokyo", "timezone_name": "Asia/Tokyo"}
_KEY = "test-key-value"
_SEARCH_URL = "https://serpapi.com/search.json"


def _success_body() -> dict[str, object]:
    """A minimal successful SerpApi document. No live request is ever made."""

    return {
        "search_metadata": {"id": "search-1", "status": "Success"},
        "local_results": [],
    }


def _timeout_then(responses: list[httpx.Response], *, timeouts: int = 1):
    """Return a side effect that times out `timeouts` times, then replays `responses`."""

    remaining = list(responses)
    left = timeouts

    def effect(_request: httpx.Request) -> httpx.Response:
        nonlocal left
        if left > 0:
            left -= 1
            raise httpx.ReadTimeout("timed out")
        if remaining:
            return remaining.pop(0)
        return httpx.Response(503, json={"error": "unavailable"})

    return effect


class _CountingProvider:
    """A provider that records every billed call it is asked to make.

    `sends` is how many billed requests each call reaches the network with, the
    way the real client reports them on a failure. Zero models a call that was
    cancelled before sending.
    """

    def __init__(self, *, sends: int = 1, failure_code: str = "NO_RESULT") -> None:
        self.billed: list[str] = []
        self.credits_charged = 0
        self.sends = sends
        self.failure_code = failure_code

    def _count(self, name: str) -> object:
        self.billed.append(name)
        failure = SerpApiFailure(self.failure_code, "unused", retryable=True)
        failure.billed_requests = self.sends
        self.credits_charged += self.sends
        raise failure

    def search_places(self, *_args: object, **_kwargs: object) -> object:
        return self._count("search_places")

    def place_details(self, **_kwargs: object) -> object:
        return self._count("place_details")

    def place_reviews(self, **_kwargs: object) -> object:
        return self._count("place_reviews")

    def web_search(self, _query: str) -> object:
        return self._count("web_search")

    def lookup_maps_coordinates(self, _query: str) -> object:
        return self._count("lookup_maps_coordinates")

    def supported_locations(self, _query: str, limit: int = 5) -> object:
        # Free call. It must never be counted or charged.
        self.billed.append("supported_locations")
        return []

    def close(self) -> None:
        return None


def _app(settings: Settings, provider: _CountingProvider) -> TestClient:
    application = create_app(settings)
    application.state.provider_factory = lambda _limit, _timeout: provider
    return TestClient(application)


def _plan_body(token: str) -> dict[str, object]:
    return {
        "destination": TOKYO,
        "intents": [{"kind": "dinner", "label": "dinner", "position": 1}],
        "local_date": "2026-10-05",
        "local_start": "19:00",
        "plan_token": token,
    }


@pytest.fixture
def settings() -> Settings:
    return Settings(live_mode=True, serpapi_api_key="test-key-value", environment="test")


def test_issued_tokens_are_random_and_carry_no_prompt(settings: Settings) -> None:
    """Two plans get different tokens and the store holds only numbers."""

    store = AllowanceStore()
    first = store.issue()
    second = store.issue()
    assert first != second
    assert len(first) >= 32
    assert "Kyoto" not in first
    assert "dinner" not in first


def test_an_unknown_token_cannot_reach_the_provider(settings: Settings) -> None:
    """A forged token is refused before any billed call."""

    provider = _CountingProvider()
    with _app(settings, provider) as client:
        response = client.post("/api/v2/plans", json=_plan_body("forged-token-value-1234"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PLAN_TOKEN_INVALID"
    assert provider.billed == []
    assert "serpapi" not in response.text.casefold()


def test_an_expired_token_is_refused(settings: Settings) -> None:
    """A token older than the store TTL no longer resolves."""

    store = AllowanceStore(ttl=0)
    token = store.issue()
    time.sleep(0.01)
    with pytest.raises(AllowanceError):
        store.remaining(token)


def test_two_simultaneous_plans_cannot_exceed_eight(settings: Settings) -> None:
    """Concurrent callers sharing one token cannot jointly exceed the limit."""

    store = AllowanceStore()
    token = store.issue()
    provider = _CountingProvider()
    metered_a = MeteredProvider(provider, store, token)
    metered_b = MeteredProvider(provider, store, token)
    lock = threading.Lock()
    overran: list[int] = []

    def drain(client: MeteredProvider) -> None:
        for _ in range(PLAN_BILLED_REQUEST_LIMIT * 2):
            try:
                client.search_places("x")
            except SerpApiFailure as failure:
                if failure.code == "CREDIT_BUDGET_EXCEEDED":
                    break
        with lock:
            overran.append(store.spent(token))

    threads = [threading.Thread(target=drain, args=(c,)) for c in (metered_a, metered_b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # Two threads each attempted sixteen calls; together they still spent eight.
    assert overran == [PLAN_BILLED_REQUEST_LIMIT, PLAN_BILLED_REQUEST_LIMIT]
    assert store.spent(token) == PLAN_BILLED_REQUEST_LIMIT
    assert store.remaining(token) == 0


def test_an_attempted_ninth_call_is_refused_without_calling_the_provider() -> None:
    """Once eight are spent, the next claim fails and the provider is untouched."""

    store = AllowanceStore()
    token = store.issue()
    provider = _CountingProvider()
    metered = MeteredProvider(provider, store, token)
    for _ in range(PLAN_BILLED_REQUEST_LIMIT):
        with pytest.raises(SerpApiFailure):
            metered.search_places("x")
    before = len(provider.billed)
    with pytest.raises(SerpApiFailure) as excinfo:
        metered.place_details(place_id="p")
    assert excinfo.value.code == "CREDIT_BUDGET_EXCEEDED"
    assert len(provider.billed) == before
    assert store.spent(token) == PLAN_BILLED_REQUEST_LIMIT


def test_a_retry_that_sent_a_request_spends_one_more_request() -> None:
    """Verify each real outbound attempt spends its own allowance, retry included.

    The provider here is a real `SerpApiClient` with a mocked transport, because
    the point of the repair is that the charge happens at the send boundary
    rather than once per wrapper call.
    """

    with respx.mock:
        respx.get(_SEARCH_URL).mock(
            side_effect=_timeout_then([httpx.Response(200, json=_success_body())])
        )
        store, token = _store()
        metered = MeteredProvider(
            SerpApiClient(_KEY, credit_limit=PLAN_BILLED_REQUEST_LIMIT),
            store,
            token,
        )
        snapshot = metered.search_places("dinner in Tokyo")
    assert snapshot.attempts == 2
    # A failed attempt plus its successful retry is two sends, so two requests.
    assert store.spent(token) == 2
    assert store.remaining(token) == PLAN_BILLED_REQUEST_LIMIT - 2


def test_a_cancelled_request_that_sent_nothing_consumes_nothing() -> None:
    """Verify a call cancelled before the network spends no allowance."""

    store, token = _store()
    metered = MeteredProvider(
        SerpApiClient(_KEY, credit_limit=PLAN_BILLED_REQUEST_LIMIT, cancelled=lambda: True),
        store,
        token,
    )
    with respx.mock, pytest.raises(SerpApiFailure):
        metered.search_places("dinner in Tokyo")
    assert store.spent(token) == 0
    assert store.remaining(token) == PLAN_BILLED_REQUEST_LIMIT


def test_a_successful_first_attempt_spends_exactly_one() -> None:
    """Verify the ordinary path spends one request and no more."""

    with respx.mock:
        route = respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json=_success_body()))
        store, token = _store()
        metered = MeteredProvider(
            SerpApiClient(_KEY, credit_limit=PLAN_BILLED_REQUEST_LIMIT),
            store,
            token,
        )
        metered.search_places("dinner in Tokyo")
    assert len(route.calls) == 1
    assert store.spent(token) == 1
    assert store.remaining(token) == PLAN_BILLED_REQUEST_LIMIT - 1


def test_a_retry_is_refused_before_the_network_when_only_one_request_is_left() -> None:
    """Verify a plan with one request left sends it once and blocks its retry."""

    with respx.mock:
        route = respx.get(_SEARCH_URL).mock(
            side_effect=_timeout_then([], timeouts=PLAN_BILLED_REQUEST_LIMIT)
        )
        store = AllowanceStore()
        token = store.issue()
        # Seven requests are already spent, so exactly one attempt is affordable.
        store.claim_attempt(token, PLAN_BILLED_REQUEST_LIMIT - 1)
        metered = MeteredProvider(
            SerpApiClient(_KEY, credit_limit=PLAN_BILLED_REQUEST_LIMIT),
            store,
            token,
        )
        with pytest.raises(SerpApiFailure) as excinfo:
            metered.search_places("dinner in Tokyo")
    assert excinfo.value.code == "CREDIT_BUDGET_EXCEEDED"
    # The first attempt went out. The retry never did.
    assert len(route.calls) == 1
    assert store.spent(token) == PLAN_BILLED_REQUEST_LIMIT
    assert store.remaining(token) == 0


def test_concurrent_attempts_cannot_jointly_exceed_eight() -> None:
    """Verify many threads racing on one token still send at most eight requests."""

    store, token = _store()
    with respx.mock:
        route = respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json=_success_body()))
        metered = [
            MeteredProvider(
                SerpApiClient(_KEY, credit_limit=PLAN_BILLED_REQUEST_LIMIT),
                store,
                token,
            )
            for _ in range(4)
        ]
        threads = [threading.Thread(target=_drain, args=(client,)) for client in metered]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert store.spent(token) == PLAN_BILLED_REQUEST_LIMIT
    assert store.remaining(token) == 0
    # Every refused attempt was stopped before it could reach the network.
    assert len(route.calls) == PLAN_BILLED_REQUEST_LIMIT


def _drain(client: MeteredProvider) -> None:
    """Call repeatedly until the shared plan allowance refuses the call."""

    for _ in range(PLAN_BILLED_REQUEST_LIMIT):
        try:
            client.search_places("dinner in Tokyo")
        except SerpApiFailure as failure:
            if failure.code == "CREDIT_BUDGET_EXCEEDED":
                return


def _store() -> tuple[AllowanceStore, str]:
    store = AllowanceStore()
    return store, store.issue()


def test_the_free_locations_call_is_not_charged() -> None:
    """The free Locations API does not come out of the allowance."""

    store = AllowanceStore()
    token = store.issue()
    provider = _CountingProvider()
    metered = MeteredProvider(provider, store, token)
    metered.supported_locations("Tokyo", limit=5)
    metered.supported_locations("Tokyo", limit=5)
    assert store.spent(token) == 0
    assert provider.credits_charged == 0
    assert "supported_locations" in provider.billed


def test_the_store_is_bounded_and_evicts_the_oldest_entry() -> None:
    """The token store cannot grow without limit."""

    store = AllowanceStore(maxsize=4)
    tokens = [store.issue() for _ in range(10)]
    assert len(store) == 4
    for stale in tokens[:6]:
        with pytest.raises(AllowanceError):
            store.remaining(stale)


def test_a_cached_recomputation_spends_nothing(settings: Settings) -> None:
    """Replanning from the stored pool adds zero billed requests."""

    class _OnePlace(_CountingProvider):
        """Returns one usable place so discovery completes and caches the pool."""

        def search_places(self, *_args: object, **_kwargs: object) -> object:
            self.billed.append("search_places")
            self.credits_charged += 1
            return SimpleNamespace(
                payload={
                    "local_results": [
                        {
                            "title": "Kura",
                            "place_id": "kura",
                            "address": "Tokyo",
                            "gps_coordinates": {
                                "latitude": 35.6764,
                                "longitude": 139.6500,
                            },
                            "website": "https://kura.example",
                            "link": "https://maps.example/kura",
                            "description": "Counter seating.",
                            "type": "Restaurant",
                            "rating": 4.6,
                            "reviews": 12,
                            "operating_hours": {"monday": "5:00 PM-10:00 PM"},
                        }
                    ]
                }
            )

    provider = _OnePlace()
    application = create_app(settings)
    application.state.provider_factory = lambda _limit, _timeout: provider
    body = {
        "destination": TOKYO,
        "intents": [{"kind": "dinner", "label": "dinner", "position": 1}],
        "local_date": "2026-10-05",
        "local_start": "19:00",
    }
    with TestClient(application) as client:
        token = client.post(
            "/api/v2/briefs/interpret",
            json={"prompt": "Dinner in Tokyo on 2026-10-05 at 7pm"},
        ).json()["brief"]["plan_token"]
        first = client.post("/api/v2/plans", json={**body, "plan_token": token})
        spent = provider.credits_charged
        second = client.post("/api/v2/plans", json={**body, "plan_token": token})
    assert first.status_code == 200
    assert second.status_code == 200
    assert provider.credits_charged == spent
    assert second.json()["billed_requests"] == spent
    assert second.json()["remaining_requests"] == PLAN_BILLED_REQUEST_LIMIT - spent


def test_resolution_and_discovery_share_one_allowance(settings: Settings) -> None:
    """Both billed routes charge the same token, so the budget is shared."""

    store = AllowanceStore()
    token = store.issue()
    provider = _CountingProvider()
    resolve = MeteredProvider(provider, store, token)
    discover = MeteredProvider(provider, store, token)
    for _ in range(4):
        for client in (resolve, discover):
            with pytest.raises(SerpApiFailure):
                client.lookup_maps_coordinates("Tokyo")
    assert store.spent(token) == 8
    assert store.remaining(token) == 0


def test_responses_never_echo_the_prompt_or_a_credential(settings: Settings) -> None:
    """Neither the allowance store nor a response carries prompt text or keys."""

    store = AllowanceStore()
    token = store.issue()
    assert "Dinner in Kyoto" not in token
    assert "test-key-value" not in token
    for allowance in store._items.values():
        assert not hasattr(allowance, "prompt")
        assert not hasattr(allowance, "api_key")
    with _app(settings, _CountingProvider()) as client:
        response = client.post("/api/v2/plans", json=_plan_body(token))
    assert "test-key-value" not in response.text
    assert "serpapi" not in response.text.casefold()
