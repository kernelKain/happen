"""Provider hours normalization and the feasibility decisions that consume it.

The strings here are the shapes SerpApi actually returns, including 12-hour
text with an en dash. Feasibility reads the canonical schedule, never the
display string, and nothing is guessed when a format is not recognized.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from happen_api.domain.hours import (
    HOURS_CLOSED,
    HOURS_DAY_LABEL_UNRECOGNIZED,
    HOURS_DAY_NOT_LISTED,
    HOURS_DAY_VALUE_UNRECOGNIZED,
    HOURS_MISSING,
    HOURS_OUTSIDE_LISTED,
    HOURS_SHAPE_UNRECOGNIZED,
    ProviderHours,
    hours_reason,
    hours_state,
    normalize_hours,
    schedule_from_lines,
)
from happen_api.domain.models import DayOfWeek
from happen_api.planning.contracts import IntentKind, PlaceIntent
from happen_api.planning.discovery import DiscoveredPlace, _place_from_record
from happen_api.planning.itinerary import (
    assemble_itinerary,
    hours_decision_reason,
    hours_status,
    place_schedule,
)

MONDAY = date(2026, 10, 5)
SATURDAY = date(2026, 10, 3)
RETRIEVED = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
ARRIVAL = time(19, 0)


def _intervals(hours: ProviderHours, day: DayOfWeek) -> list[tuple[str, str]]:
    schedule = hours.days.get(day)
    if schedule is None:
        return []
    return [
        (item.opens_at.strftime("%H:%M"), item.closes_at.strftime("%H:%M"))
        for item in schedule.intervals
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param({"monday": "6:00 PM–11:00 PM"}, [("18:00", "23:00")], id="twelve-hour"),
        pytest.param({"monday": "18:00-23:00"}, [("18:00", "23:00")], id="twenty-four-hour"),
        pytest.param({"monday": "6:00pm-11:00pm"}, [("18:00", "23:00")], id="no-spaces"),
        pytest.param({"monday": "6 PM – 11 PM"}, [("18:00", "23:00")], id="bare-hours"),
        pytest.param({"monday": "6:00 PM to 11:00 PM"}, [("18:00", "23:00")], id="to"),
        pytest.param({"monday": "6:00 PM-11:00 PM"}, [("18:00", "23:00")], id="hyphen"),
        pytest.param({"monday": "6:00 PM–11:00 PM"}, [("18:00", "23:00")], id="en-dash"),
        pytest.param({"monday": "6:00 PM—11:00 PM"}, [("18:00", "23:00")], id="em-dash"),
        pytest.param({"monday": "6:00 PM−11:00 PM"}, [("18:00", "23:00")], id="minus-sign"),
        pytest.param({"monday": "18:00–23:00"}, [("18:00", "23:00")], id="twenty-four-en-dash"),
        pytest.param({"MONDAY": "6:00 PM–11:00 PM"}, [("18:00", "23:00")], id="upper-day"),
        pytest.param({"Mon": "6:00 PM–11:00 PM"}, [("18:00", "23:00")], id="short-day"),
        pytest.param({"monday": "Open 24 hours"}, [("00:00", "00:00")], id="open-24-hours"),
        pytest.param(
            {"monday": "12:00 PM–3:00 PM, 7:00 PM–11:00 PM"},
            [("12:00", "15:00"), ("19:00", "23:00")],
            id="two-intervals",
        ),
        pytest.param(
            {"monday": "9:00 AM – 11:00 AM, 12:00 PM – 2:00 PM, 6:00 PM–11:00 PM"},
            [("09:00", "11:00"), ("12:00", "14:00"), ("18:00", "23:00")],
            id="three-intervals",
        ),
        pytest.param({"monday": "6:00 PM–1:00 AM"}, [("18:00", "01:00")], id="overnight"),
        pytest.param({"monday": "18:00-02:00"}, [("18:00", "02:00")], id="overnight-24h"),
        pytest.param({"monday": "11:00 PM–2:00 AM"}, [("23:00", "02:00")], id="late-overnight"),
    ],
)
def test_supported_formats_normalize_to_the_same_canonical_intervals(
    raw: dict[str, str], expected: list[tuple[str, str]]
) -> None:
    """Verify each provider format becomes the canonical interval it describes."""

    hours = normalize_hours(raw)
    assert hours.days[DayOfWeek.monday].status == "open"
    assert _intervals(hours, DayOfWeek.monday) == expected
    assert hours.unrecognized == []
    covered = _first_covered_hour(expected)
    assert hours_state(hours, local_date=MONDAY, arrival=covered) == "open"
    assert hours_reason(hours, local_date=MONDAY, arrival=covered) == "hours_covers_arrival"


def _first_covered_hour(expected: list[tuple[str, str]]) -> time:
    """Return a clock inside the first expected interval."""

    if not expected:
        return ARRIVAL
    return time.fromisoformat(expected[0][0])


def test_a_closed_listing_normalizes_to_a_closed_day() -> None:
    """Verify an explicitly closed day is closed and names that reason."""

    for text in ("Closed", "closed.", "CLOSED"):
        hours = normalize_hours({"monday": text})
        assert hours.days[DayOfWeek.monday].status == "closed"
        assert hours.days[DayOfWeek.monday].intervals == []
        assert hours.days[DayOfWeek.monday].original_text == text
        assert hours_state(hours, local_date=MONDAY, arrival=ARRIVAL) == "closed"
        assert hours_reason(hours, local_date=MONDAY, arrival=ARRIVAL) == HOURS_CLOSED


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param([{"monday": "6:00 PM–11:00 PM"}], id="list-of-single-key"),
        pytest.param(
            [{"day": "Monday", "hours": "6:00 PM–11:00 PM"}],
            id="list-of-day-and-hours",
        ),
        pytest.param(
            [{"day": "Monday", "hours": "6:00 PM–11:00 PM", "extra": "ignored"}],
            id="list-with-extra-keys",
        ),
        pytest.param(["Monday: 6:00 PM–11:00 PM"], id="list-of-combined-strings"),
        pytest.param(["monday: 6:00 PM–11:00 PM"], id="list-of-lowercase-strings"),
        pytest.param({"hours": [{"monday": "6:00 PM–11:00 PM"}]}, id="hours-key-list"),
    ],
)
def test_observed_provider_shapes_reach_the_same_schedule(raw: object) -> None:
    """Verify each observed SerpApi shape normalizes identically."""

    hours = normalize_hours(raw)
    assert _intervals(hours, DayOfWeek.monday) == [("18:00", "23:00")]
    assert hours_state(hours, local_date=MONDAY, arrival=ARRIVAL) == "open"


def test_the_original_provider_text_survives_normalization() -> None:
    """Verify display text is preserved beside the canonical schedule."""

    raw = {"monday": "6:00 PM–11:00 PM", "tuesday": "Closed"}
    hours = normalize_hours(raw)
    assert hours.days[DayOfWeek.monday].original_text == "6:00 PM–11:00 PM"
    assert hours.days[DayOfWeek.tuesday].original_text == "Closed"
    assert hours.days[DayOfWeek.tuesday].status == "closed"
    lines = schedule_from_lines(["monday: 6:00 PM–11:00 PM"]).days[DayOfWeek.monday]
    assert lines.original_text == "6:00 PM–11:00 PM"


def test_a_closed_day_is_closed_and_a_missing_day_is_not_invented() -> None:
    """Verify closure is read from the schedule, and gaps are not filled in."""

    raw = {
        "monday": "6:00 PM–11:00 PM",
        "tuesday": "6:00 PM–11:00 PM",
        "wednesday": "6:00 PM–11:00 PM",
        "thursday": "6:00 PM–11:00 PM",
        "friday": "6:00 PM–11:00 PM",
        "saturday": "6:00 PM–11:00 PM",
        "sunday": "Closed",
    }
    hours = normalize_hours(raw)
    assert hours_state(hours, local_date=date(2026, 10, 11), arrival=ARRIVAL) == "closed"
    assert hours_reason(hours, local_date=date(2026, 10, 11), arrival=ARRIVAL) == HOURS_CLOSED
    assert hours_state(hours, local_date=MONDAY, arrival=time(23, 30)) == "closed"
    assert hours_reason(hours, local_date=MONDAY, arrival=time(23, 30)) == HOURS_OUTSIDE_LISTED
    partial = normalize_hours({"monday": "6:00 PM–11:00 PM"})
    assert hours_state(partial, local_date=date(2026, 10, 7), arrival=ARRIVAL) == "closed"
    assert hours_reason(partial, local_date=date(2026, 10, 7), arrival=ARRIVAL) == (
        HOURS_DAY_NOT_LISTED
    )


def test_a_gap_inside_a_split_shift_is_closed() -> None:
    """Verify the afternoon break between two intervals is not treated as open."""

    hours = normalize_hours({"monday": "12:00 PM–3:00 PM, 7:00 PM–11:00 PM"})
    assert hours_state(hours, local_date=MONDAY, arrival=time(12, 30)) == "open"
    assert hours_state(hours, local_date=MONDAY, arrival=time(15, 0)) == "closed"
    assert hours_state(hours, local_date=MONDAY, arrival=time(18, 59)) == "closed"
    assert hours_state(hours, local_date=MONDAY, arrival=time(19, 0)) == "open"


def test_open_24_hours_covers_the_whole_day() -> None:
    """Verify an all-day listing is open at every clock and closes at midnight."""

    hours = normalize_hours({"monday": "Open 24 hours"})
    for clock in (time(0, 0), time(3, 15), time(12, 0), time(23, 59)):
        assert hours_state(hours, local_date=MONDAY, arrival=clock) == "open"
    assert hours_state(hours, local_date=MONDAY, arrival=time(0, 0)) == "open"


def test_overnight_coverage_is_checked_against_the_previous_day() -> None:
    """Verify an interval that opens on one day covers the small hours of the next."""

    hours = normalize_hours({"friday": "6:00 PM–1:00 AM"})
    assert hours_state(hours, local_date=date(2026, 10, 2), arrival=time(23, 0)) == "open"
    assert hours_state(hours, local_date=date(2026, 10, 2), arrival=time(1, 0)) == "closed"
    assert hours_state(hours, local_date=date(2026, 10, 3), arrival=time(0, 59)) == "open"
    assert hours_state(hours, local_date=date(2026, 10, 3), arrival=time(15, 0)) == "closed"


def test_overnight_coverage_holds_across_a_dst_change() -> None:
    """Verify the previous-day lookup does not depend on a fixed UTC offset.

    The local date and clock time are what the provider text describes, so an
    overnight interval covers the same local times on either side of a DST
    boundary. Only the instant behind those times changes.
    """

    hours = normalize_hours({"saturday": "6:00 PM–1:00 AM"})
    # 2026-11-01 is the United States DST end date, so Saturday spans the change.
    for saturday in (date(2026, 10, 31), date(2026, 11, 7)):
        assert hours_state(hours, local_date=saturday, arrival=time(23, 30)) == "open"
        assert hours_state(hours, local_date=saturday + timedelta(days=1), arrival=time(0, 30)) == (
            "open"
        )
        assert hours_state(hours, local_date=saturday + timedelta(days=1), arrival=time(3, 0)) == (
            "closed"
        )
        assert hours_state(hours, local_date=saturday, arrival=time(18, 0)) == "open"
    # 2026-03-08 is the United States DST start date.
    spring = normalize_hours({"saturday": "11:00 PM–2:00 AM"})
    assert hours_state(spring, local_date=date(2026, 3, 7), arrival=time(23, 30)) == "open"
    assert hours_state(spring, local_date=date(2026, 3, 8), arrival=time(1, 30)) == "open"
    assert hours_state(spring, local_date=date(2026, 3, 8), arrival=time(9, 0)) == "closed"


def test_overnight_across_a_month_boundary_uses_the_previous_day() -> None:
    """Verify a Saturday interval covers the small hours of the first of the month."""

    hours = normalize_hours({"saturday": "6:00 PM–2:00 AM"})
    assert hours_state(hours, local_date=date(2026, 10, 31), arrival=time(23, 0)) == "open"
    assert hours_state(hours, local_date=date(2026, 11, 1), arrival=time(1, 0)) == "open"
    assert hours_state(hours, local_date=date(2026, 11, 1), arrival=time(2, 0)) == "closed"


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        pytest.param({"monday": "如下图"}, HOURS_DAY_VALUE_UNRECOGNIZED, id="localized-value"),
        pytest.param({"monday": "Horario variable"}, HOURS_DAY_VALUE_UNRECOGNIZED, id="spanish"),
        pytest.param(
            {"monday": "月〜金 18:00〜23:00"}, HOURS_DAY_VALUE_UNRECOGNIZED, id="japanese"
        ),
        pytest.param(
            {"lundi": "18:00-23:00"}, HOURS_DAY_LABEL_UNRECOGNIZED, id="localized-day-label"
        ),
        pytest.param(
            {"montag": "18:00-23:00"}, HOURS_DAY_LABEL_UNRECOGNIZED, id="german-day-label"
        ),
        pytest.param({"monday": "18:00〜23:00"}, HOURS_DAY_VALUE_UNRECOGNIZED, id="wave-dash"),
        pytest.param({"monday": "25:00-26:00"}, HOURS_DAY_VALUE_UNRECOGNIZED, id="bad-hours"),
        pytest.param(
            {"monday": "6:00 PM–13:00 PM"}, HOURS_DAY_VALUE_UNRECOGNIZED, id="bad-meridiem"
        ),
        pytest.param({"monday": "ab:cdef–gh:ijkl"}, HOURS_DAY_VALUE_UNRECOGNIZED, id="letters"),
        pytest.param(None, HOURS_MISSING, id="absent"),
        pytest.param("", HOURS_MISSING, id="empty-string"),
        pytest.param(42, HOURS_SHAPE_UNRECOGNIZED, id="wrong-shape"),
    ],
)
def test_unrecognized_formats_stay_unknown_with_a_structured_reason(
    raw: object, reason: str
) -> None:
    """Verify an unreadable listing is never translated into an interval."""

    hours = normalize_hours(raw)
    assert all(
        schedule.status == "unknown" and not schedule.intervals for schedule in hours.days.values()
    )
    assert hours_reason(hours, local_date=MONDAY, arrival=ARRIVAL) == reason
    assert hours_state(hours, local_date=MONDAY, arrival=ARRIVAL) == "unknown"
    assert hours_state(hours, local_date=SATURDAY, arrival=ARRIVAL) == "unknown"


def test_unrecognized_localized_text_never_claims_an_opening() -> None:
    """Verify a localized weekday label is kept as text and never mapped to a day."""

    hours = normalize_hours({"lundi": "18:00-23:00"})
    assert hours.unrecognized == ["18:00-23:00"]
    assert hours.reason_codes == [HOURS_DAY_LABEL_UNRECOGNIZED]
    assert hours.days == {}


def test_a_localized_day_does_not_close_a_known_open_day() -> None:
    """Verify mixed readable and localized text keeps the readable days usable."""

    hours = normalize_hours({"monday": "6:00 PM–11:00 PM", "mardi": "18:00-23:00"})
    assert hours_state(hours, local_date=MONDAY, arrival=ARRIVAL) == "open"
    assert hours_state(hours, local_date=date(2026, 10, 6), arrival=ARRIVAL) == "unknown"


def test_contradictory_listings_for_one_day_stay_unknown() -> None:
    """Verify two different listings for one weekday are not silently merged."""

    hours = normalize_hours([{"monday": "6:00 PM–11:00 PM"}, {"monday": "7:00 PM–10:00 PM"}])
    assert hours.days[DayOfWeek.monday].status == "unknown"
    assert hours_state(hours, local_date=MONDAY, arrival=ARRIVAL) == "unknown"
    assert hours_reason(hours, local_date=MONDAY, arrival=ARRIVAL) == "hours_contradictory"


def test_agreeing_duplicate_listings_for_one_day_are_not_a_contradiction() -> None:
    """Verify the same listing twice is still one readable schedule."""

    hours = normalize_hours([{"monday": "6:00 PM–11:00 PM"}, {"monday": "6:00 PM–11:00 PM"}])
    assert hours.days[DayOfWeek.monday].status == "open"
    assert hours_state(hours, local_date=MONDAY, arrival=ARRIVAL) == "open"


def _place(**updates: object) -> DiscoveredPlace:
    values: dict[str, object] = {
        "intent": IntentKind.dinner,
        "place_id": "place-alpha",
        "name": "Alpha",
        "latitude": 35.0,
        "longitude": 135.7,
        "maps_link": "https://maps.example/alpha",
    }
    values.update(updates)
    return DiscoveredPlace.model_validate(values)


def _intent(kind: IntentKind = IntentKind.dinner, position: int = 1) -> PlaceIntent:
    return PlaceIntent(kind=kind, label=kind.value, position=position)


def test_a_place_normalizes_its_own_hours_when_no_schedule_is_attached() -> None:
    """Verify a place built outside the provider boundary still gets a schedule."""

    place = _place(hours=["monday: 6:00 PM–11:00 PM"])
    assert place.hours_schedule is None
    schedule = place_schedule(place)
    assert schedule is not None
    assert _intervals(schedule, DayOfWeek.monday) == [("18:00", "23:00")]
    assert hours_status(place, MONDAY, ARRIVAL) == "open"
    assert hours_decision_reason(place, MONDAY, ARRIVAL) == "hours_covers_arrival"


def test_a_place_without_hours_stays_unknown() -> None:
    """Verify absent hours are unknown rather than closed."""

    place = _place(hours=[])
    assert place_schedule(place) is None
    assert hours_status(place, MONDAY, ARRIVAL) == "unknown"
    assert hours_decision_reason(place, MONDAY, ARRIVAL) == HOURS_MISSING


def test_a_definitely_closed_place_is_excluded_and_an_unknown_one_is_kept() -> None:
    """Verify only a definite closure removes a place from the evening."""

    closed = _place(name="Closed Room", place_id="closed", hours=["monday: Closed"])
    localized = _place(
        name="Local Room",
        place_id="local",
        hours=["monday:如下图"],
        unknown_fields=["hours", "price"],
    )
    open_room = _place(name="Open Room", place_id="open", hours=["monday: 6:00 PM–11:00 PM"])
    plan = assemble_itinerary(
        [closed, localized, open_room],
        [_intent()],
        local_date=MONDAY,
        local_start=ARRIVAL,
        retrieved_at=RETRIEVED,
    )
    names = [stop.name for stop in plan.stops]
    assert "Closed Room" not in names
    assert "Open Room" in names
    assert hours_status(closed, MONDAY, ARRIVAL) == "closed"
    assert hours_status(localized, MONDAY, ARRIVAL) == "unknown"


def test_the_stop_names_the_reason_the_hours_could_not_be_normalized() -> None:
    """Verify an unreadable listing reports a reason instead of blaming absence."""

    record = {
        "title": "Local Room",
        "place_id": "ChIJlocal",
        "address": "1 Example Street",
        "gps_coordinates": {"latitude": 35.0, "longitude": 135.7},
        "link": "https://maps.google.com/?cid=1",
        "operating_hours": {"monday": "如下图"},
    }
    place = _place_from_record(record, IntentKind.dinner)
    assert place is not None
    assert place.hours == ["monday: 如下图"]
    assert hours_status(place, MONDAY, ARRIVAL) == "unknown"
    stop = assemble_itinerary(
        [place],
        [_intent()],
        local_date=MONDAY,
        local_start=ARRIVAL,
        retrieved_at=RETRIEVED,
    ).stops[0]
    assert stop.hours_status == "unknown"
    assert "hours_day_value_unrecognized" in stop.components[0].detail
    assert any(item.source == "maps" and item.text == "monday: 如下图" for item in stop.evidence)


def test_provider_shapes_keep_their_original_text_as_maps_evidence() -> None:
    """Verify each observed provider shape still shows the text the provider sent."""

    shapes = [
        ({"operating_hours": {"monday": "6:00 PM–11:00 PM"}}, "monday: 6:00 PM–11:00 PM"),
        ({"hours": [{"monday": "6:00 PM–11:00 PM"}]}, "monday: 6:00 PM–11:00 PM"),
        (
            {"hours": [{"day": "Monday", "hours": "6:00 PM–11:00 PM"}]},
            "Monday: 6:00 PM–11:00 PM",
        ),
        ({"hours": ["Monday: 6:00 PM–11:00 PM"]}, "Monday: 6:00 PM–11:00 PM"),
    ]
    for shape, displayed in shapes:
        record = {
            "title": "Alpha",
            "place_id": "ChIJalpha",
            "address": "1 Example Street",
            "gps_coordinates": {"latitude": 35.0, "longitude": 135.7},
            "link": "https://maps.google.com/?cid=1",
            **shape,
        }
        place = _place_from_record(record, IntentKind.dinner)
        assert place is not None, shape
        assert place.hours == [displayed], shape
        assert place.hours_schedule is not None, shape
        assert hours_status(place, MONDAY, ARRIVAL) == "open", shape
        stop = assemble_itinerary(
            [place],
            [_intent()],
            local_date=MONDAY,
            local_start=ARRIVAL,
            retrieved_at=RETRIEVED,
        ).stops[0]
        assert stop.hours_status == "open"
        assert any(item.source == "maps" and item.text == displayed for item in stop.evidence)


def test_the_second_stop_does_not_claim_a_verified_arrival() -> None:
    """Verify only the first stop asserts a planned arrival time."""

    dinner = _place(hours=["monday: 6:00 PM–11:00 PM"])
    drinks = _place(
        intent=IntentKind.drinks,
        name="Night Bar",
        place_id="bar",
        latitude=35.1,
        longitude=135.8,
        maps_link="https://maps.example/bar",
        hours=["monday: 6:00 PM–11:00 PM"],
    )
    plan = assemble_itinerary(
        [dinner, drinks],
        [_intent(), _intent(IntentKind.drinks, 2)],
        local_date=MONDAY,
        local_start=ARRIVAL,
        retrieved_at=RETRIEVED,
    )
    first, second = plan.stops
    assert first.hours_status == "open"
    assert first.explanation == "Maps hours cover 19:00 on 2026-10-05."
    assert second.hours_status == "open"
    assert "A separate arrival was not planned for this stop." in second.explanation
    assert second.explanation != first.explanation
