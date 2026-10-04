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
    DiscoveryStatus,
    _apply_web,
    discover_places,
    discovery_cache_key,
)
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
    """A place without hours spends details, reviews, and at most one web search."""

    sparse = {
        "title": "The Eagle",
        "place_id": "ChIJlondon",
        "gps_coordinates": {"latitude": 51.52, "longitude": -0.12},
    }
    detail = {"title": "The Eagle", "address": "159 Farringdon Road, London"}
    reviews = {"reviews": [{"snippet": "Loud room near the bar."}]}
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
                _response(reviews),
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
    assert result.billed_requests == 4
    assert [call.request.url.params["engine"] for call in route.calls] == [
        "google_maps",
        "google_maps",
        "google_maps_reviews",
        "google",
    ]
    place = result.places[0]
    assert "hours" in place.unknown_fields
    assert place.address == "159 Farringdon Road, London"
    assert place.highlights == ["Loud room near the bar."]
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
