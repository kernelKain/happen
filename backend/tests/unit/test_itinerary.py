"""Deterministic evening assembly. These tests do not call a provider or a model."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from happen_api.api.plans import PlanRequest
from happen_api.planning.clock import FixedClock
from happen_api.planning.constraints import EveningConstraints
from happen_api.planning.contracts import Budget, BudgetBound, BudgetTier, IntentKind, PlaceIntent
from happen_api.planning.discovery import DiscoveredPlace, EvidenceConflict
from happen_api.planning.interpret import interpret
from happen_api.planning.itinerary import (
    ConstraintAssessment,
    EvidenceSource,
    PlanTransition,
    assemble_itinerary,
    hours_status,
    local_arrival,
    propose_revision,
    verified_fit,
)

RETRIEVED = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
CLOCK = FixedClock(datetime(2026, 10, 4, 15, 0, tzinfo=UTC))
MONDAY = date(2026, 10, 5)
ARRIVAL = time(19, 0)


def _intent(kind: IntentKind = IntentKind.dinner, position: int = 1) -> PlaceIntent:
    return PlaceIntent(kind=kind, label=kind.value, position=position)


def _place(**updates: object) -> DiscoveredPlace:
    values: dict[str, object] = {
        "intent": IntentKind.dinner,
        "place_id": "place-alpha",
        "name": "Alpha",
        "latitude": 35.0,
        "longitude": 135.7,
        "maps_link": "https://maps.example/alpha",
        "hours": ["monday: 17:00-22:00"],
        "unknown_fields": ["price", "popular_times"],
    }
    values.update(updates)
    return DiscoveredPlace.model_validate(values)


def _plan(
    places: list[DiscoveredPlace],
    intents: list[PlaceIntent] | None = None,
    constraints: EveningConstraints | None = None,
):
    return assemble_itinerary(
        places,
        intents or [_intent()],
        local_date=MONDAY,
        local_start=ARRIVAL,
        retrieved_at=RETRIEVED,
        constraints=constraints,
    )


def test_timezone_changes_which_weekday_the_hours_use() -> None:
    """One UTC instant is Monday morning in Tokyo and Sunday evening in New York."""

    moment = datetime(2026, 10, 4, 22, 0, tzinfo=UTC)
    tokyo_date, tokyo_time = local_arrival(moment, "Asia/Tokyo")
    york_date, york_time = local_arrival(moment, "America/New_York")
    assert (tokyo_date, tokyo_time) == (date(2026, 10, 5), time(7, 0))
    assert (york_date, york_time) == (date(2026, 10, 4), time(18, 0))
    for zone in ("Asia/Kolkata", "Europe/London", "America/New_York", "Asia/Tokyo"):
        local = moment.astimezone(ZoneInfo(zone))
        assert local_arrival(moment, zone) == (local.date(), local.timetz().replace(tzinfo=None))
    place = _place(hours=["monday: 07:00-09:00"])
    tokyo = assemble_itinerary(
        [place],
        [_intent()],
        local_date=tokyo_date,
        local_start=tokyo_time,
        retrieved_at=moment,
    )
    york = assemble_itinerary(
        [place],
        [_intent()],
        local_date=york_date,
        local_start=york_time,
        retrieved_at=moment,
    )
    assert tokyo.outcome == "planned"
    assert tokyo.stops[0].hours_status == "open"
    assert york.outcome == "insufficient_evidence"
    assert york.stops == []


def test_overnight_hours_cover_the_next_morning_only() -> None:
    """Friday 18:00-02:00 is open late Friday and early Saturday, and closed after that."""

    place = _place(hours=["friday: 18:00-02:00"])
    friday = date(2026, 10, 2)
    saturday = date(2026, 10, 3)
    assert hours_status(place, friday, time(19, 0)) == "open"
    assert hours_status(place, friday, time(1, 0)) == "closed"
    assert hours_status(place, saturday, time(1, 0)) == "open"
    assert hours_status(place, saturday, time(15, 0)) == "closed"


def test_closed_places_are_excluded_and_unknown_hours_stay_with_a_warning() -> None:
    """A listed closed day is out. Missing hours stay, with lower confidence."""

    closed = _place(name="Closed Room", place_id="closed", hours=["sunday: 17:00-22:00"])
    unknown = _place(
        name="Unlisted Room",
        place_id="unknown",
        hours=[],
        unknown_fields=["hours", "price", "popular_times"],
    )
    plan = _plan([closed, unknown])
    assert [item.name for item in plan.stops] == ["Unlisted Room"]
    stop = plan.stops[0]
    assert stop.hours_status == "unknown"
    assert stop.confidence == "low"
    assert stop.warnings == ["Opening hours were not listed, so this stop is less certain."]
    assert "price" in stop.unknown_fields
    assert "popular_times" in stop.unknown_fields


def test_price_and_busyness_gaps_do_not_raise_a_place() -> None:
    """A missing price or popular-times value is not treated as a reason to win."""

    priced = _place(name="Bravo", place_id="bravo", price="$$$$", unknown_fields=["popular_times"])
    quiet = _place(name="Alpha", unknown_fields=["price", "popular_times"])
    busy = _place(
        name="Alpha",
        place_id="busy",
        popular_times_known=True,
        unknown_fields=["price"],
    )
    idle = _place(name="Bravo", place_id="idle", unknown_fields=["price", "popular_times"])
    assert _plan([priced, quiet]).stops[0].name == "Alpha"
    assert _plan([idle, busy]).stops[0].name == "Alpha"
    listed = _plan([priced], [_intent()]).stops[0]
    assert listed.price == "$$$$"
    assert listed.busyness == "unknown"
    assert _plan([busy], [_intent()]).stops[0].busyness == "listed"


def test_equal_evidence_uses_provider_rank_before_the_name() -> None:
    """When verified fit matches, the earlier provider result wins over the name."""

    later_name = _place(
        name="Alpha Room",
        place_id="alpha",
        provider_rank=1,
        website="https://alpha.example",
    )
    earlier = _place(
        name="Zeta Room",
        place_id="zeta",
        provider_rank=0,
        website="https://zeta.example",
    )
    assert _plan([later_name, earlier]).stops[0].name == "Zeta Room"


def test_official_source_breaks_a_name_tie_and_equal_places_use_the_name() -> None:
    """An official site outranks a maps-only place. Equal ranks then use the name."""

    maps_only = _place(name="Alpha")
    official = _place(
        name="Bravo",
        place_id="bravo",
        website="https://bravo.example",
        maps_link="https://maps.example/bravo",
    )
    later = _place(name="Bravo", place_id="bravo-2", maps_link="https://maps.example/bravo")
    earlier = _place(name="Alpha", place_id="alpha-2")
    assert _plan([maps_only, official]).stops[0].name == "Bravo"
    assert _plan([later, earlier]).stops[0].name == "Alpha"


def test_two_stops_link_directions_without_inventing_a_duration() -> None:
    """The transition is unverified and has no travel time."""

    dinner = _place()
    drinks = _place(
        intent=IntentKind.drinks,
        name="Night Bar",
        place_id="bar",
        latitude=35.1,
        longitude=135.8,
        maps_link="https://maps.example/bar",
    )
    plan = _plan(
        [dinner, drinks],
        [_intent(), _intent(IntentKind.drinks, 2)],
    )
    assert [item.position for item in plan.stops] == [1, 2]
    assert plan.transition is not None
    assert plan.transition.status == "unverified"
    dumped = plan.transition.model_dump()
    assert "duration" not in dumped
    directions = unquote(str(plan.transition.directions_url))
    assert "35.0,135.7" in directions
    assert "35.1,135.8" in directions
    with pytest.raises(ValidationError):
        PlanTransition.model_validate({**dumped, "duration": 12})


def test_evidence_keeps_source_types_and_the_retrieval_time() -> None:
    """Official, Maps, and community statements stay distinct and dated."""

    place = _place(
        website="https://alpha.example",
        community_notes=["Neighbors mention a quiet room."],
        conflicts=[
            EvidenceConflict(official="monday: 17:00-22:00", community="Closed on Mondays.")
        ],
    )
    stop = _plan([place]).stops[0]
    sources = {item.source for item in stop.evidence}
    assert sources == {EvidenceSource.maps, EvidenceSource.official, EvidenceSource.community}
    assert {item.retrieved_at for item in stop.evidence} == {RETRIEVED}
    assert "disagree" in stop.warnings[0]
    dumped = stop.model_dump()
    assert "score" not in dumped
    assert "weight" not in dumped


def test_no_places_and_all_closed_places_stay_explicit() -> None:
    """An empty search and a closed-only search do not invent a stop."""

    empty = _plan([])
    closed = _plan([_place(hours=["sunday: 10:00-12:00"])])
    assert empty.outcome == "no_results"
    assert closed.outcome == "insufficient_evidence"
    assert empty.stops == []
    assert closed.stops == []


def test_a_place_without_an_identifier_is_not_eligible() -> None:
    """Selection needs a place id or a data id from the provider."""

    nameless = _place(place_id=None, data_id=None, name="Unidentified")
    assert _plan([nameless]).outcome == "insufficient_evidence"


def test_refinement_proposes_a_diff_and_leaves_the_current_brief() -> None:
    """A revision is validated and is not applied to the brief that was sent."""

    current = interpret("Dinner in Kyoto on 2026-10-05 at 7pm for two, quiet", CLOCK).brief
    before = current.model_dump()
    proposal = propose_revision(
        current,
        "Drinks in Tokyo on 2026-10-06 at 8pm",
        CLOCK,
    )
    assert proposal.applied is False
    assert proposal.current.model_dump() == before
    assert proposal.proposed.destination_text == "Tokyo"
    assert proposal.proposed.local_date == date(2026, 10, 6)
    assert proposal.proposed.local_start == time(20, 0)
    assert [item.kind for item in proposal.proposed.intents] == [IntentKind.drinks]
    assert proposal.proposed.preferences == ["quiet"]
    assert proposal.follow_up is None
    changed = {item.field: (item.before, item.after) for item in proposal.diff.changed}
    assert changed["destination"] == ("Kyoto", "Tokyo")
    assert changed["date"] == ("2026-10-05", "2026-10-06")
    assert changed["time"] == ("19:00", "20:00")
    assert changed["intent"] == ("dinner", "drinks")
    assert proposal.diff.added == []
    assert "not changed" in proposal.message


def test_a_partial_revision_keeps_unstated_facts() -> None:
    """A time-only revision does not drop the destination or the date."""

    current = interpret("Dinner in Kyoto on 2026-10-05 at 7pm", CLOCK).brief
    proposal = propose_revision(current, "Start at 8pm", CLOCK)
    assert proposal.applied is False
    assert proposal.proposed.destination_text == "Kyoto"
    assert proposal.proposed.local_date == date(2026, 10, 5)
    assert proposal.proposed.local_start == time(20, 0)
    assert [item.field for item in proposal.diff.changed] == ["time"]


def test_assembly_does_not_ask_a_model_to_choose() -> None:
    """The selector names hours and sources. It does not load or ask a model."""

    source = (
        Path(__file__).resolve().parents[2] / "src" / "happen_api" / "planning" / "itinerary.py"
    )
    text = source.read_text(encoding="utf-8").casefold()
    assert "gemma" not in text
    assert "llama" not in text
    assert "excerpt" not in text
    closed = _place(name="Model Choice", hours=["sunday: 17:00-22:00"], highlights=["winner"])
    open_place = _place(name="Listed Room", place_id="listed")
    assert _plan([closed, open_place]).stops[0].name == "Listed Room"


def test_verified_quiet_outranks_a_loud_or_unknown_place() -> None:
    """A source-backed quiet place beats a louder place and a place with no statement."""

    quiet = _place(name="Quiet Room", place_id="quiet", highlights=["A quiet room"])
    loud = _place(name="Loud Room", place_id="loud", highlights=["A loud room"])
    unknown = _place(name="Plain Room", place_id="plain", highlights=["Counter seating"])
    plan = _plan([loud, unknown, quiet], constraints=EveningConstraints(preferences=["quiet"]))
    assert plan.stops[0].name == "Quiet Room"
    finding = plan.stops[0].constraints[0]
    assert finding.constraint == "quiet"
    assert finding.status == "met"
    assert finding.evidence[0].text == "A quiet room"


def test_unknown_quiet_does_not_add_a_positive_fit() -> None:
    """Missing quiet evidence adds the same fit as not asking for quiet."""

    plain = _place(highlights=["Counter seating"])
    loud = _place(name="Loud Room", place_id="loud", highlights=["A loud room"])
    asked = EveningConstraints(preferences=["quiet"])
    assert verified_fit(plain, "open", asked) == verified_fit(plain, "open")
    assert verified_fit(loud, "open", asked) == verified_fit(plain, "open")


def test_unmet_accessibility_cannot_be_presented_as_a_fit() -> None:
    """A contradiction is not selected, and unknown access is not called verified."""

    stairs = _place(name="Stairs", place_id="stairs", highlights=["Stairs only"])
    plain = _place(name="Plain Room", place_id="plain", highlights=["Counter seating"])
    access = EveningConstraints(accessibility_needs=["wheelchair access"])
    mixed = _plan([stairs, plain], constraints=access)
    assert mixed.stops[0].name == "Plain Room"
    assert mixed.outcome == "insufficient_evidence"
    unknown = mixed.stops[0].constraints[0]
    assert unknown.constraint == "wheelchair access"
    assert unknown.status == "unknown"
    assert unknown.evidence == []
    blocked = _plan([stairs], constraints=access)
    assert blocked.stops == []
    assert blocked.outcome == "insufficient_evidence"
    assert any("wheelchair access" in note for note in blocked.warnings)
    ramp = _place(name="Ramp", place_id="ramp", highlights=["Wheelchair accessible entrance"])
    verified = _plan([stairs, ramp], constraints=access)
    assert verified.stops[0].name == "Ramp"
    assert verified.outcome == "planned"
    assert verified.stops[0].constraints[0].status == "met"
    assert verified.stops[0].constraints[0].evidence


def test_dietary_contradiction_is_not_a_verified_fit() -> None:
    """Vegetarian follows the same evidence rule as accessibility."""

    meat = _place(name="Meat", place_id="meat", highlights=["Meat only"])
    plain = _place(name="Plain Room", place_id="plain", highlights=["Counter seating"])
    asked = EveningConstraints(preferences=["vegetarian"])
    plan = _plan([meat, plain], constraints=asked)
    assert plan.stops[0].name == "Plain Room"
    assert plan.outcome == "insufficient_evidence"
    assert plan.stops[0].constraints[0].status == "unknown"


def test_constraints_can_change_the_choice_without_new_provider_evidence() -> None:
    """The same listings select a different place when the requested constraint changes."""

    quiet = _place(name="Quiet Room", place_id="quiet", highlights=["A quiet room"], price="$$")
    veg = _place(name="Veg Room", place_id="veg", highlights=["Vegetarian menu"], price="$$$")
    same = [quiet, veg]
    assert _plan(same, constraints=EveningConstraints(preferences=["quiet"])).stops[0].name == (
        "Quiet Room"
    )
    assert _plan(same, constraints=EveningConstraints(preferences=["vegetarian"])).stops[
        0
    ].name == ("Veg Room")


def test_budget_compares_only_compatible_evidence() -> None:
    """A symbol is a tier, and an amount needs the same currency."""

    symbols = _place(name="Symbols", place_id="symbols", price="$$")
    amount_only = EveningConstraints(
        budget=Budget(amount=Decimal(40), currency="USD", bound=BudgetBound.at_most)
    )
    symbol_plan = _plan([symbols], constraints=amount_only)
    assert symbol_plan.stops[0].constraints[0].status == "unknown"
    assert verified_fit(symbols, "open", amount_only) == verified_fit(symbols, "open")
    cheap = _place(name="Cheap", place_id="cheap", price="$")
    low = EveningConstraints(budget=Budget(tier=BudgetTier.low))
    assert _plan([symbols, cheap], constraints=low).stops[0].name == "Cheap"
    assert _plan([symbols], constraints=low).stops[0].constraints[0].status == "unmet"
    yen = _place(name="Yen", place_id="yen", price="JPY 4000")
    dollars = _place(name="Dollars", place_id="dollars", price="USD 40")
    yen_budget = EveningConstraints(
        budget=Budget(amount=Decimal(5000), currency="JPY", bound=BudgetBound.at_most)
    )
    assert _plan([dollars, yen], constraints=yen_budget).stops[0].name == "Yen"
    assert _plan([yen], constraints=yen_budget).stops[0].constraints[0].status == "met"
    assert _plan([dollars], constraints=yen_budget).stops[0].constraints[0].status == "unknown"


def test_party_size_is_shown_and_unknown_without_capacity_evidence() -> None:
    """Party size stays on the plan. A missing capacity is not treated as a fit."""

    plain = _place(highlights=["Counter seating"])
    asked = EveningConstraints(party_size=6)
    plan = _plan([plain], constraints=asked)
    assert plan.party_size == 6
    assert plan.stops[0].constraints[0].constraint == "party size"
    assert plan.stops[0].constraints[0].status == "unknown"
    small = _place(name="Small", place_id="small", highlights=["The room seats 4"])
    large = _place(name="Large", place_id="large", highlights=["The room seats 8"])
    assert _plan([small], constraints=asked).stops[0].constraints[0].status == "unmet"
    assert _plan([small, large], constraints=asked).stops[0].name == "Large"


def test_unsupported_constraint_stays_unknown() -> None:
    """A preference without a deterministic signal is not counted as support."""

    place = _place(highlights=["A quiet room"])
    asked = EveningConstraints(preferences=["dog friendly"])
    plan = _plan([place], constraints=asked)
    finding = plan.stops[0].constraints[0]
    assert finding.constraint == "dog friendly"
    assert finding.status == "unknown"
    assert finding.evidence == []
    assert verified_fit(place, "open", asked) == verified_fit(place, "open")
    unused = ConstraintAssessment(constraint="budget", status="not_applicable")
    assert unused.evidence == []


def test_open_hours_outrank_a_verified_preference() -> None:
    """An open place beats a verified preference whose hours are unknown."""

    open_place = _place(name="Open Room", place_id="open", highlights=["Counter seating"])
    quiet = _place(
        name="Quiet Room",
        place_id="quiet",
        hours=[],
        highlights=["A quiet room"],
        unknown_fields=["hours", "price", "popular_times"],
    )
    plan = _plan([quiet, open_place], constraints=EveningConstraints(preferences=["quiet"]))
    assert plan.stops[0].name == "Open Room"


def test_scoring_components_do_not_expose_a_number() -> None:
    """The customer payload names each check and does not include an internal total."""

    plan = _plan(
        [_place(highlights=["A quiet room"])],
        constraints=EveningConstraints(preferences=["quiet"]),
    )
    payload = plan.model_dump(mode="json")
    assert "score" not in payload
    component = payload["stops"][0]["components"][0]
    assert set(component) == {"name", "result", "detail"}
    assert "score" not in plan.model_dump_json()
    assert "weight" not in plan.model_dump_json()


def test_plan_request_keeps_party_budget_access_and_preferences() -> None:
    """The v2 plan body accepts the same constraint set the page sends."""

    body = PlanRequest.model_validate(
        {
            "destination": {
                "label": "Kyoto",
                "source_text": "Kyoto",
                "timezone_name": "Asia/Tokyo",
            },
            "intents": [{"kind": "dinner", "label": "dinner", "position": 1}],
            "local_date": "2026-10-05",
            "local_start": "19:00:00",
            "party_size": 4,
            "budget": {
                "amount": "40",
                "currency": "USD",
                "tier": "low",
                "bound": "at_most",
            },
            "preferences": ["quiet"],
            "accessibility_needs": ["wheelchair access"],
        }
    )
    assert body.party_size == 4
    assert body.budget is not None
    assert body.budget.amount == Decimal(40)
    assert body.budget.currency == "USD"
    assert body.preferences == ["quiet"]
    assert body.accessibility_needs == ["wheelchair access"]
