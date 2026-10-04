"""Global discovery. SerpApi is mocked, including incomplete evidence in more than one country."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from happen_api.app import create_app
from happen_api.config import Settings
from happen_api.planning.contracts import IntentKind, PlaceIntent, ResolvedDestination
from happen_api.planning.discovery import (
    DiscoveredPlace,
    DiscoveryStatus,
    _apply_web,
    discover_places,
    discovery_cache_key,
)
from happen_api.planning.itinerary import assemble_itinerary
from happen_api.providers.serpapi.client import SerpApiClient

_KEY = "live-key-value"
_URL = "https://serpapi.com/search.json"
_WHEN = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)


def test_two_intents_keep_provider_language_and_skip_extra_calls() -> None:
    """Inline hours and a highlight are reused, with no country or language parameter."""

    kyoto = _place("Kikunoi", "ChIJkyoto", language="ja", category="レストラン", price="¥¥¥")
    drinks = _place("Bar Y", "ChIJbary", language="ja", category="バー", price="¥¥")
    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(
            side_effect=[
                _response({"local_results": [kyoto]}),
                _response({"local_results": [drinks]}),
            ]
        )
        result = discover_places(
            _destination("Kyoto, Japan", "JP", 35.0116, 135.7681, "Kyoto"),
            [_intent(IntentKind.dinner, 1), _intent(IntentKind.drinks, 2)],
            client,
            local_date=date(2026, 10, 5),
            start_time=time(19, 0),
            retrieved_at=_WHEN,
        )

    assert result.status is DiscoveryStatus.ready
    assert result.billed_requests == 2
    assert len(route.calls) == 2
    queries = [_params(call.request)["q"] for call in route.calls]
    assert queries == ["dinner in Kyoto, Japan", "drinks in Kyoto, Japan"]
    for call in route.calls:
        sent = _params(call.request)
        assert "hl" not in sent
        assert "gl" not in sent
        assert sent["ll"].startswith("@35.01160,135.76810")
        assert "Indiranagar" not in sent["q"]
    assert result.places[0].provider_language == "ja"
    assert result.places[0].category == "レストラン"
    assert result.places[0].price == "¥¥¥"
    assert result.places[0].hours == ["monday: 17:00-22:00"]
    assert "+81-75-000-0000" not in result.model_dump_json()
    assert _KEY not in result.model_dump_json()


def test_incomplete_london_evidence_stays_unknown_and_uses_one_web_search() -> None:
    """A place without hours spends details and one web search. Reviews wait for a constraint."""

    sparse = {
        "title": "The Eagle",
        "place_id": "ChIJlondon",
        "gps_coordinates": {"latitude": 51.52, "longitude": -0.12},
    }
    detail = {"title": "The Eagle", "address": "159 Farringdon Road, London"}
    web = {
        "organic_results": [
            {
                "title": "Another pub",
                "link": "https://www.reddit.com/r/london/comments/1",
                "snippet": "The other pub in Manchester was quiet.",
            },
            {
                "title": "The Eagle London",
                "link": "https://www.reddit.com/r/london/comments/2",
                "snippet": "The Eagle London stays open late on Farringdon Road.",
            },
        ]
    }
    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(
            side_effect=[
                _response({"local_results": [sparse]}),
                _response({"place_results": detail}),
                _response(web),
            ]
        )
        result = discover_places(
            _destination("London, United Kingdom", "GB", 51.5072, -0.1276, "London"),
            [_intent(IntentKind.dinner, 1)],
            client,
            local_date=date(2026, 10, 5),
            start_time=time(19, 0),
            retrieved_at=_WHEN,
        )

    assert result.status is DiscoveryStatus.partial_evidence
    assert result.billed_requests == 3
    assert [call.request.url.params["engine"] for call in route.calls] == [
        "google_maps",
        "google_maps",
        "google",
    ]
    place = result.places[0]
    assert "hours" in place.unknown_fields
    assert "highlights" in place.unknown_fields
    assert place.address == "159 Farringdon Road, London"
    assert place.highlights == []
    assert place.community_notes
    assert place.conflicts == []
    assert all(urlsplit_host(call.request.url) == "serpapi.com" for call in route.calls)


def test_chicago_cache_key_changes_with_the_evening_and_intent() -> None:
    """The cache identity includes the canonical place, the local evening, and the intent."""

    chicago = _destination("Chicago, Illinois", "US", 41.8781, -87.6298, "Chicago")
    dinner = [_intent(IntentKind.dinner, 1)]
    first = discovery_cache_key(
        chicago,
        local_date=date(2026, 10, 5),
        start_time=time(18, 0),
        end_time=time(21, 0),
        intents=dinner,
    )
    later = discovery_cache_key(
        chicago,
        local_date=date(2026, 10, 6),
        start_time=time(18, 0),
        end_time=time(21, 0),
        intents=dinner,
    )
    coffee = discovery_cache_key(
        chicago,
        local_date=date(2026, 10, 5),
        start_time=time(18, 0),
        end_time=time(21, 0),
        intents=[_intent(IntentKind.coffee, 1)],
    )
    assert first != later
    assert first != coffee
    assert len(first) == 64
    assert "Chicago" not in first
    assert all(character in "0123456789abcdef" for character in first)
    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(return_value=_response({"local_results": []}))
        result = discover_places(
            chicago,
            dinner,
            client,
            local_date=date(2026, 10, 5),
            start_time=time(18, 0),
            end_time=time(21, 0),
            retrieved_at=_WHEN,
        )
    assert result.status is DiscoveryStatus.no_result
    assert result.cache_key == first
    assert _params(route.calls[0].request)["q"] == "dinner in Chicago, Illinois"


def test_resolution_and_discovery_share_eight_billed_requests() -> None:
    """Earlier billed lookups leave discovery inside the same eight-request plan."""

    body = _response(
        {
            "local_results": [
                {
                    "title": "Kikunoi",
                    "place_id": "ChIJkyoto",
                    "gps_coordinates": {"latitude": 35.0, "longitude": 135.7},
                }
            ]
        }
    )
    with respx.mock, _client(credit_limit=8) as client:
        route = respx.get(_URL).mock(return_value=body)
        for _index in range(6):
            client.lookup_maps_coordinates("Kyoto")
        result = discover_places(
            _destination("Kyoto, Japan", "JP", 35.0116, 135.7681, "Kyoto"),
            [_intent(IntentKind.dinner, 1), _intent(IntentKind.museum, 2)],
            client,
            local_date=date(2026, 10, 5),
            start_time=time(19, 0),
            retrieved_at=_WHEN,
        )

    assert client.credits_charged == 8
    assert len(route.calls) == 8
    assert result.billed_requests == 2
    assert result.stopped is DiscoveryStatus.quota
    assert result.status is DiscoveryStatus.partial_evidence


def test_timeout_and_quota_are_typed_and_send_no_ninth_request() -> None:
    """A deadline and an exhausted allowance stop before another search."""

    with respx.mock, _client() as client:
        respx.get(_URL).mock(side_effect=httpx.TimeoutException("deadline"))
        timed = discover_places(
            _destination("Paris, France", "FR", 48.8566, 2.3522, "Paris"),
            [_intent(IntentKind.dinner, 1)],
            client,
            local_date=date(2026, 10, 5),
            start_time=time(19, 0),
            retrieved_at=_WHEN,
        )
    assert timed.status is DiscoveryStatus.timeout
    assert timed.places == []

    quota_body = httpx.Response(429, json={"error": "Your account has run out of searches."})
    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(return_value=quota_body)
        blocked = discover_places(
            _destination("Paris, France", "FR", 48.8566, 2.3522, "Paris"),
            [_intent(IntentKind.dinner, 1), _intent(IntentKind.drinks, 2)],
            client,
            local_date=date(2026, 10, 5),
            start_time=time(19, 0),
            retrieved_at=_WHEN,
        )
    assert blocked.status is DiscoveryStatus.quota
    assert len(route.calls) == 1


def test_official_hours_override_a_community_statement() -> None:
    """A community page does not replace official hours, and the disagreement stays visible."""

    from happen_api.planning.discovery import _place_from_record

    record = _place("Kikunoi", "ChIJkyoto")
    found = _place_from_record(record, IntentKind.dinner)
    assert found is not None
    _apply_web(
        found,
        [
            {
                "title": "Kikunoi Kyoto",
                "link": "https://www.reddit.com/r/kyoto/comments/1",
                "snippet": "Kikunoi Kyoto is closed on Monday.",
            }
        ],
        _destination("Kyoto, Japan", "JP", 35.0116, 135.7681, "Kyoto"),
    )
    assert found.hours == ["monday: 17:00-22:00"]
    assert found.conflicts[0].official == "monday: 17:00-22:00"
    assert found.conflicts[0].community is not None


def test_shared_http_client_closes_with_the_app(settings: Settings) -> None:
    """The process HTTP client closes when the application stops."""

    application = create_app(settings)
    with TestClient(application):
        client = application.state.http_client
        assert isinstance(client, httpx.Client)
        assert client.is_closed is False
    assert application.state.http_client.is_closed is True


def _client(credit_limit: int = 8) -> SerpApiClient:
    return SerpApiClient(_KEY, credit_limit=credit_limit, total_timeout_seconds=5)


def _response(payload: dict[str, object]) -> httpx.Response:
    body = {
        "search_metadata": {"id": "search-1", "status": "Success"},
        "search_parameters": {"api_key": _KEY},
        **payload,
    }
    return httpx.Response(200, json=body)


def _place(
    name: str,
    place_id: str,
    *,
    language: str = "en",
    category: str = "restaurant",
    price: str = "$$",
) -> dict[str, object]:
    return {
        "title": name,
        "place_id": place_id,
        "data_id": f"data-{place_id}",
        "address": "1 Example Street",
        "gps_coordinates": {"latitude": 35.0, "longitude": 135.7},
        "rating": 4.5,
        "reviews": 20,
        "price": price,
        "type": category,
        "language": language,
        "operating_hours": {"monday": "17:00-22:00"},
        "popular_times": {"monday": [{"time": "19:00"}]},
        "website": "https://example.com/venue",
        "link": "https://maps.google.com/?cid=1",
        "thumbnail": "https://example.com/photo.jpg",
        "events": [{"title": "Evening seating"}],
        "description": "Quiet counter",
        "phone": "+81-75-000-0000",
    }


def _destination(
    label: str,
    country: str,
    latitude: float,
    longitude: float,
    locality: str,
) -> ResolvedDestination:
    return ResolvedDestination(
        label=label,
        source_text=label,
        locality=locality,
        country_code=country,
        serpapi_location=label,
        latitude=latitude,
        longitude=longitude,
    )


def _intent(kind: IntentKind, position: int) -> PlaceIntent:
    return PlaceIntent(kind=kind, label=kind.value, position=position)


def _params(request: httpx.Request) -> dict[str, str]:
    return dict(request.url.params)


def urlsplit_host(url: httpx.URL) -> str:
    return url.host


@pytest.mark.parametrize("country", ["JP", "GB", "US"])
def test_queries_follow_the_destination_country(country: str) -> None:
    """Each destination supplies its own place text. None of them is hard-coded."""

    labels = {"JP": "Kyoto, Japan", "GB": "London, United Kingdom", "US": "Chicago, Illinois"}
    coordinates = {"JP": (35.0, 135.7), "GB": (51.5, -0.12), "US": (41.8, -87.6)}
    latitude, longitude = coordinates[country]
    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(return_value=_response({"local_results": []}))
        discover_places(
            _destination(labels[country], country, latitude, longitude, labels[country]),
            [_intent(IntentKind.coffee, 1)],
            client,
            local_date=date(2026, 10, 5),
            start_time=time(16, 0),
            retrieved_at=_WHEN,
        )
    sent = _params(route.calls[0].request)
    assert sent["q"] == f"coffee in {labels[country]}"
    assert "hl" not in sent
    assert "gl" not in sent


def test_a_later_candidate_with_stronger_fit_is_selected() -> None:
    """The first Maps row is not chosen when a later row is verified open."""

    weak = _row("First Counter", "first", hours={}, rating=4.9, website=None)
    strong = _row("Verified Room", "verified", hours={"monday": "17:00-22:00"}, rating=4.0)
    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(side_effect=_router([weak, strong]))
        result = discover_places(
            _kyoto(),
            [_intent(IntentKind.dinner, 1)],
            client,
            local_date=date(2026, 10, 5),
            start_time=time(19, 0),
            retrieved_at=_WHEN,
        )
    plan = _selected(result.places)
    assert plan.stops[0].name == "Verified Room"
    assert result.places[0].name == "Verified Room"
    assert result.places[0].provider_rank == 1
    assert {place.name for place in result.places} >= {"First Counter", "Verified Room"}
    assert len(route.calls) <= 8


def test_a_definitely_closed_first_result_is_skipped() -> None:
    """Details that show the leader is closed move on to the next candidate."""

    shut = _row("Shut Room", "shut", hours={}, rating=4.9)
    later = _row("Open Later", "later", hours={}, rating=None, website=None)
    hours = {
        "shut": {"monday": "Closed"},
        "later": {"monday": "17:00-22:00"},
    }
    with respx.mock, _client() as client:
        respx.get(_URL).mock(side_effect=_router([shut, later], detail_hours=hours))
        result = discover_places(
            _kyoto(),
            [_intent(IntentKind.dinner, 1)],
            client,
            local_date=date(2026, 10, 5),
            start_time=time(19, 0),
            retrieved_at=_WHEN,
        )
    plan = _selected(result.places)
    assert plan.stops[0].name == "Open Later"
    assert plan.stops[0].hours_status == "open"
    assert {place.name for place in result.places} >= {"Shut Room", "Open Later"}


def test_equal_evidence_uses_provider_order_as_the_tie_breaker() -> None:
    """Equal verified fit keeps the earlier provider result, not the earlier name."""

    zeta = _row("Zeta Room", "zeta")
    alpha = _row("Alpha Room", "alpha")
    with respx.mock, _client() as client:
        respx.get(_URL).mock(side_effect=_router([zeta, alpha]))
        result = discover_places(
            _kyoto(),
            [_intent(IntentKind.dinner, 1)],
            client,
            local_date=date(2026, 10, 5),
            start_time=time(19, 0),
            retrieved_at=_WHEN,
        )
    assert [place.provider_rank for place in result.places] == [0, 1]
    assert _selected(result.places).stops[0].name == "Zeta Room"
    assert result.billed_requests == 1


def test_two_intents_still_produce_at_most_two_stops() -> None:
    """Five results for each of two intents still become one stop each."""

    dinner = [_row(f"Dinner {index}", f"dinner-{index}") for index in range(5)]
    drinks = [_row(f"Drinks {index}", f"drinks-{index}") for index in range(5)]

    def answer(request: httpx.Request) -> httpx.Response:
        if "drinks" in _params(request)["q"]:
            return _response({"local_results": drinks})
        return _response({"local_results": dinner})

    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(side_effect=answer)
        result = discover_places(
            _kyoto(),
            [_intent(IntentKind.dinner, 1), _intent(IntentKind.drinks, 2)],
            client,
            local_date=date(2026, 10, 5),
            start_time=time(19, 0),
            retrieved_at=_WHEN,
        )
    plan = _selected(result.places, [_intent(IntentKind.dinner, 1), _intent(IntentKind.drinks, 2)])
    assert len(result.places) == 10
    assert len(plan.stops) == 2
    assert [stop.intent.value for stop in plan.stops] == ["dinner", "drinks"]
    assert len(route.calls) == 2


def test_discovery_cannot_exceed_eight_billed_calls() -> None:
    """Two intents, thin evidence, and a review constraint still stop at eight calls."""

    def answer(request: httpx.Request) -> httpx.Response:
        params = _params(request)
        if params.get("type") == "search":
            rows = [
                {
                    "title": f"Place {index}",
                    "place_id": f"place-{index}",
                    "gps_coordinates": {"latitude": 35.01, "longitude": 135.77},
                }
                for index in range(8)
            ]
            return _response({"local_results": rows})
        if params.get("type") == "place":
            return _response({"place_results": {}})
        if params.get("engine") == "google_maps_reviews":
            return _response({"reviews": [{"snippet": "A quiet room."}]})
        return _response({"organic_results": []})

    with respx.mock, _client(credit_limit=20) as client:
        route = respx.get(_URL).mock(side_effect=answer)
        result = discover_places(
            _kyoto(),
            [_intent(IntentKind.dinner, 1), _intent(IntentKind.drinks, 2)],
            client,
            local_date=date(2026, 10, 5),
            start_time=time(19, 0),
            retrieved_at=_WHEN,
            preferences=["quiet"],
        )
    assert len(route.calls) <= 8
    assert result.billed_requests <= 8
    assert client.credits_charged <= 8
    searches = [call for call in route.calls if _params(call.request).get("type") == "search"]
    assert len(searches) <= 2


def test_duplicates_and_outside_places_leave_the_pool() -> None:
    """Place id, data id, and name plus address dedupe. A far pin is rejected."""

    rows = [
        _row("Kikunoi", "place-a", data_id="data-a", address="459 Shimokawara-cho"),
        _row("Kikunoi", "place-b", data_id="data-b", address="459 Shimokawara cho"),
        _row("Other Name", "place-a", data_id="data-c", address="9 Other Road"),
        _row("Elsewhere", "place-e", data_id="data-a", address="9 New Road"),
        _row(
            "Paris Bistro",
            "place-far",
            data_id="data-far",
            address="1 Rue de Rivoli",
            latitude=48.86,
            longitude=2.35,
        ),
        _row("Junsei", "place-junsei", data_id="data-junsei", address="Different Street"),
        {
            "title": "No Pin",
            "place_id": "place-none",
            "data_id": "data-none",
        },
    ]
    with respx.mock, _client() as client:
        respx.get(_URL).mock(side_effect=_router(rows))
        result = discover_places(
            _kyoto(),
            [_intent(IntentKind.dinner, 1)],
            client,
            local_date=date(2026, 10, 5),
            start_time=time(19, 0),
            retrieved_at=_WHEN,
        )
    names = [place.name for place in result.places]
    assert names.count("Kikunoi") == 1
    assert "Junsei" in names
    assert "No Pin" in names
    assert "Paris Bistro" not in names
    assert "Other Name" not in names
    assert "Elsewhere" not in names
    missing = next(place for place in result.places if place.name == "No Pin")
    assert "address" in missing.unknown_fields
    assert "hours" in missing.unknown_fields


def test_a_requested_constraint_can_outrank_provider_order() -> None:
    """Reviews are read only for a requested constraint, and that evidence can win."""

    alpha = _row("Alpha Room", "alpha")
    bravo = _row("Bravo Room", "bravo")
    reviews = {
        "alpha": [{"snippet": "Loud room near the door."}],
        "bravo": [{"snippet": "A quiet room in the back."}],
    }

    def answer(request: httpx.Request) -> httpx.Response:
        params = _params(request)
        if params.get("engine") == "google_maps_reviews":
            place_id = params.get("place_id", "")
            return _response({"reviews": reviews.get(place_id, [])})
        return _router([alpha, bravo])(request)

    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(side_effect=answer)
        result = discover_places(
            _kyoto(),
            [_intent(IntentKind.dinner, 1)],
            client,
            local_date=date(2026, 10, 5),
            start_time=time(19, 0),
            retrieved_at=_WHEN,
            preferences=["quiet"],
        )
    assert _selected(result.places, preferences=["quiet"]).stops[0].name == "Bravo Room"
    assert any(_params(call.request).get("engine") == "google_maps_reviews" for call in route.calls)
    assert len(route.calls) <= 8


def _selected(
    places: list[DiscoveredPlace],
    intents: list[PlaceIntent] | None = None,
    preferences: list[str] | None = None,
):
    return assemble_itinerary(
        places,
        intents or [_intent(IntentKind.dinner, 1)],
        local_date=date(2026, 10, 5),
        local_start=time(19, 0),
        retrieved_at=_WHEN,
        preferences=preferences,
    )


def _kyoto() -> ResolvedDestination:
    return _destination("Kyoto, Japan", "JP", 35.0116, 135.7681, "Kyoto")


def _router(
    rows: list[dict[str, object]],
    detail_hours: dict[str, dict[str, str]] | None = None,
):
    def answer(request: httpx.Request) -> httpx.Response:
        params = _params(request)
        if params.get("type") == "place":
            hours = (detail_hours or {}).get(params.get("place_id", ""))
            body: dict[str, object] = {}
            if hours is not None:
                body["operating_hours"] = hours
            return _response({"place_results": body})
        if params.get("engine") == "google":
            return _response({"organic_results": []})
        return _response({"local_results": rows})

    return answer


def _row(
    name: str,
    place_id: str,
    *,
    hours: dict[str, str] | None = None,
    rating: float | None = 4.5,
    website: str | None = "https://example.com/venue",
    data_id: str | None = None,
    address: str = "1 Example Street",
    latitude: float = 35.01,
    longitude: float = 135.77,
) -> dict[str, object]:
    record: dict[str, object] = {
        "title": name,
        "place_id": place_id,
        "data_id": data_id or f"data-{place_id}",
        "address": address,
        "gps_coordinates": {"latitude": latitude, "longitude": longitude},
        "link": "https://maps.example/venue",
        "type": "restaurant",
    }
    if rating is not None:
        record["rating"] = rating
    if website is not None:
        record["website"] = website
    if hours is None:
        record["operating_hours"] = {"monday": "17:00-22:00"}
    elif hours:
        record["operating_hours"] = hours
    return record
