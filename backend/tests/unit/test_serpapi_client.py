"""SerpApi client contracts. Requests are mocked and the live key is never used."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import httpx
import pytest
import respx

from happen_api.logging import JsonFormatter, SecretRedactionFilter, get_logger
from happen_api.providers.serpapi.client import SerpApiClient, SerpApiFailure

_KEY = "live-key-value"
_URL = "https://serpapi.com/search.json"


def _metadata(key: str, status: str = "Success") -> dict[str, object]:
    return {
        "id": "search-1",
        "status": status,
        "json_endpoint": f"https://serpapi.com/searches/search-1.json?api_key={key}",
        "raw_html_file": f"https://serpapi.com/searches/search-1.html?api_key={key}",
        "total_time_taken": 1.2,
    }


def _search_body(key: str, results: list[object] | None = None) -> dict[str, object]:
    if results is None:
        results = [{"title": "Chianti", "place_id": "place-1", "phone": "+91 000"}]
    return {
        "search_metadata": _metadata(key),
        "search_parameters": {"engine": "google_maps", "q": "restaurants", "api_key": key},
        "local_results": results,
    }


def _client(
    *,
    credit_limit: int = 7,
    now: Callable[[], float] | None = None,
) -> SerpApiClient:
    return SerpApiClient(_KEY, credit_limit=credit_limit, now=now)


def _params(request: httpx.Request) -> dict[str, str]:
    return dict(request.url.params)


def test_search_redacts_the_key_and_counts_one_credit() -> None:
    """Verify a successful search charges one credit and returns no credential."""

    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(return_value=httpx.Response(200, json=_search_body(_KEY)))
        snapshot = client.search_places("restaurants in Indiranagar, Bengaluru")

    assert snapshot.kind == "search"
    assert snapshot.search_id == "search-1"
    assert snapshot.empty is False
    assert snapshot.attempts == 1
    assert snapshot.credits_charged == 1
    rendered = json.dumps(snapshot.model_dump())
    assert _KEY not in rendered
    assert "json_endpoint" not in snapshot.payload["search_metadata"]
    assert "api_key" not in snapshot.payload["search_parameters"]
    sent = _params(route.calls[0].request)
    assert sent["api_key"] == _KEY
    assert sent["engine"] == "google_maps"
    assert sent["type"] == "search"
    assert "hl" not in sent
    assert "gl" not in sent
    assert sent["output"] == "json"
    assert "no_cache" not in sent
    assert _KEY not in repr(client)


def test_place_and_review_calls_use_one_identifier() -> None:
    """Verify place and review calls send the locked engine parameters."""

    place = {
        "search_metadata": _metadata(_KEY),
        "place_results": {"title": "Chianti", "data_id": "data-1"},
    }
    reviews = {
        "search_metadata": _metadata(_KEY),
        "reviews": [
            {"snippet": "Quiet at 7.", "date": "2026-10-01", "link": "https://example.com"}
        ],
    }
    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(
            side_effect=[
                httpx.Response(200, json=place),
                httpx.Response(200, json=reviews),
            ]
        )
        place_snapshot = client.place_details(data_id="data-1")
        review_snapshot = client.place_reviews(place_id="place-1")

    assert place_snapshot.empty is False
    assert review_snapshot.empty is False
    assert _params(route.calls[0].request)["type"] == "place"
    assert _params(route.calls[0].request)["data_id"] == "data-1"
    assert _params(route.calls[1].request)["engine"] == "google_maps_reviews"
    assert _params(route.calls[1].request)["place_id"] == "place-1"
    assert client.credits_charged == 2


def test_empty_search_is_a_successful_insufficiency() -> None:
    """Verify an empty successful search is returned instead of treated as a failure."""

    with respx.mock, _client() as client:
        respx.get(_URL).mock(return_value=httpx.Response(200, json=_search_body(_KEY, [])))
        snapshot = client.search_places("restaurants in Indiranagar, Bengaluru")

    assert snapshot.empty is True
    assert snapshot.payload["local_results"] == []


def test_client_error_is_not_retried() -> None:
    """Verify a rejected parameter request is sent once."""

    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(
            return_value=httpx.Response(400, json={"error": "Invalid parameters."})
        )
        with pytest.raises(SerpApiFailure) as caught:
            client.search_places("restaurants in Indiranagar, Bengaluru")

    assert caught.value.code == "PROVIDER_REJECTED"
    assert caught.value.retryable is False
    assert len(route.calls) == 1
    assert client.credits_charged == 1
    assert client.live_enabled is True
    assert _KEY not in str(caught.value)


def test_server_error_retries_once_then_succeeds() -> None:
    """Verify one 5xx response is retried and the second attempt can succeed."""

    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(
            side_effect=[
                httpx.Response(503, json={"error": "unavailable"}),
                httpx.Response(200, json=_search_body(_KEY)),
            ]
        )
        snapshot = client.search_places("restaurants in Indiranagar, Bengaluru")

    assert snapshot.attempts == 2
    assert snapshot.credits_charged == 2
    assert len(route.calls) == 2


def test_repeated_server_error_stays_transient() -> None:
    """Verify a second 5xx response stops the call without disabling live mode."""

    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(return_value=httpx.Response(500, json={"error": "down"}))
        with pytest.raises(SerpApiFailure) as caught:
            client.search_places("restaurants in Indiranagar, Bengaluru")

    assert caught.value.code == "TRANSIENT_DEPENDENCY"
    assert len(route.calls) == 2
    assert client.credits_charged == 2
    assert client.live_enabled is True


@pytest.mark.parametrize(
    "failure",
    [httpx.ReadTimeout("timed out"), httpx.ConnectError("connection failed")],
)
def test_transport_failure_retries_once(failure: Exception) -> None:
    """Verify a timeout or connection failure is sent once more."""

    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(
            side_effect=[failure, httpx.Response(200, json=_search_body(_KEY))]
        )
        snapshot = client.search_places("restaurants in Indiranagar, Bengaluru")

    assert snapshot.attempts == 2
    assert len(route.calls) == 2


def test_timeout_after_the_deadline_does_not_retry() -> None:
    """Verify a timed-out attempt is not retried once the shared deadline is spent."""

    clock = {"now": 0.0}

    def now() -> float:
        return clock["now"]

    def expire(_request: httpx.Request) -> httpx.Response:
        clock["now"] = 14.0
        raise httpx.ReadTimeout("timed out")

    with respx.mock, _client(now=now) as client:
        route = respx.get(_URL).mock(side_effect=expire)
        with pytest.raises(SerpApiFailure) as caught:
            client.search_places("restaurants in Indiranagar, Bengaluru")

    assert caught.value.code == "TRANSIENT_DEPENDENCY"
    assert len(route.calls) == 1
    assert client.credits_charged == 1


def test_later_call_stops_when_the_shared_deadline_is_spent() -> None:
    """Verify calls share one fourteen-second budget."""

    clock = {"now": 0.0}

    def now() -> float:
        return clock["now"]

    with respx.mock, _client(now=now) as client:
        route = respx.get(_URL).mock(return_value=httpx.Response(200, json=_search_body(_KEY)))
        client.search_places("restaurants in Indiranagar, Bengaluru")
        clock["now"] = 14.0
        with pytest.raises(SerpApiFailure) as caught:
            client.place_details(data_id="data-1")

    assert caught.value.code == "TRANSIENT_DEPENDENCY"
    assert len(route.calls) == 1


def test_attempt_timeout_uses_the_time_remaining() -> None:
    """Verify a single attempt asks for at most eight seconds and never more than the budget."""

    times = iter((0.0, 11.0))

    def now() -> float:
        return next(times)

    with respx.mock, _client(now=now) as client:
        route = respx.get(_URL).mock(return_value=httpx.Response(200, json=_search_body(_KEY)))
        client.search_places("restaurants in Indiranagar, Bengaluru")

    timeout = route.calls[0].request.extensions["timeout"]
    assert timeout["read"] == 3.0


def test_quota_failure_disables_live_mode() -> None:
    """Verify exhausted search quota is not retried and later calls do not hit the network."""

    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(
            return_value=httpx.Response(
                429, json={"error": "Your account has run out of searches."}
            )
        )
        with pytest.raises(SerpApiFailure) as first:
            client.search_places("restaurants in Indiranagar, Bengaluru")
        with pytest.raises(SerpApiFailure) as second:
            client.search_places("restaurants in Indiranagar, Bengaluru")

    assert first.value.code == "QUOTA_EXHAUSTED"
    assert second.value.code == "LIVE_DISABLED"
    assert client.live_enabled is False
    assert client.disabled_code == "QUOTA_EXHAUSTED"
    assert len(route.calls) == 1
    assert _KEY not in str(first.value)


def test_authentication_failure_disables_live_mode() -> None:
    """Verify an invalid key disables live mode without a retry."""

    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(
            return_value=httpx.Response(401, json={"error": "Invalid API key."})
        )
        with pytest.raises(SerpApiFailure) as caught:
            client.search_places("restaurants in Indiranagar, Bengaluru")

    assert caught.value.code == "AUTHENTICATION_FAILED"
    assert len(route.calls) == 1
    assert client.live_enabled is False
    with pytest.raises(SerpApiFailure) as blocked:
        client.place_details(place_id="place-1")
    assert blocked.value.code == "LIVE_DISABLED"


def test_unlabeled_rate_limit_is_not_retried() -> None:
    """Verify a 429 without a quota message does not spend a second attempt."""

    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(return_value=httpx.Response(429, json={"error": "Slow down."}))
        with pytest.raises(SerpApiFailure) as caught:
            client.search_places("restaurants in Indiranagar, Bengaluru")

    assert caught.value.code == "TRANSIENT_DEPENDENCY"
    assert caught.value.immediate_retry is False
    assert len(route.calls) == 1
    assert client.live_enabled is True


def test_malformed_json_is_an_invalid_dependency_response() -> None:
    """Verify a 200 response that is not JSON fails once without a retry."""

    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(return_value=httpx.Response(200, content=b"not-json"))
        with pytest.raises(SerpApiFailure) as caught:
            client.search_places("restaurants in Indiranagar, Bengaluru")

    assert caught.value.code == "INVALID_DEPENDENCY_RESPONSE"
    assert len(route.calls) == 1


def test_redirect_is_not_followed() -> None:
    """Verify a redirect is rejected so the key is not sent to another host."""

    location = f"https://evil.example/search?api_key={_KEY}"
    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(
            return_value=httpx.Response(302, headers={"location": location})
        )
        with pytest.raises(SerpApiFailure) as caught:
            client.search_places("restaurants in Indiranagar, Bengaluru")

    assert caught.value.code == "INVALID_DEPENDENCY_RESPONSE"
    assert len(route.calls) == 1
    assert _KEY not in str(caught.value)


def test_credit_budget_stops_before_another_request() -> None:
    """Verify the client refuses to send once its credit limit is reached."""

    with respx.mock, _client(credit_limit=1) as client:
        route = respx.get(_URL).mock(return_value=httpx.Response(200, json=_search_body(_KEY)))
        client.search_places("restaurants in Indiranagar, Bengaluru")
        with pytest.raises(SerpApiFailure) as caught:
            client.place_details(data_id="data-1")

    assert caught.value.code == "CREDIT_BUDGET_EXCEEDED"
    assert len(route.calls) == 1
    assert client.live_enabled is True


def test_missing_key_fails_before_a_request() -> None:
    """Verify an empty key never opens a request."""

    with pytest.raises(SerpApiFailure) as caught:
        SerpApiClient("  ")
    assert caught.value.code == "AUTHENTICATION_FAILED"


def test_blank_query_and_missing_identifier_do_not_call_the_provider() -> None:
    """Verify local request mistakes are rejected before SerpApi is contacted."""

    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(return_value=httpx.Response(500))
        with pytest.raises(SerpApiFailure) as blank:
            client.search_places("  ")
        with pytest.raises(SerpApiFailure) as missing:
            client.place_details()

    assert blank.value.code == "INVALID_REQUEST"
    assert missing.value.code == "INVALID_REQUEST"
    assert route.called is False


def test_logs_omit_the_api_key() -> None:
    """Verify operational logs name the provider without the request URL or key."""

    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(JsonFormatter().format(record))

    logger = get_logger()
    handler = _Capture()
    handler.addFilter(SecretRedactionFilter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with respx.mock, _client() as client:
            respx.get(_URL).mock(return_value=httpx.Response(200, json=_search_body(_KEY)))
            client.search_places("restaurants in Indiranagar, Bengaluru")
    finally:
        logger.removeHandler(handler)

    rendered = "\n".join(records)
    assert _KEY not in rendered
    assert "serpapi.com" not in rendered
    payload = json.loads(records[0])
    assert payload["message"] == "serpapi request finished"
    assert payload["endpoint"] == "serpapi"
    assert payload["status_code"] == 200


def test_locations_lookup_is_free_and_discards_the_payload() -> None:
    """The Locations API does not spend a credit, send the key, or keep the raw document."""

    body = [
        {
            "id": "raw-payload-marker",
            "google_id": 1,
            "name": "Jaipur",
            "canonical_name": "Jaipur,Rajasthan,India",
            "country_code": "IN",
            "target_type": "City",
            "reach": 10,
            "gps": [75.7872709, 26.9124336],
        }
    ]
    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    logger = get_logger()
    handler = _Capture()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with respx.mock, _client() as client:
            route = respx.get("https://serpapi.com/locations.json").mock(
                return_value=httpx.Response(200, json=body)
            )
            found = client.supported_locations("Jaipur")
            charged = client.credits_charged
    finally:
        logger.removeHandler(handler)

    assert charged == 0
    assert "api_key" not in str(route.calls[0].request.url)
    assert found[0].name == "Jaipur"
    assert found[0].latitude == pytest.approx(26.9124336)
    assert found[0].longitude == pytest.approx(75.7872709)
    rendered = found[0].model_dump_json()
    assert "raw-payload-marker" not in rendered
    assert "raw-payload-marker" not in "\n".join(records)


def test_maps_coordinate_lookup_is_billed_and_keeps_only_coordinates() -> None:
    """A Maps lookup counts as one search and does not return the provider document."""

    body = {
        "search_metadata": _metadata(_KEY),
        "search_parameters": {"api_key": _KEY, "engine": "google_maps"},
        "place_results": {
            "title": "Jaipur",
            "gps_coordinates": {"latitude": 26.9124336, "longitude": 75.7872709},
            "secret_blob": "raw-payload-marker",
        },
    }
    with respx.mock, _client() as client:
        route = respx.get(_URL).mock(return_value=httpx.Response(200, json=body))
        points = client.lookup_maps_coordinates("Jaipur,Rajasthan,India")

    assert client.credits_charged == 1
    sent = _params(route.calls[0].request)
    assert sent["engine"] == "google_maps"
    assert sent["type"] == "search"
    assert "hl" not in sent
    assert "gl" not in sent
    assert points[0].latitude == pytest.approx(26.9124336)
    assert "raw-payload-marker" not in points[0].model_dump_json()
    assert _KEY not in points[0].model_dump_json()
