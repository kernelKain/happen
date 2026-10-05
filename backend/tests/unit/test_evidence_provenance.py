"""Every displayed claim keeps its provenance and its safe source link.

The rules under test:

- an official-domain result stays official and a community host stays community;
- the exact safe result URL survives to the response;
- Maps hours stay Maps evidence even when an official site exists;
- a conflict is recorded only when normalization proves incompatible claims;
- unsafe, credential-bearing, local, or non-HTTP links are never shown;
- reviews are requested only when a constraint can be evaluated from them.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import ClassVar

import pytest

from happen_api.planning.constraints import EveningConstraints
from happen_api.planning.contracts import IntentKind, PlaceIntent, ResolvedDestination
from happen_api.planning.discovery import DiscoveredPlace, _apply_web, _place_from_record
from happen_api.planning.evidence import (
    ClaimField,
    ClaimKind,
    MatchMethod,
    Verification,
    safe_link,
    safe_link_text,
)
from happen_api.planning.itinerary import EvidenceSource, assemble_itinerary

RETRIEVED = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
MONDAY = date(2026, 10, 5)
ARRIVAL = time(19, 0)
DESTINATION = ResolvedDestination(
    label="Kyoto, Kyoto, Japan",
    source_text="Kyoto",
    locality="Kyoto",
    region="Kyoto",
    country_code="JP",
    timezone_name="Asia/Tokyo",
    latitude=35.0116,
    longitude=135.7681,
    serpapi_location="Kyoto,Kyoto,Japan",
    confidence="high",
    resolution_source="locations_api",
    provenance=None,
)


def _place(**updates: object) -> DiscoveredPlace:
    record: dict[str, object] = {
        "title": "Kura",
        "place_id": "ChIJkura",
        "data_id": "data-kura",
        "address": "Kawaramachi, Kyoto",
        "gps_coordinates": {"latitude": 35.0, "longitude": 135.7},
        "website": "https://kura.example",
        "link": "https://maps.example/kura",
        "rating": 4.5,
        "reviews": 120,
        "operating_hours": {"monday": "6:00 PM–11:00 PM"},
    }
    record.update(updates)
    found = _place_from_record(record, IntentKind.dinner)
    assert found is not None
    return found


def _rows(*rows: dict[str, object]) -> list[dict[str, object]]:
    return list(rows)


def _plan(place: DiscoveredPlace, preferences: list[str] | None = None):
    return assemble_itinerary(
        [place],
        [PlaceIntent(kind=IntentKind.dinner, label="dinner", position=1)],
        local_date=MONDAY,
        local_start=ARRIVAL,
        retrieved_at=RETRIEVED,
        preferences=preferences or [],
    )


def test_an_official_domain_result_stays_official() -> None:
    """Verify an official-page snippet is not filed as a community note."""

    place = _place()
    _apply_web(
        place,
        _rows(
            {
                "title": "Kura hours",
                "link": "https://kura.example/hours",
                "snippet": "Kura in Kyoto opens at 6pm every evening.",
            }
        ),
        DESTINATION,
    )
    assert [claim.kind for claim in place.claims] == [ClaimKind.official]
    assert place.community_notes == []
    assert place.claims[0].matched_by is MatchMethod.official_domain
    assert str(place.claims[0].url) == "https://kura.example/hours"


def test_a_community_result_stays_community() -> None:
    """Verify a community host stays community and keeps its own URL."""

    place = _place()
    _apply_web(
        place,
        _rows(
            {
                "title": "Kura thread",
                "link": "https://www.reddit.com/r/kyoto/comments/abc",
                "snippet": "Kura in Kyoto is busy but the ramen is good.",
            }
        ),
        DESTINATION,
    )
    assert [claim.kind for claim in place.claims] == [ClaimKind.community]
    assert str(place.claims[0].url) == "https://www.reddit.com/r/kyoto/comments/abc"
    assert place.community_notes == ["Kura in Kyoto is busy but the ramen is good."]


def test_a_result_for_another_place_is_not_claimed() -> None:
    """Verify a row that does not match this entity is skipped entirely."""

    place = _place()
    _apply_web(
        place,
        _rows(
            {
                "title": "Another pub",
                "link": "https://www.reddit.com/r/kyoto/comments/other",
                "snippet": "Another pub in Kyoto is closed on Monday.",
            },
            {
                "title": "Opening hours",
                "link": "https://kura.example/hours",
                # The place is not named, so this cannot be tied to it.
                "snippet": "Some other restaurant nearby lists its hours.",
            },
        ),
        DESTINATION,
    )
    assert place.claims == []


def test_the_exact_safe_url_reaches_the_stop() -> None:
    """Verify the result URL is not discarded before the itinerary is assembled."""

    place = _place()
    _apply_web(
        place,
        _rows(
            {
                "title": "Kura hours",
                "link": "https://kura.example/hours?utm_source=serp",
                "snippet": "Kura in Kyoto opens at 6pm.",
            }
        ),
        DESTINATION,
    )
    stop = _plan(place).stops[0]
    official = [item for item in stop.evidence if item.source is EvidenceSource.official]
    assert any(str(item.url) == "https://kura.example/hours?utm_source=serp" for item in official)


def test_maps_hours_stay_maps_evidence_alongside_an_official_site() -> None:
    """Verify Maps hours are not re-labelled because an official site exists."""

    stop = _plan(_place()).stops[0]
    maps = [item for item in stop.evidence if item.source is EvidenceSource.maps]
    assert maps, "Maps hours must remain Maps evidence"
    assert all(item.field is ClaimField.hours for item in maps)
    assert all(item.url is None or str(item.url) == "https://maps.example/kura" for item in maps)
    assert any("6:00 PM" in item.text for item in maps)


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("file:///etc/passwd", id="local-file"),
        pytest.param("ftp://example.com/x", id="ftp"),
        pytest.param("javascript:alert(1)", id="javascript"),
        pytest.param("http://localhost:8000/x", id="localhost"),
        pytest.param("http://127.0.0.1/x", id="loopback"),
        pytest.param("https://evil.example/x?api_key=SECRET", id="credential"),
        pytest.param("https://user:pw@evil.example/x", id="userinfo"),
        pytest.param("https://box.local/x", id="dot-local"),
        pytest.param("", id="empty"),
        pytest.param(None, id="none"),
    ],
)
def test_unsafe_or_credential_bearing_links_are_not_linked(url: object) -> None:
    """Verify an unsafe URL is dropped rather than rendered as a link."""

    assert safe_link(url) is None
    assert safe_link_text(url) is None


def test_a_safe_public_url_is_kept_exactly() -> None:
    """Verify a normal result URL is preserved verbatim."""

    assert safe_link_text("https://kura.example/hours") == "https://kura.example/hours"
    assert safe_link_text("https://maps.example/place?id=7") == "https://maps.example/place?id=7"


def test_an_unsafe_url_is_dropped_from_the_claim() -> None:
    """Verify a matched but unsafe result keeps its text and loses only the link."""

    place = _place()
    _apply_web(
        place,
        _rows(
            {
                "title": "Kura thread",
                "link": "https://www.reddit.com/r/kyoto/comments/1?api_key=SECRET",
                "snippet": "Kura in Kyoto is worth the trip.",
            }
        ),
        DESTINATION,
    )
    assert place.claims
    assert place.claims[0].url is None
    assert place.claims[0].linked is False
    assert place.claims[0].text == "Kura in Kyoto is worth the trip."


def test_a_contradiction_is_recorded_only_when_proven() -> None:
    """Verify an incompatible claim becomes a conflict and the official wins."""

    place = _place(operating_hours={"monday": "6:00 PM–11:00 PM"})
    _apply_web(
        place,
        _rows(
            {
                "title": "Kura thread",
                "link": "https://www.reddit.com/r/kyoto/comments/1",
                "snippet": "Kura in Kyoto is closed on Monday.",
            }
        ),
        DESTINATION,
    )
    assert len(place.claim_conflicts) == 1
    conflict = place.claim_conflicts[0]
    assert conflict.field is ClaimField.hours
    # Official normalized hours take precedence over community text.
    assert conflict.resolved.kind is ClaimKind.maps
    assert conflict.resolved.verification is Verification.conflicting
    assert conflict.secondary.kind is ClaimKind.community


def test_agreement_between_the_record_and_a_claim_is_not_a_conflict() -> None:
    """Verify two sources saying the same thing raise no disagreement."""

    place = _place(operating_hours={"monday": "6:00 PM–11:00 PM"})
    _apply_web(
        place,
        _rows(
            {
                "title": "Kura thread",
                "link": "https://www.reddit.com/r/kyoto/comments/1",
                "snippet": "Kura in Kyoto is open on Monday 6:00 PM to 11:00 PM.",
            }
        ),
        DESTINATION,
    )
    assert place.claim_conflicts == []
    assert place.claims[0].verification is Verification.unverified


@pytest.mark.parametrize(
    "snippet",
    [
        pytest.param("Kura in Kyoto is great, we went at 7pm.", id="mentions-a-time"),
        pytest.param("Kura in Kyoto closed on Sunday.", id="a-different-day"),
        pytest.param("Kura in Kyoto hours are unclear, ask the staff.", id="vague-about-hours"),
        pytest.param("Kura closes at 8pm on Monday in Kyoto.", id="only-one-end-of-an-interval"),
    ],
)
def test_secondary_text_without_a_contradiction_stays_unverified(snippet: str) -> None:
    """Verify mentioning hours is not the same as contradicting them."""

    place = _place()
    _apply_web(
        place,
        _rows(
            {
                "title": "Kura thread",
                "link": "https://www.reddit.com/r/kyoto/comments/1",
                "snippet": snippet,
            }
        ),
        DESTINATION,
    )
    assert place.claim_conflicts == []
    assert place.claims[0].verification is Verification.unverified
    assert place.claims[0].kind is ClaimKind.community


def test_community_text_still_feeds_constraint_assessment() -> None:
    """Verify a review-derived signal is usable without being a verified fact."""

    place = _place()
    _apply_web(
        place,
        _rows(
            {
                "title": "Kura thread",
                "link": "https://www.reddit.com/r/kyoto/comments/1",
                "snippet": "Kura in Kyoto has a quiet room at the back.",
            }
        ),
        DESTINATION,
    )
    stop = _plan(place, ["quiet"]).stops[0]
    quiet = next(item for item in stop.constraints if item.constraint == "quiet")
    assert quiet.status == "met"
    assert quiet.evidence
    community = [item for item in quiet.evidence if item.source is EvidenceSource.community]
    assert community, "the citing evidence must stay community, not become official"
    assert community[0].url is not None
    assert community[0].verification is Verification.unverified


def test_the_stop_separates_the_three_source_kinds() -> None:
    """Verify the response distinguishes official, Maps, and community claims."""

    place = _place()
    _apply_web(
        place,
        _rows(
            {
                "title": "Kura hours",
                "link": "https://kura.example/hours",
                "snippet": "Kura in Kyoto opens at 6pm.",
            },
            {
                "title": "Kura thread",
                "link": "https://www.reddit.com/r/kyoto/comments/1",
                "snippet": "Kura in Kyoto is busy on Fridays.",
            },
        ),
        DESTINATION,
    )
    stop = _plan(place).stops[0]
    kinds = {item.source for item in stop.evidence}
    assert EvidenceSource.maps in kinds
    assert EvidenceSource.official in kinds
    assert EvidenceSource.community in kinds
    for item in stop.evidence:
        assert (
            item.matched_by is not MatchMethod.none_found or item.source is EvidenceSource.community
        )
        assert item.retrieved_at is not None


def test_reviews_are_not_requested_without_an_explicit_constraint() -> None:
    """Verify a plain evening spends no billed request on reviews."""

    from happen_api.planning.discovery import _reviews_if_needed

    provider = _CountingProvider()
    constraints = EveningConstraints()
    status = _reviews_if_needed(
        [_place()],
        0,
        _place(),
        provider,  # type: ignore[arg-type]
        billed_limit=8,
        local_date=MONDAY,
        arrival=ARRIVAL,
        constraints=constraints,
        preferences=[],
    )
    assert status is None
    assert provider.calls == []


def test_reviews_are_not_requested_for_a_wording_a_review_cannot_check() -> None:
    """Verify an unsupported preference does not buy a review request."""

    from happen_api.planning.discovery import _reviews_if_needed

    provider = _CountingProvider()
    status = _reviews_if_needed(
        [_place()],
        0,
        _place(),
        provider,  # type: ignore[arg-type]
        billed_limit=8,
        local_date=MONDAY,
        arrival=ARRIVAL,
        constraints=EveningConstraints(preferences=["vaguepleasing"]),
        preferences=["vaguepleasing"],
    )
    assert status is None
    assert provider.calls == []


def test_reviews_are_requested_when_a_constraint_still_needs_evidence() -> None:
    """Verify a checkable, unverified constraint earns the review request."""

    from happen_api.planning.discovery import _reviews_if_needed

    provider = _CountingProvider()
    _reviews_if_needed(
        [_place()],
        0,
        _place(),
        provider,  # type: ignore[arg-type]
        billed_limit=8,
        local_date=MONDAY,
        arrival=ARRIVAL,
        constraints=EveningConstraints(preferences=["quiet"]),
        preferences=["quiet"],
    )
    assert any(call.startswith("reviews") for call in provider.calls)


def test_no_reviewer_identity_phone_or_long_text_is_exposed() -> None:
    """Verify the stored claim keeps a short excerpt and no personal detail."""

    place = _place()
    _apply_web(
        place,
        _rows(
            {
                "title": "Kura thread",
                "link": "https://www.reddit.com/r/kyoto/comments/1",
                "snippet": "Kura in Kyoto is quiet. " + ("Long tail. " * 60),
            }
        ),
        DESTINATION,
    )
    claim = place.claims[0]
    assert len(claim.text) <= 300
    dumped = place.model_dump_json()
    assert "+81" not in dumped
    assert "reviewer" not in dumped.casefold()


class _CountingProvider:
    """Counts review requests. It opens no connection."""

    def __init__(self) -> None:
        self.credits_charged = 0
        self.calls: list[str] = []

    def place_reviews(self, **_kwargs: object):
        self.calls.append("reviews")
        self.credits_charged += 1

        class _Snapshot:
            payload: ClassVar[dict[str, list[object]]] = {"reviews": []}

        return _Snapshot()
