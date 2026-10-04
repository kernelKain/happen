"""Recomputing a refinement from evidence Happen already retrieved.

A preference, accessibility, budget, or party-size change must not spend another
billed request. The stored candidate pool is rescored instead. A destination,
date, time, or intent change needs new evidence. Python revalidates the whole
proposed brief either way, so nothing is trusted from the caller.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from happen_api.app import create_app
from happen_api.config import Settings
from happen_api.planning.clock import FixedClock

CLOCK = FixedClock(datetime(2026, 10, 4, 15, 0, tzinfo=UTC))
TOKYO = {"label": "Tokyo", "source_text": "Tokyo", "timezone_name": "Asia/Tokyo"}
KYOTO = {"label": "Kyoto", "source_text": "Kyoto", "timezone_name": "Asia/Tokyo"}


def _snapshot(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(payload=payload)


def _place(
    name: str,
    place_id: str,
    *,
    description: str,
    rating: float,
    hours: dict[str, str] | None = None,
    latitude: float = 35.6764,
    longitude: float = 139.65,
) -> dict[str, object]:
    record: dict[str, object] = {
        "title": name,
        "place_id": place_id,
        "data_id": f"data-{place_id}",
        "address": "Tokyo",
        "gps_coordinates": {"latitude": latitude, "longitude": longitude},
        "website": "https://venue.example",
        "link": "https://maps.example/venue",
        "description": description,
        "type": "Restaurant",
        "rating": rating,
        "reviews": 20,
        "operating_hours": hours if hours is not None else {"monday": "5:00 PM–10:00 PM"},
    }
    return record


class TwoPlaceProvider:
    """Two places where only one verifies quiet. Every call is counted."""

    def __init__(self, credit_limit: int = 8, timeout: float = 14.0) -> None:
        self.credit_limit = credit_limit
        self.timeout = timeout
        self.credits_charged = 0
        self.calls: list[str] = []

    def supported_locations(self, query: str, limit: int = 5) -> list[object]:
        self.calls.append(f"locations:{query}")
        return []

    def lookup_maps_coordinates(self, query: str) -> list[object]:
        self.calls.append(f"maps:{query}")
        return []

    def search_places(
        self,
        query: str,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> SimpleNamespace:
        self.calls.append(query)
        self.credits_charged += 1
        return _snapshot(
            {
                "local_results": [
                    _place(
                        "Loud Room",
                        "loud",
                        description="Counter seating.",
                        rating=4.4,
                    ),
                    _place(
                        "Quiet Room",
                        "quiet",
                        description="A quiet room.",
                        rating=4.3,
                        latitude=35.6765,
                        longitude=139.6501,
                    ),
                ]
            }
        )

    def place_details(self, **_kwargs: object) -> SimpleNamespace:
        self.calls.append("details")
        self.credits_charged += 1
        return _snapshot({"place_results": {}})

    def place_reviews(self, **_kwargs: object) -> SimpleNamespace:
        self.calls.append("reviews")
        self.credits_charged += 1
        return _snapshot({"reviews": []})

    def web_search(self, query: str) -> SimpleNamespace:
        self.calls.append(f"web:{query}")
        self.credits_charged += 1
        return _snapshot({"organic_results": []})


def _app(settings: Settings, provider: TwoPlaceProvider) -> TestClient:
    application = create_app(settings)
    application.state.clock = CLOCK
    application.state.provider_factory = lambda _limit, _timeout: provider
    return TestClient(application)


def _body(**updates: object) -> dict[str, object]:
    body: dict[str, object] = {
        "destination": TOKYO,
        "intents": [{"kind": "dinner", "label": "dinner", "position": 1}],
        "local_date": "2026-10-05",
        "local_start": "19:00",
    }
    body.update(updates)
    return body


@pytest.fixture
def settings() -> Settings:
    return Settings(
        live_mode=True,
        serpapi_api_key="test-key-value",
        environment="test",
    )


def test_a_preference_only_change_rescores_without_a_new_billed_request(
    settings: Settings,
) -> None:
    """Verify the second plan reuses the stored pool and spends nothing."""

    provider = TwoPlaceProvider()
    with _app(settings, provider) as client:
        first = client.post("/api/v2/plans", json=_body())
        spent_after_first = provider.credits_charged
        second = client.post(
            "/api/v2/plans",
            json=_body(preferences=["quiet"], prior_billed_requests=spent_after_first),
        )
    assert first.status_code == 200
    assert second.status_code == 200
    assert provider.credits_charged == spent_after_first


def test_a_verified_preference_replaces_the_previous_stop(settings: Settings) -> None:
    """Verify a cached rescore can select a different, better-evidenced place."""

    provider = TwoPlaceProvider()
    with _app(settings, provider) as client:
        first = client.post("/api/v2/plans", json=_body())
        second = client.post(
            "/api/v2/plans",
            json=_body(
                preferences=["quiet"],
                prior_billed_requests=provider.credits_charged,
            ),
        )
    assert first.json()["stops"][0]["name"] == "Loud Room"
    assert second.json()["stops"][0]["name"] == "Quiet Room"
    constraint = second.json()["stops"][0]["constraints"][0]
    assert constraint["constraint"] == "quiet"
    assert constraint["status"] == "met"
    assert constraint["evidence"]


def test_an_unknown_preference_is_reported_instead_of_claimed(settings: Settings) -> None:
    """Verify evidence that does not support the request stays unknown."""

    provider = TwoPlaceProvider()
    with _app(settings, provider) as client:
        response = client.post(
            "/api/v2/plans",
            json=_body(preferences=["wheelchair access"]),
        )
    assert response.status_code == 200
    stop = response.json()["stops"][0]
    constraint = stop["constraints"][0]
    assert constraint["constraint"] == "wheelchair access"
    assert constraint["status"] == "unknown"
    assert constraint["evidence"] == []
    assert response.json()["outcome"] == "insufficient_evidence"


def test_the_cache_key_ignores_constraints_so_scoring_can_change(settings: Settings) -> None:
    """Verify the same evidence key serves a differently constrained request."""

    provider = TwoPlaceProvider()
    with _app(settings, provider) as client:
        plain = client.post("/api/v2/plans", json=_body())
        quiet = client.post("/api/v2/plans", json=_body(preferences=["quiet"]))
        party = client.post("/api/v2/plans", json=_body(party_size=4))
    assert plain.status_code == quiet.status_code == party.status_code == 200
    # One search served all three.
    assert provider.credits_charged == 1
    assert plain.json()["stops"][0]["name"] != quiet.json()["stops"][0]["name"]


def test_a_destination_change_retrieves_new_evidence(settings: Settings) -> None:
    """Verify a different destination cannot reuse the first pool."""

    provider = TwoPlaceProvider()
    with _app(settings, provider) as client:
        client.post("/api/v2/plans", json=_body())
        before = provider.credits_charged
        moved = client.post("/api/v2/plans", json=_body(destination=KYOTO))
    assert moved.status_code == 200
    assert provider.credits_charged > before


def test_a_date_change_retrieves_new_evidence(settings: Settings) -> None:
    """Verify a different local evening cannot reuse the first pool."""

    provider = TwoPlaceProvider()
    with _app(settings, provider) as client:
        client.post("/api/v2/plans", json=_body())
        before = provider.credits_charged
        moved = client.post("/api/v2/plans", json=_body(local_date="2026-10-06"))
    assert moved.status_code == 200
    assert provider.credits_charged > before


def test_an_intent_change_retrieves_new_evidence(settings: Settings) -> None:
    """Verify a second intent needs its own search."""

    provider = TwoPlaceProvider()
    with _app(settings, provider) as client:
        client.post("/api/v2/plans", json=_body())
        before = provider.credits_charged
        drinks = client.post(
            "/api/v2/plans",
            json=_body(
                intents=[
                    {"kind": "dinner", "label": "dinner", "position": 1},
                    {"kind": "drinks", "label": "drinks", "position": 2},
                ]
            ),
        )
    assert drinks.status_code == 200
    assert provider.credits_charged > before


def test_the_server_rejects_an_invalid_constraint_in_the_request(settings: Settings) -> None:
    """Verify constraints are rebuilt and validated server-side, not trusted."""

    provider = TwoPlaceProvider()
    with _app(settings, provider) as client:
        rejected = client.post(
            "/api/v2/plans",
            json=_body(preferences="quiet"),
        )
        bad_budget = client.post(
            "/api/v2/plans",
            json=_body(budget={"amount": "10", "currency": "usd", "bound": "about"}),
        )
        bad_party = client.post("/api/v2/plans", json=_body(party_size=99))
    assert rejected.status_code == 422
    assert bad_budget.status_code == 422
    assert bad_party.status_code == 422
    assert provider.credits_charged == 0


def test_refine_itself_still_spends_nothing(settings: Settings) -> None:
    """Verify the proposal step retrieves no places and applies nothing."""

    provider = TwoPlaceProvider()
    with _app(settings, provider) as client:
        interpreted = client.post(
            "/api/v2/briefs/interpret",
            json={"prompt": "Dinner in Tokyo on 2026-10-05 at 7pm"},
        ).json()
        response = client.post(
            "/api/v2/plans/refine",
            json={"current": interpreted["brief"], "revision": "Make it romantic"},
        )
    assert response.status_code == 200
    assert response.json()["applied"] is False
    assert response.json()["current"]["preferences"] == []
    assert response.json()["proposed"]["preferences"] == ["romantic"]
    # Nothing was there before, so the new preference is an addition.
    assert response.json()["diff"]["added"] == ["preferences"]
    assert response.json()["diff"]["changed"] == []
    assert provider.calls == []
