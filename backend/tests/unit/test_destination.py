"""Destination resolution. Every provider call is mocked."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import httpx
import pytest
import respx

from happen_api.planning import (
    PLAN_BILLED_REQUEST_LIMIT,
    DatePhrase,
    FixedClock,
    PendingDate,
    ResolutionSource,
    ResolutionStatus,
    interpret,
    resolve_destination,
)
from happen_api.planning.local_time import WallTimeStatus
from happen_api.providers.serpapi.client import SerpApiClient

_KEY = "live-key-value"
_LOCATIONS = "https://serpapi.com/locations.json"
_SEARCH = "https://serpapi.com/search.json"
_CLOCK = FixedClock(datetime(2026, 10, 4, 22, 0, tzinfo=UTC))
_MARKER = "raw-payload-marker"

_CITIES = {
    "Jaipur": ("Rajasthan", "India", "IN", 26.9124336, 75.7872709, "Asia/Kolkata"),
    "London": ("England", "United Kingdom", "GB", 51.5072178, -0.1275862, "Europe/London"),
    "New York": ("New York", "United States", "US", 40.7127753, -74.0059728, "America/New_York"),
    "Tokyo": ("Tokyo", "Japan", "JP", 35.6764225, 139.650027, "Asia/Tokyo"),
}


def _city(
    name: str,
    region: str,
    country: str,
    country_code: str,
    latitude: float,
    longitude: float,
    *,
    gps: bool = True,
) -> dict[str, object]:
    record: dict[str, object] = {
        "id": _MARKER,
        "google_id": 1,
        "name": name,
        "canonical_name": f"{name},{region},{country}",
        "country_code": country_code,
        "target_type": "City",
        "reach": 10,
    }
    if gps:
        record["gps"] = [longitude, latitude]
    return record


def _search_body(results: list[object] | None = None) -> dict[str, object]:
    return {
        "search_metadata": {"id": "search-1", "status": "Success"},
        "search_parameters": {"api_key": _KEY},
        "local_results": [] if results is None else results,
        "secret_blob": _MARKER,
    }


def _place_body(title: str, latitude: float, longitude: float) -> dict[str, object]:
    return {
        "search_metadata": {"id": "search-1", "status": "Success"},
        "search_parameters": {"api_key": _KEY},
        "place_results": {
            "title": title,
            "gps_coordinates": {"latitude": latitude, "longitude": longitude},
            "secret_blob": _MARKER,
        },
    }


def test_plan_budget_matches_the_shared_request_cap() -> None:
    """A paid destination fallback uses the same eight-request plan budget."""

    assert PLAN_BILLED_REQUEST_LIMIT == 8


@pytest.mark.parametrize("name", ["Jaipur", "London", "New York", "Tokyo"])
def test_a_single_locations_match_resolves_offline(name: str) -> None:
    """A complete free match stores the canonical place and its IANA zone."""

    region, country, code, latitude, longitude, zone = _CITIES[name]
    with respx.mock, SerpApiClient(_KEY, credit_limit=8) as client:
        route = respx.get(_LOCATIONS).mock(
            return_value=httpx.Response(
                200,
                json=[_city(name, region, country, code, latitude, longitude)],
            )
        )
        result = resolve_destination(name, client, clock=_CLOCK)
        charged = client.credits_charged

    destination = result.destination
    assert result.status is ResolutionStatus.resolved
    assert destination is not None
    assert destination.label == f"{name}, {region}, {country}"
    assert destination.country_code == code
    assert destination.region == region
    assert destination.latitude == pytest.approx(latitude)
    assert destination.longitude == pytest.approx(longitude)
    assert destination.serpapi_location == f"{name},{region},{country}"
    assert destination.timezone_name == zone
    assert destination.resolution_source is ResolutionSource.locations_api
    assert destination.confidence is not None
    assert destination.confidence.value == "high"
    assert result.choices == []
    assert result.billed_requests == 0
    assert charged == 0
    assert "api_key" not in str(route.calls[0].request.url)
    assert _MARKER not in result.model_dump_json()


def test_springfield_returns_three_choices_and_does_not_guess() -> None:
    """Several cities stay choices, including when the catalog returns more than three."""

    catalog = [
        _city("Springfield", "Illinois", "United States", "US", 39.7817213, -89.6501481),
        _city("Springfield", "Missouri", "United States", "US", 37.2089572, -93.2922989),
        _city("Springfield", "Massachusetts", "United States", "US", 42.1014831, -72.589811),
        _city("Springfield", "Oregon", "United States", "US", 44.0462362, -123.0220289),
    ]
    with respx.mock, SerpApiClient(_KEY, credit_limit=8) as client:
        respx.get(_LOCATIONS).mock(return_value=httpx.Response(200, json=catalog))
        search = respx.get(_SEARCH).mock(return_value=httpx.Response(500))
        result = resolve_destination(
            "Springfield",
            client,
            clock=_CLOCK,
            pending_date=PendingDate(phrase=DatePhrase.tomorrow),
        )

    assert result.status is ResolutionStatus.ambiguous
    assert result.destination is None
    assert result.local_time is None
    assert result.billed_requests == 0
    assert search.called is False
    assert [item.region for item in result.choices] == ["Illinois", "Missouri", "Massachusetts"]
    assert [item.timezone_name for item in result.choices] == [
        "America/Chicago",
        "America/Chicago",
        "America/New_York",
    ]
    rendered = result.model_dump_json()
    assert "Oregon" not in rendered
    assert _MARKER not in rendered


def test_an_unknown_place_is_unsupported_after_one_billed_lookup() -> None:
    """An empty free catalog and an empty Maps lookup are an unsupported location."""

    with respx.mock, SerpApiClient(_KEY, credit_limit=8) as client:
        respx.get(_LOCATIONS).mock(return_value=httpx.Response(200, json=[]))
        search = respx.get(_SEARCH).mock(return_value=httpx.Response(200, json=_search_body([])))
        result = resolve_destination("Zzznotaplace", client, clock=_CLOCK)

    assert result.status is ResolutionStatus.unsupported
    assert result.destination is None
    assert result.choices == []
    assert result.billed_requests == 1
    assert search.call_count == 1
    assert _MARKER not in result.model_dump_json()


def test_missing_coordinates_use_one_maps_lookup_inside_the_plan_budget() -> None:
    """A catalog row without gps spends one billed Maps lookup and keeps that source."""

    catalog = [_city("Jaipur", "Rajasthan", "India", "IN", 0, 0, gps=False)]
    maps = _place_body("Jaipur", 26.9124336, 75.7872709)
    with respx.mock, SerpApiClient(_KEY, credit_limit=8) as client:
        respx.get(_LOCATIONS).mock(return_value=httpx.Response(200, json=catalog))
        respx.get(_SEARCH).mock(return_value=httpx.Response(200, json=maps))
        result = resolve_destination("Jaipur", client, clock=_CLOCK)

    destination = result.destination
    assert result.status is ResolutionStatus.resolved
    assert result.billed_requests == 1
    assert client.credits_charged == 1
    assert destination is not None
    assert destination.resolution_source is ResolutionSource.maps_lookup
    assert destination.confidence is not None
    assert destination.confidence.value == "medium"
    assert destination.serpapi_location == "Jaipur,Rajasthan,India"
    assert destination.timezone_name == "Asia/Kolkata"
    assert destination.latitude == pytest.approx(26.9124336)
    assert _MARKER not in result.model_dump_json()


def test_a_catalog_place_without_coordinates_stays_unresolved_when_maps_has_none() -> None:
    """Missing coordinates stay missing when the billed lookup cannot fill them."""

    catalog = [_city("Jaipur", "Rajasthan", "India", "IN", 0, 0, gps=False)]
    with respx.mock, SerpApiClient(_KEY, credit_limit=8) as client:
        respx.get(_LOCATIONS).mock(return_value=httpx.Response(200, json=catalog))
        respx.get(_SEARCH).mock(return_value=httpx.Response(200, json=_search_body([])))
        result = resolve_destination("Jaipur", client, clock=_CLOCK)

    assert result.status is ResolutionStatus.missing_coordinates
    assert result.billed_requests == 1
    assert result.destination is not None
    assert result.destination.latitude is None
    assert result.destination.longitude is None
    assert result.destination.timezone_name is None
    assert result.local_time is None


def test_a_paid_lookup_is_refused_when_the_plan_budget_is_spent() -> None:
    """The eighth billed request leaves no credit for a destination fallback."""

    with (
        respx.mock as router,
        SerpApiClient(_KEY, credit_limit=PLAN_BILLED_REQUEST_LIMIT) as client,
    ):
        respx.get(_SEARCH).mock(return_value=httpx.Response(200, json=_search_body([])))
        respx.get(_LOCATIONS).mock(return_value=httpx.Response(200, json=[]))
        for _ in range(PLAN_BILLED_REQUEST_LIMIT):
            client.search_places("restaurants")
        calls_before = len(router.calls)
        result = resolve_destination("Zzznotaplace", client, clock=_CLOCK)
        extra_calls = len(router.calls) - calls_before

    assert result.status is ResolutionStatus.budget_exhausted
    assert result.billed_requests == 0
    assert client.credits_charged == PLAN_BILLED_REQUEST_LIMIT
    assert extra_calls == 1


def test_new_york_dst_gap_and_ambiguous_hour_are_explicit() -> None:
    """A spring-forward gap and a fall-back hour are not folded into one instant."""

    record = [_city("New York", "New York", "United States", "US", 40.7127753, -74.0059728)]
    with respx.mock, SerpApiClient(_KEY, credit_limit=8) as client:
        respx.get(_LOCATIONS).mock(return_value=httpx.Response(200, json=record))
        gap = resolve_destination(
            "New York",
            client,
            clock=_CLOCK,
            local_date=date(2026, 3, 8),
            local_start=time(2, 30),
        )
        ambiguous = resolve_destination(
            "New York",
            client,
            clock=_CLOCK,
            local_date=date(2026, 11, 1),
            local_start=time(1, 30),
        )

    assert gap.local_time is not None
    assert gap.local_time.wall_status is WallTimeStatus.gap
    assert gap.local_time.offsets == []
    assert gap.local_time.local_date == date(2026, 3, 8)
    assert gap.local_time.local_start == time(2, 30)
    assert ambiguous.local_time is not None
    assert ambiguous.local_time.wall_status is WallTimeStatus.ambiguous
    assert ambiguous.local_time.offsets == ["-04:00", "-05:00"]
    assert ambiguous.local_time.local_start == time(1, 30)


def test_today_and_tomorrow_follow_the_destination_zone() -> None:
    """The same instant is a different local day in Tokyo and New York."""

    tokyo = [_city("Tokyo", "Tokyo", "Japan", "JP", 35.6764225, 139.650027)]
    new_york = [_city("New York", "New York", "United States", "US", 40.7127753, -74.0059728)]
    with respx.mock, SerpApiClient(_KEY, credit_limit=8) as client:
        respx.get(_LOCATIONS).mock(
            side_effect=[
                httpx.Response(200, json=tokyo),
                httpx.Response(200, json=tokyo),
                httpx.Response(200, json=new_york),
                httpx.Response(200, json=new_york),
            ]
        )
        today_tokyo = interpret("Dinner in Tokyo today at 7pm", _CLOCK).brief
        tomorrow_tokyo = interpret("Dinner in Tokyo tomorrow at 7pm", _CLOCK).brief
        today_ny = interpret("Dinner in New York today at 7pm", _CLOCK).brief
        tomorrow_ny = interpret("Dinner in New York tomorrow at 7pm", _CLOCK).brief
        tokyo_today = resolve_destination(
            "Tokyo",
            client,
            clock=_CLOCK,
            pending_date=today_tokyo.pending_date,
            local_start=today_tokyo.local_start,
        )
        tokyo_tomorrow = resolve_destination(
            "Tokyo",
            client,
            clock=_CLOCK,
            pending_date=tomorrow_tokyo.pending_date,
            local_start=tomorrow_tokyo.local_start,
        )
        ny_today = resolve_destination(
            "New York",
            client,
            clock=_CLOCK,
            pending_date=today_ny.pending_date,
            local_start=today_ny.local_start,
        )
        ny_tomorrow = resolve_destination(
            "New York",
            client,
            clock=_CLOCK,
            pending_date=tomorrow_ny.pending_date,
            local_start=tomorrow_ny.local_start,
        )

    assert today_tokyo.local_date is None
    assert tokyo_today.local_time is not None
    assert tokyo_today.local_time.local_date == date(2026, 10, 5)
    assert tokyo_tomorrow.local_time is not None
    assert tokyo_tomorrow.local_time.local_date == date(2026, 10, 6)
    assert tokyo_tomorrow.local_time.wall_status is WallTimeStatus.unique
    assert tokyo_tomorrow.local_time.offsets == ["+09:00"]
    assert ny_today.local_time is not None
    assert ny_today.local_time.local_date == date(2026, 10, 4)
    assert ny_tomorrow.local_time is not None
    assert ny_tomorrow.local_time.local_date == date(2026, 10, 5)
    assert ny_tomorrow.local_time.offsets == ["-04:00"]


def test_next_weekday_candidates_are_chosen_in_the_destination_zone() -> None:
    """Next Friday stays two dates until the user picks one."""

    record = [_city("Tokyo", "Tokyo", "Japan", "JP", 35.6764225, 139.650027)]
    brief = interpret("Dinner in Tokyo next Friday at 7pm", _CLOCK).brief
    with respx.mock, SerpApiClient(_KEY, credit_limit=8) as client:
        respx.get(_LOCATIONS).mock(return_value=httpx.Response(200, json=record))
        result = resolve_destination(
            "Tokyo",
            client,
            clock=_CLOCK,
            pending_date=brief.pending_date,
            local_start=brief.local_start,
        )

    assert result.status is ResolutionStatus.resolved
    assert result.local_time is not None
    assert result.local_time.local_date is None
    assert result.local_time.date_candidates == ["2026-10-09", "2026-10-16"]
    assert result.local_time.wall_status is WallTimeStatus.not_checked


def test_coordinates_without_a_zone_are_an_unknown_timezone() -> None:
    """A dataset miss does not invent a zone or a local date."""

    record = [_city("Jaipur", "Rajasthan", "India", "IN", 26.9124336, 75.7872709)]
    with respx.mock, SerpApiClient(_KEY, credit_limit=8) as client:
        respx.get(_LOCATIONS).mock(return_value=httpx.Response(200, json=record))
        result = resolve_destination(
            "Jaipur",
            client,
            clock=_CLOCK,
            pending_date=PendingDate(phrase=DatePhrase.tomorrow),
            zone_at=lambda _latitude, _longitude: None,
        )

    assert result.status is ResolutionStatus.unknown_timezone
    assert result.local_time is None
    assert result.destination is not None
    assert result.destination.timezone_name is None
    assert result.destination.latitude == pytest.approx(26.9124336)
