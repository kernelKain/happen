"""Deterministic evening assembly. These tests do not call a provider or a model."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from happen_api.planning.clock import FixedClock
from happen_api.planning.contracts import IntentKind, PlaceIntent
from happen_api.planning.discovery import DiscoveredPlace, EvidenceConflict
from happen_api.planning.interpret import interpret
from happen_api.planning.itinerary import (
    EvidenceSource,
    PlanTransition,
    assemble_itinerary,
    hours_status,
    local_arrival,
    propose_revision,
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


def _plan(places: list[DiscoveredPlace], intents: list[PlaceIntent] | None = None):
    return assemble_itinerary(
        places,
        intents or [_intent()],
        local_date=MONDAY,
        local_start=ARRIVAL,
        retrieved_at=RETRIEVED,
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


def test_official_source_breaks_a_name_tie_and_equal_places_use_the_name() -> None:
    """An official site outranks a maps-only place. Equal places use the name, not input order."""

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
