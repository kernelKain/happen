"""Provider documents become three place records, or an explicit insufficiency."""

from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from happen_api.providers.serpapi.normalizer import select_candidates

_VISIT = date(2026, 10, 3)
_CAPTURED = datetime(2026, 10, 3, 12, tzinfo=ZoneInfo("Asia/Kolkata"))
_PHONE = "+91 99999 00000"
_REVIEWER = "Ada Reviewer"


def _place(place_id: str, title: str, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "title": title,
        "place_id": place_id,
        "type": "Italian restaurant",
        "phone": _PHONE,
    }
    row.update(extra)
    return row


def _hours() -> list[dict[str, str]]:
    return [{"saturday": "6 pm - 11 pm"}]


def _busy() -> dict[str, object]:
    return {
        "graph_results": {
            "Saturday": [
                {"time": "6 PM", "busyness_score": 40},
                {"time": "6:30 PM", "busyness_score": 50},
                {"time": "7 PM", "busyness_score": 140},
                {"time": "8 PM", "busyness_score": 22},
            ]
        },
        "live": {"busyness_score": 5},
    }


def _review(text: str, **extra: object) -> dict[str, object]:
    review: dict[str, object] = {
        "username": _REVIEWER,
        "snippet": text,
        "iso_date": "2026-09-01",
        "link": "https://maps.google.com/reviews/example",
    }
    review.update(extra)
    return review


def _search(*rows: dict[str, object]) -> dict[str, object]:
    return {"local_results": list(rows)}


def _select(
    search: dict[str, object],
    place_payloads: list[dict[str, object]] | None = None,
    review_payloads: list[dict[str, object]] | None = None,
):
    return select_candidates(
        search,
        place_payloads,
        review_payloads,
        visit_date=_VISIT,
        captured_at=_CAPTURED,
    )


def test_completeness_outranks_search_order_and_drops_private_fields() -> None:
    """Verify a later complete restaurant is chosen ahead of earlier sparse ones."""

    complete = _place(
        "ChIJdelta004",
        "Delta Dining",
        hours=_hours(),
        popular_times=_busy(),
        user_reviews=[_review("Quiet tables around 7 pm.")],
    )
    search = _search(
        _place("ChIJalpha001", "Alpha Atrium"),
        _place("ChIJbravo0002", "Bravo Bistro"),
        _place("ChIJcharlie03", "Charlie Cafe"),
        complete,
    )
    first = _select(search)
    second = _select(search)

    assert first.reason_codes == ["three_candidates"]
    assert [place.name for place in first.places] == [
        "Delta Dining",
        "Alpha Atrium",
        "Bravo Bistro",
    ]
    assert first == second
    rendered = json.dumps(first.model_dump(mode="json"))
    assert _PHONE not in rendered
    assert _REVIEWER not in rendered
    delta = first.places[0]
    assert delta.opening_intervals[0].opens_at.hour == 18
    assert [
        (item.hour_start.hour, item.relative_popularity) for item in delta.busyness_observations
    ] == [
        (18, 40),
        (20, 22),
    ]
    assert delta.review_excerpts[0].published_at == date(2026, 9, 1)
    assert delta.review_excerpts[0].text == "Quiet tables around 7 pm."
    assert "missing_busyness" in first.places[1].warnings
    assert first.places[1].busyness_observations == []
    assert first.places[1].opening_intervals == []
    assert first.places[1].category_tags == ["restaurants"]
    assert first.places[1].source_url.startswith(
        "https://www.google.com/maps/search/?api=1&query_place_id="
    )


def test_closed_visit_day_is_not_replaced_with_invented_hours() -> None:
    """Verify a closed restaurant is rejected and missing hours are not filled in."""

    search = _search(
        _place("ChIJalpha001", "Alpha Atrium", hours=[{"saturday": "Closed"}]),
        _place("ChIJbravo0002", "Bravo Bistro"),
        _place("ChIJcharlie03", "Charlie Cafe"),
    )
    selection = _select(search)

    assert selection.places == []
    assert selection.reason_codes == ["insufficient_candidates", "hours_closed"]


def test_place_details_supply_hours_reviews_and_limit_the_pool() -> None:
    """Verify fetched details enrich only the matching shortlist."""

    alpha = "ChIJalpha001"
    bravo = "ChIJbravo0002"
    charlie = "ChIJcharlie03"
    delta = "ChIJdelta004"
    search = _search(
        _place(alpha, "Alpha Atrium"),
        _place(bravo, "Bravo Bistro"),
        _place(charlie, "Charlie Cafe"),
        _place(delta, "Delta Dining", hours=_hours()),
    )
    reviews = [
        _review(" ".join(["word"] * 120)),
        _review("Relative date.", iso_date="2 weeks ago"),
        _review("Kannada note.", language="kn"),
        _review("Third note."),
        _review("Fourth note."),
    ]
    selection = _select(
        search,
        place_payloads=[
            {"place_results": _place(alpha, "Alpha Atrium", hours=_hours(), popular_times=_busy())},
            {"place_results": _place(bravo, "Bravo Bistro")},
            {
                "place_results": _place(charlie, "Charlie Cafe"),
                "search_parameters": {"place_id": charlie},
            },
        ],
        review_payloads=[{"search_parameters": {"place_id": charlie}, "reviews": reviews}],
    )

    assert [place.provider_place_id for place in selection.places] == [alpha, charlie, bravo]
    charlie_place = selection.places[1]
    assert len(charlie_place.review_excerpts) == 3
    assert charlie_place.review_excerpts[0].truncated is True
    assert len(charlie_place.review_excerpts[0].text) == 400
    assert charlie_place.review_excerpts[1].text == "Relative date."
    assert charlie_place.review_excerpts[1].published_at is None
    assert charlie_place.review_excerpts[2].text == "Third note."
    assert selection.places[2].warnings == ["hours_missing", "missing_busyness", "missing_reviews"]
    assert delta not in {place.provider_place_id for place in selection.places}


def test_empty_unknown_and_non_restaurant_results_are_specific() -> None:
    """Verify empty, unusable, and off-category searches do not invent restaurants."""

    empty = _select(_search())
    invalid = _select({"local_results": {}})
    unknown = _select(
        _search(
            _place("ChIJalpha001", "Alpha Atrium", type=""),
            _place("ChIJbravo0002", "Bravo Bistro", type=""),
            _place("ChIJcharlie03", "Charlie Cafe", type=""),
        )
    )
    cafes = _select(
        _search(
            _place("ChIJalpha001", "Alpha Atrium", type="Cafe"),
            _place("ChIJbravo0002", "Bravo Bistro", type="Bar"),
            _place("ChIJcharlie03", "Charlie Cafe", type="Bakery"),
        )
    )

    assert empty.reason_codes == ["empty_search"]
    assert invalid.reason_codes == ["invalid_search"]
    assert unknown.reason_codes == ["insufficient_candidates", "category_unknown"]
    assert cafes.reason_codes == ["insufficient_candidates", "category_not_restaurant"]
    assert empty.places == invalid.places == unknown.places == cafes.places == []


def test_duplicate_place_does_not_fill_a_third_slot() -> None:
    """Verify the same provider id cannot be selected twice."""

    shared = _place("ChIJalpha001", "Alpha Atrium")
    selection = _select(
        _search(
            shared,
            dict(shared, title="Alpha Again"),
            _place("ChIJbravo0002", "Bravo Bistro"),
        )
    )

    assert selection.places == []
    assert "duplicate_place" in selection.reason_codes
