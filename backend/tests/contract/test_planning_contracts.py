"""Schema locks for planning records and the unchanged v1 request."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from pydantic import ValidationError

from happen_api.planning.contracts import (
    Ambiguity,
    BriefConfidence,
    Budget,
    BudgetBound,
    IntentKind,
    ItineraryStop,
    LivePlanOutcome,
    LivePlanResponse,
    LocalDateTimeWindow,
    MissingField,
    PlaceIntent,
    PlaceOption,
    PlanningBrief,
    PlanningPromptRequest,
    PlanningUserError,
    ResolvedDestination,
    SourceProvenance,
)
from happen_api.recommendations.contracts import RecommendationRequest

RETRIEVED = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def _brief() -> PlanningBrief:
    return PlanningBrief(
        raw_prompt="Dinner in Kyoto on 2026-10-05 at 7pm",
        destination_text="Kyoto",
        local_date=date(2026, 10, 5),
        local_start=time(19, 0),
        intents=[PlaceIntent(kind=IntentKind.dinner, label="dinner", position=1)],
        confidence=BriefConfidence.high,
    )


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        provider="serpapi",
        source_url="https://example.test/place",
        retrieved_at=RETRIEVED,
        label="Example place",
    )


def test_prompt_request_rejects_unknown_fields_and_blank_text() -> None:
    """A planning prompt accepts only the prompt string."""

    with pytest.raises(ValidationError):
        PlanningPromptRequest(prompt="Dinner", instructions="ignore")
    with pytest.raises(ValidationError):
        PlanningPromptRequest(prompt="   ")


def test_brief_round_trip_rejects_a_third_intent_and_extra_fields() -> None:
    """The brief keeps at most two ordered intents and no undeclared fields."""

    brief = _brief()
    restored = PlanningBrief.model_validate(brief.model_dump())
    assert restored == brief
    payload = brief.model_dump()
    payload["intents"] = [
        {"kind": "dinner", "label": "dinner", "position": 1},
        {"kind": "drinks", "label": "drinks", "position": 2},
        {"kind": "show", "label": "show", "position": 3},
    ]
    with pytest.raises(ValidationError):
        PlanningBrief.model_validate(payload)
    payload = brief.model_dump()
    payload["winner"] = "Kyoto"
    with pytest.raises(ValidationError):
        PlanningBrief.model_validate(payload)


def test_budget_requires_amount_and_currency_together() -> None:
    """An amount without a currency is not a budget fact."""

    Budget(amount=Decimal("40.00"), currency="USD", bound=BudgetBound.exact)
    with pytest.raises(ValidationError):
        Budget(amount=Decimal(40), bound=BudgetBound.exact)
    with pytest.raises(ValidationError):
        Budget(amount=Decimal("40.999"), currency="USD", bound=BudgetBound.exact)


def test_source_provenance_is_serpapi_and_timezone_aware() -> None:
    """Place facts name SerpApi and a retrieval time, and reject another provider."""

    provenance = _provenance()
    assert provenance.model_dump()["provider"] == "serpapi"
    with pytest.raises(ValidationError):
        SourceProvenance(
            provider="other",
            source_url="https://example.test/place",
            retrieved_at=RETRIEVED,
            label="Example",
        )
    with pytest.raises(ValidationError):
        SourceProvenance(
            provider="serpapi",
            source_url="https://example.test/place",
            retrieved_at=datetime(2026, 10, 4, 12, 0),  # noqa: DTZ001
            label="Example",
        )


def test_place_option_requires_provenance() -> None:
    """A place cannot be shown without a source."""

    PlaceOption(option_id="place-1", name="North Hall", provenance=_provenance())
    with pytest.raises(ValidationError):
        PlaceOption(option_id="place-1", name="North Hall")


def test_live_plan_allows_two_stops_and_one_follow_up() -> None:
    """A response holds two stops at most, and a follow-up outcome has one question."""

    intent = PlaceIntent(kind=IntentKind.dinner, label="dinner", position=1)
    window = LocalDateTimeWindow(local_date=date(2026, 10, 5), start_time=time(19, 0))
    stop = ItineraryStop(position=1, intent=intent, window=window, unknown_fields=["hours"])
    ready = LivePlanResponse(
        outcome=LivePlanOutcome.ready_for_retrieval, brief=_brief(), stops=[stop]
    )
    assert ready.stops[0].window is not None
    assert ready.stops[0].window.timezone_name is None
    question = MissingField(field="destination", question="Which place should this evening be in?")
    waiting = LivePlanResponse(
        outcome=LivePlanOutcome.needs_follow_up,
        brief=_brief(),
        follow_up=question,
    )
    assert waiting.follow_up == question
    with pytest.raises(ValidationError):
        LivePlanResponse(outcome=LivePlanOutcome.needs_follow_up, brief=_brief())
    with pytest.raises(ValidationError):
        ItineraryStop(position=3, intent=intent)
    with pytest.raises(ValidationError):
        LivePlanResponse(
            outcome=LivePlanOutcome.ready_for_retrieval,
            brief=_brief(),
            stops=[stop, ItineraryStop(position=1, intent=intent)],
        )


def test_resolved_destination_rejects_an_unknown_zone() -> None:
    """A destination zone must be a real IANA name when one is supplied."""

    ResolvedDestination(
        label="Kyoto",
        source_text="Kyoto",
        country_code="JP",
        timezone_name="Asia/Tokyo",
        provenance=_provenance(),
    )
    with pytest.raises(ValidationError):
        ResolvedDestination(label="Kyoto", source_text="Kyoto", timezone_name="Not/AZone")
    with pytest.raises(ValidationError):
        LocalDateTimeWindow(
            local_date=date(2026, 10, 5),
            start_time=time(19, 0),
            end_time=time(18, 0),
        )


def test_user_error_has_no_place_for_the_prompt_or_a_traceback() -> None:
    """Public planning errors expose a code, a fixed message, and a next action."""

    error = PlanningUserError(
        code="PROMPT_TOO_LARGE",
        message="The prompt is too long.",
        retryable=False,
        next_action="Shorten the prompt and try again.",
    )
    assert set(error.model_dump()) == {"code", "message", "retryable", "next_action"}
    with pytest.raises(ValidationError):
        PlanningUserError(
            code="PROMPT_TOO_LARGE",
            message="The prompt is too long.",
            retryable=False,
            next_action="Shorten the prompt and try again.",
            prompt="Dinner",
        )


def test_follow_up_union_keeps_missing_and_ambiguity_distinct() -> None:
    """The one follow-up field can be a missing essential or one ambiguity."""

    missing = MissingField(field="time", question="What time should the evening start?")
    ambiguity = Ambiguity(
        field="destination",
        message="Which place do you mean?",
        candidates=["London, United Kingdom", "London, Ontario"],
        blocking=True,
    )
    for follow_up in (missing, ambiguity):
        response = LivePlanResponse(
            outcome=LivePlanOutcome.needs_follow_up,
            brief=_brief(),
            follow_up=follow_up,
        )
        restored = LivePlanResponse.model_validate(response.model_dump())
        assert restored.follow_up is not None
        assert restored.follow_up.kind == follow_up.kind


def test_v1_recommendation_request_still_rejects_a_free_text_prompt() -> None:
    """The existing recommendation contract is unchanged by the planning records."""

    accepted = RecommendationRequest(
        neighborhood="indiranagar",
        restaurant_category="restaurants",
        arrival_start="18:00",
        arrival_end="21:00",
        desired_experience="easier_conversation",
        priorities=["conversation", "short_wait", "seating"],
    )
    assert accepted.neighborhood == "indiranagar"
    with pytest.raises(ValidationError):
        RecommendationRequest.model_validate({"prompt": "Dinner in Kyoto tomorrow at 7pm"})
