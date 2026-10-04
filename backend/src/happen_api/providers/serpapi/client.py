"""Bounded SerpApi access for search, place, review, and location calls.

Search, place, review, and maps lookup attempts count toward the credit
budget, including a retry and including a response SerpApi might have served
from cache. The Locations API is free and does not count. The API key stays
in memory and on billed requests. Logs, errors, and returned records do not
include it, and location lookups do not keep the raw response.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any, Literal, Self
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from happen_api.logging import get_logger

_SEARCH_URL = "https://serpapi.com/search.json"
_LOCATIONS_URL = "https://serpapi.com/locations.json"
_ATTEMPT_TIMEOUT_SECONDS = 8.0
_TOTAL_TIMEOUT_SECONDS = 14.0
_RECOMMENDATION_CREDIT_LIMIT = 7
_SECRET_FIELD = re.compile(r"(key|token|secret|authorization|cookie)", re.IGNORECASE)
_API_KEY_QUERY = re.compile(r"(?i)(api_key=)[^&#\s]+")
_CREDENTIAL_URL_FIELDS = {"json_endpoint", "raw_html_file", "prettify_html_file"}
_RETRYABLE_TRANSPORT = (httpx.TimeoutException, httpx.NetworkError)
_Kind = Literal["search", "place", "reviews", "web"]


class SerpApiFailure(Exception):
    """A provider call stopped. The message is safe to log and return."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        immediate_retry: bool = False,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.immediate_retry = immediate_retry
        super().__init__(message)


class SupportedLocation(BaseModel):
    """One Locations API match. The raw catalog document is not kept."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    canonical_name: str | None = Field(default=None, max_length=120)
    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    target_type: str | None = Field(default=None, max_length=40)
    latitude: float | None = None
    longitude: float | None = None


class MapsCoordinate(BaseModel):
    """Coordinates taken from a billed Maps lookup. The raw search document is not kept."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)
    latitude: float
    longitude: float


class ProviderSnapshot(BaseModel):
    """One successful provider document with credential fields removed."""

    model_config = ConfigDict(extra="forbid")

    kind: _Kind
    search_id: str | None = None
    empty: bool
    attempts: int = Field(ge=1, le=2)
    credits_charged: int = Field(ge=1)
    payload: dict[str, Any]


class SerpApiClient:
    """Search, place, and review calls with one retry and a shared deadline.

    One instance is one recommendation. Its credit limit and fourteen-second
    budget apply to every call made with that instance.
    """

    def __init__(
        self,
        api_key: str,
        *,
        credit_limit: int = _RECOMMENDATION_CREDIT_LIMIT,
        total_timeout_seconds: float = _TOTAL_TIMEOUT_SECONDS,
        attempt_timeout_seconds: float = _ATTEMPT_TIMEOUT_SECONDS,
        now: Callable[[], float] | None = None,
        transport: httpx.BaseTransport | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if credit_limit < 1:
            raise ValueError("credit_limit must be at least 1")
        if not api_key.strip():
            raise SerpApiFailure(
                "AUTHENTICATION_FAILED",
                "SerpApi is not configured.",
                retryable=False,
            )
        self._api_key = api_key.strip()
        self._credit_limit = credit_limit
        self._total_timeout_seconds = total_timeout_seconds
        self._attempt_timeout_seconds = attempt_timeout_seconds
        self._now = now or _monotonic
        self._started: float | None = None
        self._credits_charged = 0
        self.live_enabled = True
        self.disabled_code: str | None = None
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(attempt_timeout_seconds),
        )

    def __repr__(self) -> str:
        return (
            f"SerpApiClient(live_enabled={self.live_enabled}, "
            f"credits_charged={self.credits_charged})"
        )

    @property
    def owns_http(self) -> bool:
        """Whether this instance created the HTTP client and must close it."""

        return self._owns_http

    def close(self) -> None:
        """Close an HTTP client this instance created. A shared client stays open."""

        if self._owns_http and not self._http.is_closed:
            self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def credits_charged(self) -> int:
        """Return how many attempts this client has sent."""

        return self._credits_charged

    def search_places(
        self,
        query: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> ProviderSnapshot:
        """Search Google Maps. Country and language are left to the provider."""

        if not query.strip():
            raise SerpApiFailure(
                "INVALID_REQUEST",
                "A place search needs a query.",
                retryable=False,
            )
        params = {
            "engine": "google_maps",
            "type": "search",
            "q": query.strip(),
            "output": "json",
        }
        if latitude is not None and longitude is not None:
            params["ll"] = f"@{latitude:.5f},{longitude:.5f},14z"
        return self._execute("search", params)

    def place_details(
        self,
        *,
        data_id: str | None = None,
        place_id: str | None = None,
    ) -> ProviderSnapshot:
        """Request one place, including hours and popular times when SerpApi has them."""

        return self._execute(
            "place",
            {
                "engine": "google_maps",
                "type": "place",
                "output": "json",
                **_place_identifier(data_id, place_id),
            },
        )

    def place_reviews(
        self,
        *,
        data_id: str | None = None,
        place_id: str | None = None,
    ) -> ProviderSnapshot:
        """Request review excerpts for one place."""

        return self._execute(
            "reviews",
            {
                "engine": "google_maps_reviews",
                "output": "json",
                **_place_identifier(data_id, place_id),
            },
        )

    def supported_locations(self, query: str, *, limit: int = 5) -> list[SupportedLocation]:
        """Query the free Locations API. This call does not consume a billed search."""

        self._ensure_live()
        cleaned = " ".join(query.split())
        if not cleaned or len(cleaned) > 120:
            raise SerpApiFailure(
                "INVALID_REQUEST",
                "A location search needs a query.",
                retryable=False,
            )
        if not _host_allowed(_LOCATIONS_URL):
            raise SerpApiFailure(
                "INVALID_DEPENDENCY_RESPONSE",
                "SerpApi returned a response Happen could not use.",
                retryable=False,
            )
        bounded = min(10, max(1, limit))
        params = {"q": cleaned, "limit": str(bounded)}
        last_failure: SerpApiFailure | None = None
        for _attempt in (1, 2):
            try:
                response = self._http.get(
                    _LOCATIONS_URL,
                    params=params,
                    timeout=httpx.Timeout(self._attempt_timeout_seconds),
                )
            except _RETRYABLE_TRANSPORT:
                _log_failure("TRANSIENT_DEPENDENCY")
                last_failure = SerpApiFailure(
                    "TRANSIENT_DEPENDENCY",
                    "SerpApi did not respond before the deadline.",
                    retryable=True,
                    immediate_retry=True,
                )
                continue
            except httpx.HTTPError:
                _log_failure("INVALID_DEPENDENCY_RESPONSE")
                raise SerpApiFailure(
                    "INVALID_DEPENDENCY_RESPONSE",
                    "SerpApi returned a response Happen could not use.",
                    retryable=False,
                ) from None
            parsed = _locations(response)
            if isinstance(parsed, list):
                _log_success(response.status_code)
                return parsed
            _log_failure(parsed.code)
            if parsed.immediate_retry:
                last_failure = parsed
                continue
            self._maybe_disable(parsed)
            raise parsed
        if last_failure is not None:
            raise last_failure
        raise SerpApiFailure(
            "TRANSIENT_DEPENDENCY",
            "SerpApi did not respond before the deadline.",
            retryable=True,
        )

    def lookup_maps_coordinates(self, query: str) -> list[MapsCoordinate]:
        """Run one billed Maps search and keep only coordinates."""

        cleaned = " ".join(query.split())
        if not cleaned:
            raise SerpApiFailure(
                "INVALID_REQUEST",
                "A place search needs a query.",
                retryable=False,
            )
        body = self._billed_success(
            {
                "engine": "google_maps",
                "type": "search",
                "q": cleaned,
                "output": "json",
            }
        )
        return _map_points(body)

    def web_search(self, query: str) -> ProviderSnapshot:
        """Run one Google web search through SerpApi. The result links are not fetched."""

        cleaned = " ".join(query.split())
        if not cleaned:
            raise SerpApiFailure(
                "INVALID_REQUEST",
                "A web search needs a query.",
                retryable=False,
            )
        return self._execute(
            "web",
            {
                "engine": "google",
                "q": cleaned,
                "output": "json",
            },
        )

    def _execute(self, kind: _Kind, params: dict[str, str]) -> ProviderSnapshot:
        body, attempts = self._billed_success_with_attempts(params)
        return self._snapshot(kind, body, attempts=attempts)

    def _billed_success(self, params: dict[str, str]) -> dict[str, Any]:
        body, _attempts = self._billed_success_with_attempts(params)
        return body

    def _billed_success_with_attempts(self, params: dict[str, str]) -> tuple[dict[str, Any], int]:
        self._ensure_live()
        started = self._mark_started()
        last_failure: SerpApiFailure | None = None
        for attempt in (1, 2):
            remaining = self._remaining(started)
            if remaining <= 0:
                break
            if self._credits_charged >= self._credit_limit:
                if last_failure is not None:
                    raise last_failure
                raise SerpApiFailure(
                    "CREDIT_BUDGET_EXCEEDED",
                    "The SerpApi credit budget for this recommendation is exhausted.",
                    retryable=False,
                )
            timeout = min(self._attempt_timeout_seconds, remaining)
            self._credits_charged += 1
            try:
                response = self._send(params, timeout)
            except _RETRYABLE_TRANSPORT:
                _log_failure("TRANSIENT_DEPENDENCY")
                last_failure = SerpApiFailure(
                    "TRANSIENT_DEPENDENCY",
                    "SerpApi did not respond before the deadline.",
                    retryable=True,
                    immediate_retry=True,
                )
                continue
            except httpx.HTTPError:
                _log_failure("INVALID_DEPENDENCY_RESPONSE")
                raise SerpApiFailure(
                    "INVALID_DEPENDENCY_RESPONSE",
                    "SerpApi returned a response Happen could not use.",
                    retryable=False,
                ) from None
            interpreted = self._interpret(response)
            if isinstance(interpreted, dict):
                _log_success(response.status_code)
                return interpreted, attempt
            _log_failure(interpreted.code)
            if interpreted.immediate_retry:
                last_failure = interpreted
                continue
            self._maybe_disable(interpreted)
            raise interpreted
        if last_failure is not None:
            raise last_failure
        raise SerpApiFailure(
            "TRANSIENT_DEPENDENCY",
            "SerpApi did not respond before the deadline.",
            retryable=True,
        )

    def _ensure_live(self) -> None:
        if self.live_enabled:
            return
        raise SerpApiFailure(
            "LIVE_DISABLED",
            "Live SerpApi mode is disabled.",
            retryable=False,
        )

    def _maybe_disable(self, failure: SerpApiFailure) -> None:
        if failure.code not in {"AUTHENTICATION_FAILED", "QUOTA_EXHAUSTED"}:
            return
        self.live_enabled = False
        self.disabled_code = failure.code

    def _mark_started(self) -> float:
        if self._started is None:
            self._started = self._now()
        return self._started

    def _remaining(self, started: float) -> float:
        return self._total_timeout_seconds - (self._now() - started)

    def _send(self, params: dict[str, str], timeout: float) -> httpx.Response:
        if not _host_allowed(_SEARCH_URL):
            raise SerpApiFailure(
                "INVALID_DEPENDENCY_RESPONSE",
                "SerpApi returned a response Happen could not use.",
                retryable=False,
            )
        request_params = {**params, "api_key": self._api_key}
        return self._http.get(
            _SEARCH_URL,
            params=request_params,
            timeout=httpx.Timeout(timeout),
        )

    def _interpret(self, response: httpx.Response) -> SerpApiFailure | dict[str, Any]:
        failure = _status_failure(response)
        if failure is not None:
            return failure
        try:
            body = response.json()
        except json.JSONDecodeError:
            return SerpApiFailure(
                "INVALID_DEPENDENCY_RESPONSE",
                "SerpApi returned a response Happen could not use.",
                retryable=False,
            )
        if not isinstance(body, dict):
            return SerpApiFailure(
                "INVALID_DEPENDENCY_RESPONSE",
                "SerpApi returned a response Happen could not use.",
                retryable=False,
            )
        metadata = body.get("search_metadata")
        if not isinstance(metadata, dict) or metadata.get("status") != "Success":
            return SerpApiFailure(
                "INVALID_DEPENDENCY_RESPONSE",
                "SerpApi returned a response Happen could not use.",
                retryable=False,
            )
        return body

    def _snapshot(self, kind: _Kind, body: dict[str, Any], *, attempts: int) -> ProviderSnapshot:
        payload = redact_provider_document(body, self._api_key)
        metadata = payload.get("search_metadata")
        search_id = metadata.get("id") if isinstance(metadata, dict) else None
        if not isinstance(search_id, str):
            search_id = None
        empty = _is_empty(kind, payload)
        if empty is None:
            raise SerpApiFailure(
                "INVALID_DEPENDENCY_RESPONSE",
                "SerpApi returned a response Happen could not use.",
                retryable=False,
            )
        return ProviderSnapshot(
            kind=kind,
            search_id=search_id,
            empty=empty,
            attempts=attempts,
            credits_charged=self._credits_charged,
            payload=payload,
        )


def redact_provider_document(value: dict[str, Any], api_key: str) -> dict[str, Any]:
    """Return a copy with credential fields and echoed key values removed."""

    redacted = _redact_value(value, api_key)
    if not isinstance(redacted, dict):
        return {}
    return redacted


def _redact_value(value: object, api_key: str) -> object:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name in _CREDENTIAL_URL_FIELDS or _SECRET_FIELD.search(name):
                continue
            cleaned[name] = _redact_value(item, api_key)
        return cleaned
    if isinstance(value, list):
        return [_redact_value(item, api_key) for item in value]
    if isinstance(value, str):
        hidden = _API_KEY_QUERY.sub(r"\1[redacted]", value)
        if api_key:
            hidden = hidden.replace(api_key, "[redacted]")
        return hidden
    return value


def _status_failure(response: httpx.Response) -> SerpApiFailure | None:
    if 300 <= response.status_code < 400:
        return SerpApiFailure(
            "INVALID_DEPENDENCY_RESPONSE",
            "SerpApi returned a response Happen could not use.",
            retryable=False,
        )
    error_text = _error_text(response)
    if response.status_code == 401 or _mentions_invalid_key(response.status_code, error_text):
        return SerpApiFailure(
            "AUTHENTICATION_FAILED",
            "SerpApi rejected the API key.",
            retryable=False,
        )
    if _is_quota(error_text):
        return SerpApiFailure(
            "QUOTA_EXHAUSTED",
            "SerpApi search quota is exhausted.",
            retryable=False,
        )
    if response.status_code == 429:
        return SerpApiFailure(
            "TRANSIENT_DEPENDENCY",
            "SerpApi is temporarily unavailable.",
            retryable=True,
        )
    if response.status_code >= 500:
        return SerpApiFailure(
            "TRANSIENT_DEPENDENCY",
            "SerpApi returned a server error.",
            retryable=True,
            immediate_retry=True,
        )
    if response.status_code >= 400:
        return SerpApiFailure(
            "PROVIDER_REJECTED",
            "SerpApi rejected the request.",
            retryable=False,
        )
    if response.status_code != 200 or error_text:
        return SerpApiFailure(
            "INVALID_DEPENDENCY_RESPONSE",
            "SerpApi returned a response Happen could not use.",
            retryable=False,
        )
    return None


def _locations(response: httpx.Response) -> SerpApiFailure | list[SupportedLocation]:
    failure = _status_failure(response)
    if failure is not None:
        return failure
    try:
        body = response.json()
    except json.JSONDecodeError:
        return SerpApiFailure(
            "INVALID_DEPENDENCY_RESPONSE",
            "SerpApi returned a response Happen could not use.",
            retryable=False,
        )
    if not isinstance(body, list):
        return SerpApiFailure(
            "INVALID_DEPENDENCY_RESPONSE",
            "SerpApi returned a response Happen could not use.",
            retryable=False,
        )
    found: list[SupportedLocation] = []
    for item in body:
        if isinstance(item, dict):
            parsed = _one_location(item)
            if parsed is not None:
                found.append(parsed)
    return found


def _one_location(item: dict[str, Any]) -> SupportedLocation | None:
    name = item.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        return None
    canonical = item.get("canonical_name")
    if not isinstance(canonical, str) or not canonical.strip():
        canonical_name = None
    else:
        canonical_name = canonical.strip()[:120]
    country = item.get("country_code")
    if isinstance(country, str) and len(country) == 2 and country.isalpha():
        country_code = country.upper()
    else:
        country_code = None
    target = item.get("target_type")
    target_type = target.strip()[:40] if isinstance(target, str) and target.strip() else None
    latitude, longitude = _location_gps(item.get("gps"))
    return SupportedLocation(
        name=name.strip(),
        canonical_name=canonical_name,
        country_code=country_code,
        target_type=target_type,
        latitude=latitude,
        longitude=longitude,
    )


def _location_gps(value: object) -> tuple[float | None, float | None]:
    """Locations API gps is longitude, then latitude."""

    if not isinstance(value, list) or len(value) != 2:
        return None, None
    longitude, latitude = value
    if not _axis(longitude, -180, 180) or not _axis(latitude, -90, 90):
        return None, None
    return float(latitude), float(longitude)


def _axis(value: object, low: float, high: float) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return low <= float(value) <= high


def _map_points(body: dict[str, Any]) -> list[MapsCoordinate]:
    place = body.get("place_results")
    if isinstance(place, dict):
        point = _map_point(place.get("title"), place.get("gps_coordinates"))
        if point is not None:
            return [point]
    results = body.get("local_results")
    points: list[MapsCoordinate] = []
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            point = _map_point(item.get("title"), item.get("gps_coordinates"))
            if point is not None:
                points.append(point)
    return points[:3]


def _map_point(title: object, coordinates: object) -> MapsCoordinate | None:
    if not isinstance(coordinates, dict):
        return None
    latitude = coordinates.get("latitude")
    longitude = coordinates.get("longitude")
    if not _axis(latitude, -90, 90) or not _axis(longitude, -180, 180):
        return None
    label = title.strip()[:120] if isinstance(title, str) and title.strip() else None
    return MapsCoordinate(title=label, latitude=float(latitude), longitude=float(longitude))


def _place_identifier(data_id: str | None, place_id: str | None) -> dict[str, str]:
    data = data_id.strip() if data_id else ""
    place = place_id.strip() if place_id else ""
    if bool(data) == bool(place):
        raise SerpApiFailure(
            "INVALID_REQUEST",
            "A place request needs either a data id or a place id.",
            retryable=False,
        )
    if data:
        return {"data_id": data}
    return {"place_id": place}


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except json.JSONDecodeError:
        return ""
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        return body["error"]
    return ""


def _mentions_invalid_key(status_code: int, error_text: str) -> bool:
    if status_code not in {401, 403}:
        return False
    return "api key" in error_text.lower()


def _is_quota(error_text: str) -> bool:
    lowered = error_text.lower()
    return "run out of searches" in lowered or "no searches left" in lowered


def _is_empty(kind: _Kind, payload: dict[str, Any]) -> bool | None:
    if kind == "search":
        results = payload.get("local_results")
        if not isinstance(results, list):
            return None
        return len(results) == 0
    if kind == "web":
        organic = payload.get("organic_results")
        if not isinstance(organic, list):
            return None
        return len(organic) == 0
    if kind == "place":
        place = payload.get("place_results")
        if place is None:
            return True
        if isinstance(place, dict):
            return len(place) == 0
        return None
    reviews = payload.get("reviews")
    if reviews is None:
        return True
    if isinstance(reviews, list):
        return len(reviews) == 0
    return None


def _monotonic() -> float:
    return time.monotonic()


def _log_success(status_code: int) -> None:
    get_logger().info(
        "serpapi request finished",
        extra={"status_code": status_code, "endpoint": "serpapi"},
    )


def _log_failure(error_code: str) -> None:
    get_logger().info(
        "serpapi request failed",
        extra={"error_code": error_code, "endpoint": "serpapi"},
    )


def _host_allowed(url: str) -> bool:
    """Reject unexpected hosts so the key is only sent to SerpApi."""

    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.netloc == "serpapi.com"
