"""Central Hook characterization using accepted evidence, without the model artifact."""

from __future__ import annotations

import json
from datetime import date, datetime, time

from happen_api.catalog import SCORING_POLICY_VERSION
from happen_api.config import Settings
from happen_api.domain.models import (
    BusynessObservation,
    DayOfWeek,
    Dimension,
    HoursConfidence,
    NormalizedPlace,
    OpeningInterval,
    ReviewExcerpt,
)
from happen_api.domain.timing import KOLKATA
from happen_api.fixtures.schema import FixtureRequest, LoadedFixture
from happen_api.recommendations.contracts import RecommendationRequest
from happen_api.recommendations.service import build_recommendation

VISIT = date(2026, 10, 3)
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=KOLKATA)
SOURCE = "https://example.com/happen/synthetic/hook"
TEXT = (
    "Synthetic note: conversation was easy at 7 pm, the wait was short at 7 pm, "
    "and seating stayed comfortable at 7 pm."
)
PLAIN = "Synthetic note: the room was ordinary."
DISCLAIMER = "Synthetic development evidence. Planning evidence—not live occupancy."


def test_hook_selects_one_moment_and_a_different_fallback(settings: Settings) -> None:
    """Verify three timelines, separate labels, and a stable distinct fallback."""

    first = _recommend(settings, _places())
    second = _recommend(settings, _places())

    assert len(first.candidates) == 3
    assert [item.candidate_id for item in first.candidates] == [
        "courtyard-lantern",
        "north-gallery",
        "platform-seats",
    ]
    assert all(len(item.windows) == 6 for item in first.candidates)
    assert first.outcome.value == "recommendation"
    assert first.recommendation is not None
    assert first.fallback is not None
    assert first.recommendation.candidate_id == "courtyard-lantern"
    assert first.fallback.candidate_id == "north-gallery"
    assert first.recommendation.window_id == "courtyard-lantern:2026-10-03T19:00"
    assert first.fallback.window_id == "north-gallery:2026-10-03T19:00"
    assert first.recommendation.fit_label.value == "strong"
    assert first.recommendation.confidence_label.value == "high"
    assert first.recommendation.fit_label != first.recommendation.confidence_label
    assert first.fallback.fit_label.value != "unknown"
    assert first.provenance.mode == "captured_fixture"
    assert first.provenance.model_id == settings.hf_model_repo
    assert first.provenance.scoring_policy_version == SCORING_POLICY_VERSION
    assert first.provenance.extraction_schema_version == "1"
    assert first.provenance.stale is False
    assert first.provenance.data_label == "synthetic_development"
    assert any(item.code == "synthetic_development" for item in first.warnings)
    assert DISCLAIMER in first.warnings[0].message
    quotes = [item.quoted_span for item in first.evidence]
    assert quotes
    assert all(quote in TEXT for quote in quotes)
    assert "fit_score" not in first.model_dump(mode="json")
    assert second.recommendation is not None
    assert second.fallback is not None
    assert first.recommendation.window_id == second.recommendation.window_id
    assert first.fallback.window_id == second.fallback.window_id
    assert first.outcome == second.outcome


def test_missing_third_candidate_stays_partial(settings: Settings) -> None:
    """Verify a winner can exist while an unsupported restaurant stays unknown."""

    places = _places()
    places[2] = _place(
        "platform-seats",
        "Platform Seats",
        PLAIN,
        "platform-seats-1",
        busyness=False,
    )
    result = _recommend(settings, places, plain_ids={"platform-seats-1"})

    assert result.outcome.value == "partial_evidence"
    assert result.recommendation is not None
    assert result.fallback is not None
    assert result.recommendation.candidate_id != result.fallback.candidate_id
    assert result.recommendation.candidate_id != "platform-seats"
    assert result.fallback.candidate_id != "platform-seats"
    unsupported = result.candidates[2]
    assert unsupported.windows
    assert all(window.fit_label.value == "unknown" for window in unsupported.windows)


def _recommend(
    settings: Settings,
    places: list[NormalizedPlace],
    *,
    plain_ids: set[str] | None = None,
):
    loaded = LoadedFixture(
        fixture_id="indiranagar-dinner",
        fixture_version="1.0.0",
        schema_version="1.0.0",
        data_label="synthetic_development",
        checksum="a" * 64,
        stale=False,
        captured_at=NOW,
        timezone="Asia/Kolkata",
        visit_date=VISIT,
        request=FixtureRequest(
            neighborhood="indiranagar",
            restaurant_category="restaurants",
            arrival_start="18:00",
            arrival_end="21:00",
            desired_experience="easier_conversation",
            priorities=[Dimension.conversation, Dimension.short_wait, Dimension.seating],
        ),
        places=places,
        source_urls=[SOURCE],
        safe_request_ids=["synthetic-hook"],
        attribution=(
            "Synthetic development fixture. Restaurant names are fictional "
            "and are not a SerpApi capture."
        ),
        disclaimer=DISCLAIMER,
        scoring_policy_version=SCORING_POLICY_VERSION,
        adapter_id="none",
    )
    body = RecommendationRequest(
        neighborhood="indiranagar",
        restaurant_category="restaurants",
        arrival_start="18:00",
        arrival_end="21:00",
        desired_experience="easier_conversation",
        priorities=[Dimension.conversation, Dimension.short_wait, Dimension.seating],
    )
    return build_recommendation(
        loaded,
        body,
        settings=settings,
        now=NOW,
        generate=_generate(plain_ids or set()),
        request_id="hook-test",
    )


def _places() -> list[NormalizedPlace]:
    return [
        _place("courtyard-lantern", "Courtyard Lantern", TEXT, "courtyard-1"),
        _place("north-gallery", "North Gallery Supper", TEXT, "north-1"),
        _place("platform-seats", "Platform Seats", TEXT, "platform-1"),
    ]


def _place(
    candidate_id: str,
    name: str,
    text: str,
    excerpt_id: str,
    *,
    busyness: bool = True,
) -> NormalizedPlace:
    observations = (
        [
            BusynessObservation(
                day_of_week=DayOfWeek.saturday,
                hour_start=time(19, 0),
                relative_popularity=20,
                source_url=SOURCE,
                captured_at=NOW,
            )
        ]
        if busyness
        else []
    )
    return NormalizedPlace(
        candidate_id=candidate_id,
        provider_place_id=f"synthetic:{candidate_id}",
        name=name,
        category_tags=["restaurants"],
        source_url=SOURCE,
        opening_intervals=[
            OpeningInterval(
                date=VISIT,
                opens_at=time(18, 0),
                closes_at=time(23, 0),
                source_url=SOURCE,
                confidence=HoursConfidence.verified,
            )
        ],
        busyness_observations=observations,
        review_excerpts=[
            ReviewExcerpt(
                excerpt_id=excerpt_id,
                candidate_id=candidate_id,
                text=text,
                published_at=date(2026, 9, 1),
                captured_at=NOW,
                source_url=SOURCE,
                language="en",
                truncated=False,
            )
        ],
        eligibility_reasons=["synthetic_candidate"],
        warnings=["synthetic_development"],
    )


def _generate(plain_ids: set[str]):
    def generate(prompt: str) -> str:
        excerpt_id = ""
        for line in prompt.splitlines():
            if line.startswith("excerpt_id:"):
                excerpt_id = line.split(":", 1)[1].strip()
        if excerpt_id in plain_ids:
            payload = {
                "schema_version": "1",
                "excerpt_id": excerpt_id,
                "signals": [],
                "unknown_dimensions": ["conversation", "short_wait", "seating"],
            }
            return json.dumps(payload)
        payload = {
            "schema_version": "1",
            "excerpt_id": excerpt_id,
            "signals": [
                _signal("conversation", "conversation was easy at 7 pm"),
                _signal("short_wait", "the wait was short at 7 pm"),
                _signal("seating", "seating stayed comfortable at 7 pm"),
            ],
            "unknown_dimensions": [],
        }
        return json.dumps(payload)

    return generate


def _signal(dimension: str, quote: str) -> dict[str, object]:
    return {
        "dimension": dimension,
        "polarity": "positive",
        "temporal_hint": "weekend",
        "temporal_span": None,
        "quoted_span": quote,
        "confidence": "high",
    }
