"""v2 planning routes. Provider calls are scripted and v1 stays registered."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from happen_api.app import create_app
from happen_api.config import Settings
from happen_api.planning.clock import FixedClock
from happen_api.providers.serpapi.client import SerpApiFailure, SupportedLocation

CLOCK = FixedClock(datetime(2026, 10, 4, 22, 0, tzinfo=UTC))
TOKYO = SupportedLocation(
    name="Tokyo",
    canonical_name="Tokyo,Tokyo,Japan",
    country_code="JP",
    target_type="City",
    latitude=35.6764225,
    longitude=139.650027,
)


def _snapshot(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(payload=payload)


def _row(title: str, place_id: str, hours: dict[str, str] | None) -> dict[str, object]:
    record: dict[str, object] = {
        "title": title,
        "place_id": place_id,
        "address": "Kyoto",
        "gps_coordinates": {"latitude": 35.0, "longitude": 135.7},
        "website": "https://venue.example",
        "link": "https://maps.example/venue",
        "description": "Counter seating.",
        "type": "Restaurant",
        "rating": 4.6,
        "reviews": 12,
    }
    if hours is not None:
        record["operating_hours"] = hours
    return record


class ScriptedProvider:
    """In-memory provider. It never opens a network connection."""

    def __init__(
        self,
        credit_limit: int,
        timeout: float,
        *,
        locations: list[SupportedLocation] | None = None,
        hours: dict[str, str] | None = None,
        empty: bool = False,
        failure: SerpApiFailure | None = None,
        credits: int = 0,
    ) -> None:
        self.credit_limit = credit_limit
        self.timeout = timeout
        self.locations = locations if locations is not None else [TOKYO]
        self.hours = hours
        self.empty = empty
        self.failure = failure
        self.credits_charged = credits
        self.calls: list[str] = []

    def supported_locations(self, query: str, limit: int = 5) -> list[SupportedLocation]:
        self.calls.append(f"locations:{query}:{limit}")
        return self.locations

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
        if self.failure is not None:
            raise self.failure
        if self.empty:
            return _snapshot({"local_results": []})
        title = "Night Bar" if "drinks" in query else "Kura"
        return _snapshot({"local_results": [_row(title, title.casefold(), self.hours)]})

    def place_details(
        self,
        *,
        data_id: str | None = None,
        place_id: str | None = None,
    ) -> SimpleNamespace:
        self.calls.append(f"details:{place_id or data_id}")
        self.credits_charged += 1
        return _snapshot({"place_results": {}})

    def place_reviews(
        self,
        *,
        data_id: str | None = None,
        place_id: str | None = None,
    ) -> SimpleNamespace:
        self.calls.append(f"reviews:{place_id or data_id}")
        self.credits_charged += 1
        return _snapshot({"reviews": []})

    def web_search(self, query: str) -> SimpleNamespace:
        self.calls.append(f"web:{query}")
        self.credits_charged += 1
        return _snapshot({"organic_results": []})


def _app(settings: Settings, provider: ScriptedProvider | None = None) -> TestClient:
    application = create_app(settings)
    application.state.clock = CLOCK
    if provider is not None:
        application.state.provider_factory = lambda _limit, _timeout: provider
    return TestClient(application)


def _plan_body(destination: dict[str, object], drinks: bool = False) -> dict[str, object]:
    intents = [{"kind": "dinner", "label": "dinner", "position": 1}]
    if drinks:
        intents.append({"kind": "drinks", "label": "drinks", "position": 2})
    return {
        "destination": destination,
        "intents": intents,
        "local_date": "2026-10-05",
        "local_start": "19:00",
    }


def _safe(payload: str) -> None:
    folded = payload.casefold()
    assert "traceback" not in folded
    assert ".gguf" not in folded
    assert "api_key" not in folded
    assert "site-packages" not in folded
    assert "captured evidence" not in folded


def test_v1_health_stays_available_beside_the_planning_routes(settings: Settings) -> None:
    """The historical health route still answers after the v2 router is added."""

    with _app(settings) as client:
        response = client.get("/healthz")
        missing = client.post("/api/v1/recommendations", json={})
    assert response.status_code == 200
    assert missing.status_code != 404


def test_interpret_returns_a_brief_and_hides_invalid_prompt_text(settings: Settings) -> None:
    """A prompt becomes a brief. An invalid prompt does not come back in the error."""

    with _app(settings) as client:
        ready = client.post(
            "/api/v2/briefs/interpret",
            json={"prompt": "Dinner in Kyoto on 2026-10-05 at 7pm"},
        )
        rejected = client.post(
            "/api/v2/briefs/interpret",
            json={"prompt": "Dinner\x00tonight"},
        )
    assert ready.status_code == 200
    body = ready.json()
    assert body["outcome"] == "ready_for_retrieval"
    assert body["brief"]["destination_text"] == "Kyoto"
    assert body["stops"] == []
    assert body["follow_up"] is None
    assert rejected.status_code == 422
    _safe(rejected.text)
    assert "Dinner" not in rejected.text


def test_resolve_keeps_an_ambiguous_query_as_choices(settings: Settings) -> None:
    """Several cities are returned for the caller to choose, without a traceback."""

    places = [
        SupportedLocation(
            name=f"Springfield {index}",
            canonical_name=f"Springfield,Region {index},United States",
            country_code="US",
            target_type="City",
            latitude=39.0 + index,
            longitude=-89.0,
        )
        for index in range(3)
    ]
    provider = ScriptedProvider(8, 14.0, locations=places)
    with _app(settings, provider) as client:
        response = client.post("/api/v2/destinations/resolve", json={"query": "Springfield"})
    assert response.status_code == 409
    body = response.json()
    assert body["status"] == "ambiguous"
    assert len(body["choices"]) == 3
    assert body["destination"] is None
    _safe(response.text)
    assert "maps:" not in provider.calls


def test_resolve_tokyo_today_uses_the_destination_zone(settings: Settings) -> None:
    """At 22:00 UTC on October 4, Tokyo's local today is October 5."""

    provider = ScriptedProvider(8, 14.0)
    with _app(settings, provider) as client:
        response = client.post(
            "/api/v2/destinations/resolve",
            json={"query": "Tokyo", "pending_date": "today"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["destination"]["timezone_name"] == "Asia/Tokyo"
    assert body["local_time"]["local_date"] == "2026-10-05"
    assert body["billed_requests"] == 0


def test_plan_selects_two_stops_and_an_unverified_transition(settings: Settings) -> None:
    """Discovery feeds Python selection. The response has evidence and no travel time."""

    provider = ScriptedProvider(8, 14.0, hours={"monday": "17:00-22:00"})
    with _app(settings, provider) as client:
        resolved = client.post("/api/v2/destinations/resolve", json={"query": "Tokyo"}).json()
        response = client.post(
            "/api/v2/plans",
            json=_plan_body(resolved["destination"], drinks=True),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "2"
    assert body["outcome"] == "planned"
    assert [item["name"] for item in body["stops"]] == ["Kura", "Night Bar"]
    assert {item["source"] for item in body["stops"][0]["evidence"]} >= {"maps", "official"}
    assert body["stops"][0]["evidence"][0]["retrieved_at"]
    assert body["transition"]["status"] == "unverified"
    assert "duration" not in body["transition"]
    assert "score" not in response.text
    assert "weight" not in response.text
    _safe(response.text)


def test_plan_reports_no_results_closed_hours_and_unknown_hours(settings: Settings) -> None:
    """Empty, closed, and unlisted hours each stay explicit."""

    empty = ScriptedProvider(8, 14.0, empty=True)
    closed = ScriptedProvider(8, 14.0, hours={"sunday": "17:00-22:00"})
    unknown = ScriptedProvider(8, 14.0, hours=None)
    with _app(settings, empty) as client:
        destination = client.post("/api/v2/destinations/resolve", json={"query": "Tokyo"}).json()[
            "destination"
        ]
        none = client.post("/api/v2/plans", json=_plan_body(destination))
    with _app(settings, closed) as client:
        shut = client.post("/api/v2/plans", json=_plan_body(destination))
    with _app(settings, unknown) as client:
        listed = client.post("/api/v2/plans", json=_plan_body(destination))
    assert none.status_code == 200
    assert none.json()["outcome"] == "no_results"
    assert shut.json()["outcome"] == "insufficient_evidence"
    assert listed.json()["stops"][0]["confidence"] == "low"
    assert "not listed" in listed.json()["stops"][0]["warnings"][0]
    _safe(none.text)
    _safe(shut.text)


def test_timeout_and_quota_are_safe_errors(settings: Settings) -> None:
    """A stalled search and a spent allowance do not expose internals or the fixture."""

    stalled = ScriptedProvider(
        8,
        14.0,
        failure=SerpApiFailure("TRANSIENT_DEPENDENCY", "timed out", retryable=True),
    )
    spent = ScriptedProvider(8, 14.0, credits=8)
    with _app(settings, stalled) as client:
        destination = {"label": "Kyoto", "source_text": "Kyoto", "timezone_name": "Asia/Tokyo"}
        timeout = client.post("/api/v2/plans", json=_plan_body(destination))
    with _app(settings, spent) as client:
        quota = client.post("/api/v2/plans", json=_plan_body(destination))
    assert timeout.status_code == 504
    assert timeout.json()["error"]["code"] == "TIMEOUT"
    assert quota.status_code == 503
    assert quota.json()["error"]["code"] == "QUOTA_EXHAUSTED"
    assert "fixture" not in timeout.json()["error"]["next_action"].casefold()
    _safe(timeout.text)
    _safe(quota.text)


def test_a_spent_plan_budget_does_not_search(settings: Settings) -> None:
    """Eight earlier billed requests leave no allowance for another search."""

    provider = ScriptedProvider(8, 14.0, hours={"monday": "17:00-22:00"})
    application = create_app(settings)
    application.state.clock = CLOCK
    application.state.provider_factory = lambda _limit, _timeout: provider
    body = _plan_body({"label": "Kyoto", "source_text": "Kyoto", "timezone_name": "Asia/Tokyo"})
    body["prior_billed_requests"] = 8
    with TestClient(application) as client:
        response = client.post("/api/v2/plans", json=body)
    assert response.status_code == 503
    assert provider.calls == []
    _safe(response.text)


def test_refine_returns_a_proposal_without_replacing_the_plan(settings: Settings) -> None:
    """Refinement does not retrieve places and does not mark the proposal applied."""

    provider = ScriptedProvider(8, 14.0)
    with _app(settings, provider) as client:
        interpreted = client.post(
            "/api/v2/briefs/interpret",
            json={"prompt": "Dinner in Kyoto on 2026-10-05 at 7pm for two, quiet"},
        ).json()
        response = client.post(
            "/api/v2/plans/refine",
            json={
                "current": interpreted["brief"],
                "revision": "Drinks in Tokyo on 2026-10-06 at 8pm",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is False
    assert body["current"]["destination_text"] == "Kyoto"
    assert body["proposed"]["destination_text"] == "Tokyo"
    assert body["diff"]["changed"]
    assert provider.calls == []
    _safe(response.text)


def test_live_planning_without_configuration_is_a_safe_error(settings: Settings) -> None:
    """A plan without a configured provider does not mention a key or a model path."""

    with _app(settings) as client:
        response = client.post(
            "/api/v2/plans",
            json=_plan_body(
                {"label": "Kyoto", "source_text": "Kyoto", "timezone_name": "Asia/Tokyo"}
            ),
        )
    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Live place evidence is not configured."
    _safe(response.text)
