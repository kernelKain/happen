"""Hours, windows, temporal mapping, fit, confidence, and tie-breaking."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from happen_api.domain.models import (
    AcceptedSignal,
    ArrivalWindow,
    BusynessObservation,
    CandidateEvidence,
    ConfidenceLabel,
    DayOfWeek,
    Dimension,
    ExtractionConfidence,
    FitLabel,
    OpenStatus,
    Outcome,
    Polarity,
    RecommendationDecision,
    TemporalHint,
    WindowAssessment,
)
from happen_api.domain.scoring import (
    POSSIBLE_CONFIDENCE,
    POSSIBLE_FIT,
    STRONG_CONFIDENCE,
    STRONG_FIT,
    UNKNOWN_CONFIDENCE,
    decide,
    is_supported,
    label_confidence,
    label_fit,
)
from happen_api.domain.timing import KOLKATA, temporal_relevance, windows_from_hours

VISIT = date(2026, 10, 3)
AS_OF = datetime(2026, 10, 3, 12, 0, tzinfo=KOLKATA)
SOURCE = "https://maps.example/place"
PRIORITIES = [Dimension.conversation, Dimension.short_wait, Dimension.seating]


def test_verified_evening_hours_emit_six_windows_inside_the_request() -> None:
    """Verify a 6–11 PM opening keeps only the six requested half hours."""

    parsed, windows = windows_from_hours(
        [{"saturday": "6:00 PM–11:00 PM"}],
        candidate_id="place-a",
        visit_date=VISIT,
        arrival_start=time(18, 0),
        arrival_end=time(21, 0),
        source_url=SOURCE,
        busyness=[_busyness(19, 40)],
    )
    assert parsed.status == "verified"
    assert [item.starts_at.strftime("%H:%M") for item in windows] == [
        "18:00",
        "18:30",
        "19:00",
        "19:30",
        "20:00",
        "20:30",
    ]
    assert all(item.open_status is OpenStatus.verified_open for item in windows)
    assert windows[2].busyness_refs == ["saturday:19:00"]
    assert windows[0].busyness_refs == []
    for window in windows:
        assert time(18, 0) <= window.starts_at.timetz().replace(tzinfo=None)
        assert window.ends_at <= datetime(2026, 10, 3, 23, 0, tzinfo=KOLKATA)


def test_hours_outside_the_opening_or_request_are_excluded() -> None:
    """Verify windows cannot start before opening or end after it."""

    _parsed, early = windows_from_hours(
        [{"saturday": "7:00 PM–11:00 PM"}],
        candidate_id="place-a",
        visit_date=VISIT,
        arrival_start=time(18, 0),
        arrival_end=time(21, 0),
        source_url=SOURCE,
    )
    assert [item.starts_at.strftime("%H:%M") for item in early] == [
        "19:00",
        "19:30",
        "20:00",
        "20:30",
    ]
    _parsed, short = windows_from_hours(
        [{"saturday": "6:00 PM–7:15 PM"}],
        candidate_id="place-a",
        visit_date=VISIT,
        arrival_start=time(18, 0),
        arrival_end=time(21, 0),
        source_url=SOURCE,
    )
    assert [item.starts_at.strftime("%H:%M") for item in short] == ["18:00", "18:30"]


def test_split_shift_and_overnight_hours_keep_only_open_minutes() -> None:
    """Verify split shifts and overnight closes do not invent open time."""

    _parsed, split = windows_from_hours(
        [{"saturday": "12:00 PM–3:00 PM, 7:00 PM–11:00 PM"}],
        candidate_id="place-a",
        visit_date=VISIT,
        arrival_start=time(18, 0),
        arrival_end=time(21, 0),
        source_url=SOURCE,
    )
    assert [item.starts_at.strftime("%H:%M") for item in split] == [
        "19:00",
        "19:30",
        "20:00",
        "20:30",
    ]
    parsed, overnight = windows_from_hours(
        [{"saturday": "6:00 PM–1:00 AM"}],
        candidate_id="place-a",
        visit_date=VISIT,
        arrival_start=time(23, 0),
        arrival_end=time(1, 0),
        source_url=SOURCE,
    )
    assert parsed.status == "verified"
    assert [item.starts_at.strftime("%H:%M") for item in overnight] == [
        "23:00",
        "23:30",
        "00:00",
        "00:30",
    ]
    assert overnight[-1].ends_at == datetime(2026, 10, 4, 1, 0, tzinfo=KOLKATA)


@pytest.mark.parametrize(
    ("hours", "status", "reason"),
    [
        ("Closed", "closed", "hours_closed"),
        ("Varies", "uncertain", "hours_unparseable"),
    ],
)
def test_closed_or_unparseable_hours_create_no_windows(
    hours: str,
    status: str,
    reason: str,
) -> None:
    """Verify closed and unreadable hours never become verified windows."""

    parsed, windows = windows_from_hours(
        [{"saturday": hours}],
        candidate_id="place-a",
        visit_date=VISIT,
        arrival_start=time(18, 0),
        arrival_end=time(21, 0),
        source_url=SOURCE,
    )
    assert parsed.status == status
    assert parsed.reason_codes == [reason]
    assert windows == []


def test_contradictory_or_missing_hours_stay_uncertain() -> None:
    """Verify conflicting listings and a missing visit day produce no windows."""

    contradictory, contradictory_windows = windows_from_hours(
        [
            {"saturday": "6:00 PM–11:00 PM"},
            {"day": "Saturday", "hours": "5:00 PM–10:00 PM"},
        ],
        candidate_id="place-a",
        visit_date=VISIT,
        arrival_start=time(18, 0),
        arrival_end=time(21, 0),
        source_url=SOURCE,
    )
    assert contradictory.status == "uncertain"
    assert contradictory.reason_codes == ["hours_contradictory"]
    assert contradictory_windows == []
    missing, missing_windows = windows_from_hours(
        [{"friday": "6:00 PM–11:00 PM"}],
        candidate_id="place-a",
        visit_date=VISIT,
        arrival_start=time(18, 0),
        arrival_end=time(21, 0),
        source_url=SOURCE,
    )
    assert missing.status == "uncertain"
    assert missing.reason_codes == ["hours_missing"]
    assert missing_windows == []


def test_open_24_hours_covers_the_requested_evening() -> None:
    """Verify an explicit all-day listing can fill the requested range."""

    parsed, windows = windows_from_hours(
        [{"saturday": "Open 24 hours"}],
        candidate_id="place-a",
        visit_date=VISIT,
        arrival_start=time(18, 0),
        arrival_end=time(21, 0),
        source_url=SOURCE,
    )
    assert parsed.status == "verified"
    assert len(windows) == 6


def test_arrival_bounds_must_be_half_hour_and_one_to_four_hours() -> None:
    """Verify the generator rejects a range the policy cannot score."""

    with pytest.raises(ValueError, match="30-minute"):
        windows_from_hours(
            [{"saturday": "Open 24 hours"}],
            candidate_id="place-a",
            visit_date=VISIT,
            arrival_start=time(18, 10),
            arrival_end=time(21, 0),
            source_url=SOURCE,
        )


def test_temporal_multipliers_follow_the_locked_bands() -> None:
    """Verify evening, weekday, and exact-time hints map onto one window."""

    start = datetime(2026, 10, 3, 19, 0, tzinfo=KOLKATA)
    end = start + timedelta(minutes=30)
    assert temporal_relevance(
        TemporalHint.mid_evening, None, starts_at=start, ends_at=end
    ) == Decimal(1)
    assert temporal_relevance(
        TemporalHint.early_evening, None, starts_at=start, ends_at=end
    ) == Decimal(0)
    early = datetime(2026, 10, 3, 18, 30, tzinfo=KOLKATA)
    assert temporal_relevance(
        TemporalHint.early_evening,
        None,
        starts_at=early,
        ends_at=early + timedelta(minutes=30),
    ) == Decimal(1)
    assert temporal_relevance(TemporalHint.weekend, None, starts_at=start, ends_at=end) == Decimal(
        "0.75"
    )
    assert temporal_relevance(TemporalHint.weekday, None, starts_at=start, ends_at=end) == Decimal(
        0
    )
    assert temporal_relevance(TemporalHint.general, None, starts_at=start, ends_at=end) == Decimal(
        "0.50"
    )
    assert temporal_relevance(TemporalHint.unknown, None, starts_at=start, ends_at=end) == Decimal(
        "0.35"
    )
    assert temporal_relevance(
        TemporalHint.specific_time, "7:15 PM", starts_at=start, ends_at=end
    ) == Decimal(1)
    assert temporal_relevance(
        TemporalHint.specific_time, "7:45 PM", starts_at=start, ends_at=end
    ) == Decimal(0)
    assert temporal_relevance(
        TemporalHint.specific_time, "later", starts_at=start, ends_at=end
    ) == Decimal(0)


def test_complete_evidence_is_strong_and_missing_data_is_unknown() -> None:
    """Verify full evidence can be strong and absent evidence stays unknown."""

    complete = decide(
        [
            _candidate(
                "alpha", "Alpha", signals=_perfect_signals("alpha"), busyness=[_busyness(19, 0)]
            )
        ],
        PRIORITIES,
        as_of=AS_OF,
    )
    chosen = complete.candidate_assessments[0]
    assert chosen.fit_score == Decimal("1.0000")
    assert chosen.confidence_score == Decimal("1.0000")
    assert chosen.fit_label is FitLabel.strong
    assert chosen.confidence_label is ConfidenceLabel.high
    assert chosen.eligible is True
    assert chosen.dimension_scores[Dimension.short_wait] == Decimal("1.0000")

    empty = decide([_candidate("alpha", "Alpha")], PRIORITIES, as_of=AS_OF)
    unknown = empty.candidate_assessments[0]
    assert unknown.fit_score == Decimal("0.0000")
    assert unknown.confidence_score == Decimal("0.0000")
    assert unknown.fit_label is FitLabel.unknown
    assert unknown.confidence_label is ConfidenceLabel.insufficient
    assert unknown.eligible is False
    assert "no_accepted_evidence" in unknown.reason_codes


def test_missing_dimensions_and_sources_keep_their_ordinary_weight() -> None:
    """Verify missing evidence adds zero instead of rescaling the remainder."""

    conversation_only = decide(
        [_candidate("alpha", "Alpha", signals=[_signal("alpha", Dimension.conversation, "conv")])],
        PRIORITIES,
        as_of=AS_OF,
    ).candidate_assessments[0]
    assert conversation_only.dimension_scores[Dimension.conversation] == Decimal("1.0000")
    assert conversation_only.dimension_scores[Dimension.short_wait] == Decimal("0.0000")
    assert conversation_only.dimension_scores[Dimension.seating] == Decimal("0.0000")
    assert conversation_only.fit_score == Decimal("0.5000")
    assert conversation_only.confidence_score == Decimal("0.8250")
    assert conversation_only.fit_label is FitLabel.possible

    review_only = decide(
        [_candidate("alpha", "Alpha", signals=[_signal("alpha", Dimension.short_wait, "wait")])],
        PRIORITIES,
        as_of=AS_OF,
    ).candidate_assessments[0]
    assert review_only.dimension_scores[Dimension.short_wait] == Decimal("0.4000")

    busyness_only = decide(
        [_candidate("alpha", "Alpha", busyness=[_busyness(19, 0)])],
        PRIORITIES,
        as_of=AS_OF,
    ).candidate_assessments[0]
    assert busyness_only.dimension_scores[Dimension.short_wait] == Decimal("0.6000")

    crowded = decide(
        [_candidate("alpha", "Alpha", busyness=[_busyness(19, 100)])],
        [Dimension.short_wait, Dimension.conversation, Dimension.seating],
        as_of=AS_OF,
    ).candidate_assessments[0]
    assert crowded.dimension_scores[Dimension.short_wait] == Decimal("-0.6000")
    assert crowded.fit_score == Decimal("-0.3000")
    assert crowded.fit_label is FitLabel.weak
    assert crowded.eligible is False


def test_non_matching_time_does_not_count_as_favorable_evidence() -> None:
    """Verify a weekday-only signal does not support a Saturday window."""

    decision = decide(
        [
            _candidate(
                "alpha",
                "Alpha",
                signals=[
                    _signal(
                        "alpha",
                        Dimension.conversation,
                        "weekday",
                        temporal_hint=TemporalHint.weekday,
                    )
                ],
            )
        ],
        PRIORITIES,
        as_of=AS_OF,
    )
    assessment = decision.candidate_assessments[0]
    assert assessment.fit_label is FitLabel.unknown
    assert assessment.eligible is False
    assert assessment.evidence_refs == []


def test_two_supported_candidates_select_a_distinct_fallback() -> None:
    """Verify a complete comparison returns one primary and a different fallback."""

    decision = decide(
        [
            _candidate(
                "beta", "Beta", signals=_perfect_signals("beta"), busyness=[_busyness(19, 0)]
            ),
            _candidate(
                "alpha", "Alpha", signals=_perfect_signals("alpha"), busyness=[_busyness(19, 0)]
            ),
            _candidate(
                "gamma", "Gamma", signals=_perfect_signals("gamma"), busyness=[_busyness(19, 0)]
            ),
        ],
        PRIORITIES,
        as_of=AS_OF,
    )
    assert decision.outcome is Outcome.recommendation
    assert decision.primary_window_id == "alpha:2026-10-03T19:00"
    assert decision.fallback_window_id == "beta:2026-10-03T19:00"
    assert decision.missing_dimensions == []
    assert decision.policy_version == "v1"


def test_fewer_than_two_supported_candidates_has_no_winner() -> None:
    """Verify one supported restaurant cannot manufacture a recommendation."""

    decision = decide(
        [
            _candidate(
                "alpha", "Alpha", signals=_perfect_signals("alpha"), busyness=[_busyness(19, 0)]
            ),
            _candidate("beta", "Beta"),
        ],
        PRIORITIES,
        as_of=AS_OF,
    )
    assert decision.outcome is Outcome.insufficient_evidence
    assert decision.primary_window_id is None
    assert decision.fallback_window_id is None
    assert "fewer_than_two_supported_candidates" in decision.reason_codes


def test_incomplete_third_candidate_stays_a_partial_result() -> None:
    """Verify a winner can exist while an unsupported row stays unknown."""

    decision = decide(
        [
            _candidate(
                "alpha", "Alpha", signals=_perfect_signals("alpha"), busyness=[_busyness(19, 0)]
            ),
            _candidate(
                "beta", "Beta", signals=_perfect_signals("beta"), busyness=[_busyness(19, 0)]
            ),
            _candidate("gamma", "Gamma"),
        ],
        PRIORITIES,
        as_of=AS_OF,
    )
    assert decision.outcome is Outcome.partial_evidence
    assert decision.primary_window_id == "alpha:2026-10-03T19:00"
    assert decision.fallback_window_id == "beta:2026-10-03T19:00"
    assert Dimension.conversation in decision.missing_dimensions
    assert "unsupported_candidate:gamma" in decision.reason_codes


def test_tie_break_uses_fit_then_confidence_then_priority_then_time_then_name() -> None:
    """Verify the locked selection order down to the restaurant name."""

    later_better = decide(
        [
            _candidate(
                "beta",
                "Beta",
                windows=[_window("beta", 19, 0)],
                signals=[_signal("beta", Dimension.conversation, "conv")],
            ),
            _candidate(
                "alpha",
                "Alpha",
                windows=[_window("alpha", 19, 30)],
                signals=_perfect_signals("alpha"),
                busyness=[_busyness(19, 0)],
            ),
        ],
        PRIORITIES,
        as_of=AS_OF,
    )
    assert later_better.primary_window_id == "alpha:2026-10-03T19:30"

    higher_confidence = decide(
        [
            _candidate("zeta", "Zeta", signals=_agreement_signals("zeta", contradictory=False)),
            _candidate("alpha", "Alpha", signals=_agreement_signals("alpha", contradictory=True)),
        ],
        PRIORITIES,
        as_of=AS_OF,
    )
    assert higher_confidence.primary_window_id == "zeta:2026-10-03T19:00"
    zeta = _assessment(higher_confidence, "zeta:2026-10-03T19:00")
    alpha = _assessment(higher_confidence, "alpha:2026-10-03T19:00")
    assert zeta.fit_score == alpha.fit_score
    assert zeta.confidence_score > alpha.confidence_score

    higher_priority = decide(
        [
            _priority_candidate("zeta", "Zeta", favor_first=True),
            _priority_candidate("alpha", "Alpha", favor_first=False),
        ],
        PRIORITIES,
        as_of=AS_OF,
    )
    assert higher_priority.primary_window_id == "zeta:2026-10-03T19:00"
    first = _assessment(higher_priority, "zeta:2026-10-03T19:00")
    second = _assessment(higher_priority, "alpha:2026-10-03T19:00")
    assert first.fit_score == second.fit_score == Decimal("0.5000")
    assert first.confidence_score == second.confidence_score
    assert (
        first.dimension_scores[Dimension.conversation]
        > second.dimension_scores[Dimension.conversation]
    )

    earlier = decide(
        [
            _candidate(
                "alpha",
                "Alpha",
                windows=[_window("alpha", 19, 30)],
                signals=_perfect_signals("alpha"),
                busyness=[_busyness(19, 0)],
            ),
            _candidate(
                "beta",
                "Beta",
                windows=[_window("beta", 19, 0)],
                signals=_perfect_signals("beta"),
                busyness=[_busyness(19, 0)],
            ),
        ],
        PRIORITIES,
        as_of=AS_OF,
    )
    assert earlier.primary_window_id == "beta:2026-10-03T19:00"
    assert earlier.fallback_window_id == "alpha:2026-10-03T19:30"

    by_name = decide(
        [
            _candidate(
                "beta", "Beta", signals=_perfect_signals("beta"), busyness=[_busyness(19, 0)]
            ),
            _candidate(
                "alpha", "Alpha", signals=_perfect_signals("alpha"), busyness=[_busyness(19, 0)]
            ),
        ],
        PRIORITIES,
        as_of=AS_OF,
    )
    assert by_name.primary_window_id == "alpha:2026-10-03T19:00"
    assert by_name.fallback_window_id == "beta:2026-10-03T19:00"


def test_the_same_evidence_is_byte_stable_across_repeated_runs() -> None:
    """Verify scoring ignores input order and stays identical across runs."""

    forward = _candidate(
        "alpha",
        "Alpha",
        signals=_perfect_signals("alpha"),
        busyness=[_busyness(19, 20), _busyness(19, 0)],
    )
    backward = forward.model_copy(
        update={
            "signals": list(reversed(forward.signals)),
            "busyness": list(reversed(forward.busyness)),
        }
    )
    dumps = [
        decide([candidate], PRIORITIES, as_of=AS_OF).model_dump(mode="json")
        for candidate in (forward, backward, forward, forward, forward)
    ]
    assert dumps[0] == dumps[1] == dumps[2] == dumps[3] == dumps[4]


@pytest.mark.parametrize(
    ("fit", "confidence", "has_evidence", "expected"),
    [
        (STRONG_FIT, STRONG_CONFIDENCE, True, FitLabel.strong),
        (STRONG_FIT, STRONG_CONFIDENCE - Decimal("0.0001"), True, FitLabel.possible),
        (POSSIBLE_FIT, POSSIBLE_CONFIDENCE, True, FitLabel.possible),
        (POSSIBLE_FIT - Decimal("0.0001"), Decimal("0.9000"), True, FitLabel.weak),
        (Decimal("0.9000"), UNKNOWN_CONFIDENCE - Decimal("0.0001"), True, FitLabel.unknown),
        (Decimal("0.9000"), Decimal("0.9000"), False, FitLabel.unknown),
    ],
)
def test_fit_labels_use_the_locked_boundaries(
    fit: Decimal,
    confidence: Decimal,
    has_evidence: bool,
    expected: FitLabel,
) -> None:
    """Verify strong, possible, weak, and unknown cutoffs stay exact."""

    assert label_fit(fit, confidence, has_evidence=has_evidence) is expected


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (Decimal("0.7500"), ConfidenceLabel.high),
        (Decimal("0.7499"), ConfidenceLabel.medium),
        (Decimal("0.5000"), ConfidenceLabel.medium),
        (Decimal("0.4999"), ConfidenceLabel.low),
        (Decimal("0.2500"), ConfidenceLabel.low),
        (Decimal("0.2499"), ConfidenceLabel.insufficient),
    ],
)
def test_confidence_labels_use_the_locked_boundaries(
    confidence: Decimal,
    expected: ConfidenceLabel,
) -> None:
    """Verify confidence bands do not move at the published cutoffs."""

    assert label_confidence(confidence) is expected


def test_support_requires_both_thresholds_and_temporal_evidence() -> None:
    """Verify a high score without evidence or either threshold is unsupported."""

    assert is_supported(POSSIBLE_FIT, POSSIBLE_CONFIDENCE, has_temporal_evidence=True)
    assert not is_supported(
        POSSIBLE_FIT - Decimal("0.0001"),
        POSSIBLE_CONFIDENCE,
        has_temporal_evidence=True,
    )
    assert not is_supported(
        POSSIBLE_FIT,
        POSSIBLE_CONFIDENCE - Decimal("0.0001"),
        has_temporal_evidence=True,
    )
    assert not is_supported(Decimal(1), Decimal(1), has_temporal_evidence=False)


def _candidate(
    candidate_id: str,
    name: str,
    *,
    signals: list[AcceptedSignal] | None = None,
    busyness: list[BusynessObservation] | None = None,
    windows: list[ArrivalWindow] | None = None,
) -> CandidateEvidence:
    return CandidateEvidence(
        candidate_id=candidate_id,
        name=name,
        windows=windows or [_window(candidate_id, 19, 0)],
        signals=signals or [],
        busyness=busyness or [],
    )


def _window(candidate_id: str, hour: int, minute: int) -> ArrivalWindow:
    start = datetime(2026, 10, 3, hour, minute, tzinfo=KOLKATA)
    return ArrivalWindow(
        window_id=f"{candidate_id}:{start.strftime('%Y-%m-%dT%H:%M')}",
        candidate_id=candidate_id,
        starts_at=start,
        ends_at=start + timedelta(minutes=30),
        open_status=OpenStatus.verified_open,
        busyness_refs=[],
        evidence_refs=[],
    )


def _signal(
    candidate_id: str,
    dimension: Dimension,
    signal_id: str,
    *,
    polarity: Polarity = Polarity.positive,
    temporal_hint: TemporalHint = TemporalHint.mid_evening,
) -> AcceptedSignal:
    return AcceptedSignal(
        signal_id=signal_id,
        candidate_id=candidate_id,
        dimension=dimension,
        polarity=polarity,
        temporal_hint=temporal_hint,
        confidence=ExtractionConfidence.high,
        published_at=VISIT,
    )


def _perfect_signals(candidate_id: str) -> list[AcceptedSignal]:
    return [
        _signal(candidate_id, Dimension.conversation, f"{candidate_id}-conversation"),
        _signal(candidate_id, Dimension.short_wait, f"{candidate_id}-wait"),
        _signal(candidate_id, Dimension.seating, f"{candidate_id}-seating"),
    ]


def _agreement_signals(candidate_id: str, *, contradictory: bool) -> list[AcceptedSignal]:
    if contradictory:
        conversation = [
            _signal(
                candidate_id,
                Dimension.conversation,
                f"{candidate_id}-positive",
                polarity=Polarity.positive,
            ),
            _signal(
                candidate_id,
                Dimension.conversation,
                f"{candidate_id}-negative",
                polarity=Polarity.negative,
            ),
        ]
    else:
        conversation = [
            _signal(
                candidate_id,
                Dimension.conversation,
                f"{candidate_id}-mixed",
                polarity=Polarity.mixed,
            )
        ]
    return [
        *conversation,
        _signal(candidate_id, Dimension.short_wait, f"{candidate_id}-wait"),
        _signal(candidate_id, Dimension.seating, f"{candidate_id}-seating"),
    ]


def _priority_candidate(candidate_id: str, name: str, *, favor_first: bool) -> CandidateEvidence:
    if favor_first:
        conversation = Polarity.positive
        wait = Polarity.mixed
        seating = Polarity.mixed
        popularity = 50
    else:
        conversation = Polarity.mixed
        wait = Polarity.positive
        seating = Polarity.positive
        popularity = 0
    return _candidate(
        candidate_id,
        name,
        signals=[
            _signal(
                candidate_id,
                Dimension.conversation,
                f"{candidate_id}-conversation",
                polarity=conversation,
            ),
            _signal(candidate_id, Dimension.short_wait, f"{candidate_id}-wait", polarity=wait),
            _signal(candidate_id, Dimension.seating, f"{candidate_id}-seating", polarity=seating),
        ],
        busyness=[_busyness(19, popularity)],
    )


def _busyness(hour: int, popularity: int) -> BusynessObservation:
    return BusynessObservation(
        day_of_week=DayOfWeek.saturday,
        hour_start=time(hour, 0),
        relative_popularity=popularity,
        source_url=SOURCE,
        captured_at=AS_OF,
    )


def _assessment(decision: RecommendationDecision, window_id: str) -> WindowAssessment:
    return next(item for item in decision.candidate_assessments if item.window_id == window_id)
