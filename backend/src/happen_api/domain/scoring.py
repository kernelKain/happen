"""Deterministic scoring policy v1.

Fit always divides by six priority points. A missing dimension adds zero and
does not shrink that denominator. Short-wait evidence keeps its ordinary
weight when the other short-wait source is missing: typical popularity is
0.60 and validated wait reviews are 0.40.

Confidence components are bounded from zero to one:

- weighted dimension coverage is the covered priority weight divided by six;
  short wait contributes only the fraction of its 0.60 and 0.40 sources that
  are present;
- temporal specificity is the mean temporal multiplier of applicable review
  signals, or 1 when only hour-aligned popularity applies;
- evidence quality is the mean extraction-confidence multiplier of applicable
  signals, with hour-aligned popularity counted as 1;
- evidence agreement is 0 for a dimension that has both positive and negative
  applicable signals, otherwise 1, then averaged across covered dimensions;
- freshness is the mean recency multiplier of applicable signals and popularity
  observations.

A signal whose temporal multiplier is 0 does not cover a dimension. Unknown
dates use the locked 0.50 recency multiplier. No applicable evidence yields
confidence 0 and the unknown fit label.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from happen_api.catalog import SCORING_POLICY_VERSION
from happen_api.domain.models import (
    AcceptedSignal,
    BusynessObservation,
    CandidateEvidence,
    ConfidenceLabel,
    Dimension,
    ExtractionConfidence,
    FitLabel,
    Outcome,
    Polarity,
    RecommendationDecision,
    WindowAssessment,
)
from happen_api.domain.timing import temporal_relevance

_QUANT = Decimal("0.0001")
_PRIORITY_WEIGHTS = (Decimal(3), Decimal(2), Decimal(1))
_BUSYNESS_WEIGHT = Decimal("0.60")
_REVIEW_WAIT_WEIGHT = Decimal("0.40")
_CONFIDENCE_WEIGHTS = {
    "coverage": Decimal("0.35"),
    "temporal": Decimal("0.25"),
    "quality": Decimal("0.20"),
    "agreement": Decimal("0.10"),
    "freshness": Decimal("0.10"),
}
_EXTRACTION_MULTIPLIER = {
    ExtractionConfidence.high: Decimal(1),
    ExtractionConfidence.medium: Decimal("0.75"),
    ExtractionConfidence.low: Decimal("0.50"),
}
_POLARITY_VALUE = {
    Polarity.positive: Decimal(1),
    Polarity.mixed: Decimal(0),
    Polarity.negative: Decimal(-1),
}
STRONG_FIT = Decimal("0.55")
STRONG_CONFIDENCE = Decimal("0.65")
POSSIBLE_FIT = Decimal("0.20")
POSSIBLE_CONFIDENCE = Decimal("0.40")
UNKNOWN_CONFIDENCE = Decimal("0.25")


def quantize(value: Decimal) -> Decimal:
    """Round a score to four decimal places without binary float drift."""

    return value.quantize(_QUANT, rounding=ROUND_HALF_UP)


def label_fit(fit: Decimal, confidence: Decimal, *, has_evidence: bool) -> FitLabel:
    """Apply the locked fit labels without relaxing a threshold."""

    if not has_evidence or confidence < UNKNOWN_CONFIDENCE:
        return FitLabel.unknown
    if fit >= STRONG_FIT and confidence >= STRONG_CONFIDENCE:
        return FitLabel.strong
    if fit >= POSSIBLE_FIT and confidence >= POSSIBLE_CONFIDENCE:
        return FitLabel.possible
    return FitLabel.weak


def label_confidence(confidence: Decimal) -> ConfidenceLabel:
    """Apply the locked confidence labels."""

    if confidence >= Decimal("0.75"):
        return ConfidenceLabel.high
    if confidence >= Decimal("0.50"):
        return ConfidenceLabel.medium
    if confidence >= UNKNOWN_CONFIDENCE:
        return ConfidenceLabel.low
    return ConfidenceLabel.insufficient


def is_supported(fit: Decimal, confidence: Decimal, *, has_temporal_evidence: bool) -> bool:
    """Return whether one window meets the locked support threshold."""

    return has_temporal_evidence and fit >= POSSIBLE_FIT and confidence >= POSSIBLE_CONFIDENCE


def decide(
    candidates: list[CandidateEvidence],
    priorities: list[Dimension],
    *,
    as_of: datetime,
) -> RecommendationDecision:
    """Score every feasible window and select a primary moment and fallback."""

    weights = _priority_weights(priorities)
    assessments: list[WindowAssessment] = []
    order: dict[str, tuple[str, datetime]] = {}
    for candidate in candidates:
        for window in candidate.windows:
            assessment = _assess_window(
                candidate,
                window_id=window.window_id,
                starts_at=window.starts_at,
                ends_at=window.ends_at,
                weights=weights,
                as_of=as_of,
            )
            assessments.append(assessment)
            order[window.window_id] = (_normalized_name(candidate.name), window.starts_at)

    assessments.sort(
        key=lambda item: (
            order[item.window_id][0],
            order[item.window_id][1],
            item.window_id,
        )
    )
    eligible = [item for item in assessments if item.eligible]
    eligible.sort(key=lambda item: _selection_key(item, priorities, order))
    supported_ids = {item.candidate_id for item in eligible}
    primary = eligible[0] if eligible else None
    fallback = next(
        (
            item
            for item in eligible
            if primary is not None and item.candidate_id != primary.candidate_id
        ),
        None,
    )
    missing = [
        dimension
        for dimension in Dimension
        if any(f"missing_dimension:{dimension.value}" in item.reason_codes for item in assessments)
    ]
    if len(supported_ids) < 2 or primary is None or fallback is None:
        outcome = Outcome.insufficient_evidence
        primary_id = None
        fallback_id = None
    else:
        unknown_present = any(item.fit_label is FitLabel.unknown for item in assessments)
        incomplete = len(supported_ids) < len(candidates) or unknown_present
        outcome = Outcome.partial_evidence if incomplete else Outcome.recommendation
        primary_id = primary.window_id
        fallback_id = fallback.window_id

    reasons = [f"supported_candidates:{len(supported_ids)}"]
    if outcome is Outcome.insufficient_evidence:
        reasons.append("fewer_than_two_supported_candidates")
    if primary_id is not None:
        reasons.append(f"primary:{primary_id}")
    if fallback_id is not None:
        reasons.append(f"fallback:{fallback_id}")
    for candidate_id in sorted({item.candidate_id for item in candidates} - supported_ids):
        reasons.append(f"unsupported_candidate:{candidate_id}")
    return RecommendationDecision(
        outcome=outcome,
        candidate_assessments=assessments,
        primary_window_id=primary_id,
        fallback_window_id=fallback_id,
        reason_codes=sorted(reasons),
        missing_dimensions=missing,
        policy_version=SCORING_POLICY_VERSION,
    )


def _priority_weights(priorities: list[Dimension]) -> dict[Dimension, Decimal]:
    if len(priorities) != 3 or set(priorities) != set(Dimension):
        raise ValueError("priorities must rank conversation, short_wait, and seating once each")
    return {
        dimension: weight for dimension, weight in zip(priorities, _PRIORITY_WEIGHTS, strict=True)
    }


def _assess_window(
    candidate: CandidateEvidence,
    *,
    window_id: str,
    starts_at: datetime,
    ends_at: datetime,
    weights: dict[Dimension, Decimal],
    as_of: datetime,
) -> WindowAssessment:
    signals = [
        signal for signal in candidate.signals if signal.candidate_id == candidate.candidate_id
    ]
    signals.sort(key=lambda signal: signal.signal_id)
    busyness = _busyness_for_window(candidate.busyness, starts_at, ends_at)
    contributions: dict[Dimension, list[Decimal]] = {dimension: [] for dimension in Dimension}
    applicable: dict[Dimension, int] = {dimension: 0 for dimension in Dimension}
    temporal_terms: list[Decimal] = []
    quality_terms: list[Decimal] = []
    freshness_terms: list[Decimal] = []
    evidence_refs: list[str] = []
    contradictory: set[Dimension] = set()
    for dimension in Dimension:
        polarities = _signed_polarities(signals, dimension, starts_at, ends_at)
        if Polarity.positive in polarities and Polarity.negative in polarities:
            contradictory.add(dimension)
    for signal in signals:
        relevance = temporal_relevance(
            signal.temporal_hint,
            signal.temporal_span,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        contribution = (
            _POLARITY_VALUE[signal.polarity]
            * relevance
            * _EXTRACTION_MULTIPLIER[signal.confidence]
            * _recency(signal.published_at, as_of)
        )
        contributions[signal.dimension].append(contribution)
        if relevance > 0:
            applicable[signal.dimension] += 1
            evidence_refs.append(signal.signal_id)
            temporal_terms.append(relevance)
            quality_terms.append(_EXTRACTION_MULTIPLIER[signal.confidence])
            freshness_terms.append(_recency(signal.published_at, as_of))

    review_wait = _mean(contributions[Dimension.short_wait])
    busyness_fit = _busyness_fit(busyness)
    wait_score, wait_reasons = _short_wait_score(review_wait, busyness_fit, applicable)
    scores: dict[Dimension, Decimal] = {}
    covered: set[Dimension] = set()
    reasons = list(wait_reasons)
    if len({item.relative_popularity for item in busyness}) > 1:
        reasons.append("conflicting_busyness")
    if busyness:
        temporal_terms.append(Decimal(1))
        quality_terms.append(Decimal(1))
        freshness_values = [_recency(item.captured_at.date(), as_of) for item in busyness]
        freshness_terms.append(_mean(freshness_values) or Decimal("0.50"))
    for dimension in Dimension:
        if dimension is Dimension.short_wait:
            scores[dimension] = quantize(wait_score)
            if applicable[dimension] > 0 or busyness:
                covered.add(dimension)
            else:
                reasons.append(f"missing_dimension:{dimension.value}")
            continue
        if applicable[dimension] == 0:
            scores[dimension] = quantize(Decimal(0))
            reasons.append(f"missing_dimension:{dimension.value}")
            continue
        covered.add(dimension)
        scores[dimension] = quantize(_mean(contributions[dimension]) or Decimal(0))
        if dimension in contradictory:
            reasons.append(f"contradictory_signals:{dimension.value}")
    if Dimension.short_wait in contradictory:
        reasons.append(f"contradictory_signals:{Dimension.short_wait.value}")

    fit = quantize(
        sum(weights[dimension] * scores[dimension] for dimension in Dimension) / Decimal(6)
    )
    confidence = _confidence(
        weights=weights,
        covered=covered,
        has_busyness=bool(busyness),
        has_review_wait=applicable[Dimension.short_wait] > 0,
        temporal_terms=temporal_terms,
        quality_terms=quality_terms,
        contradictory=contradictory,
        freshness_terms=freshness_terms,
    )
    has_evidence = bool(covered)
    fit_name = label_fit(fit, confidence, has_evidence=has_evidence)
    confidence_name = label_confidence(confidence)
    eligible = is_supported(fit, confidence, has_temporal_evidence=has_evidence)
    if not has_evidence:
        reasons.append("no_accepted_evidence")
    reasons.append("eligible" if eligible else "below_support_threshold")
    assessment = WindowAssessment(
        window_id=window_id,
        candidate_id=candidate.candidate_id,
        dimension_scores=scores,
        fit_score=fit,
        confidence_score=confidence,
        fit_label=fit_name,
        confidence_label=confidence_name,
        eligible=eligible,
        reason_codes=sorted(set(reasons)),
        evidence_refs=sorted(set(evidence_refs)),
        policy_version=SCORING_POLICY_VERSION,
    )
    return assessment


def _short_wait_score(
    review_wait: Decimal | None,
    busyness_fit: Decimal | None,
    applicable: dict[Dimension, int],
) -> tuple[Decimal, list[str]]:
    reasons: list[str] = []
    review_present = applicable[Dimension.short_wait] > 0 and review_wait is not None
    if not review_present:
        reasons.append("missing_review_wait")
    if busyness_fit is None:
        reasons.append("missing_busyness")
    if review_present and busyness_fit is not None:
        return _BUSYNESS_WEIGHT * busyness_fit + _REVIEW_WAIT_WEIGHT * review_wait, reasons
    if busyness_fit is not None:
        return _BUSYNESS_WEIGHT * busyness_fit, reasons
    if review_present and review_wait is not None:
        return _REVIEW_WAIT_WEIGHT * review_wait, reasons
    return Decimal(0), reasons


def _confidence(
    *,
    weights: dict[Dimension, Decimal],
    covered: set[Dimension],
    has_busyness: bool,
    has_review_wait: bool,
    temporal_terms: list[Decimal],
    quality_terms: list[Decimal],
    contradictory: set[Dimension],
    freshness_terms: list[Decimal],
) -> Decimal:
    if not temporal_terms:
        return quantize(Decimal(0))
    coverage_weight = Decimal(0)
    for dimension, weight in weights.items():
        if dimension not in covered:
            continue
        if dimension is Dimension.short_wait:
            fraction = Decimal(0)
            if has_busyness:
                fraction += _BUSYNESS_WEIGHT
            if has_review_wait:
                fraction += _REVIEW_WAIT_WEIGHT
            coverage_weight += weight * fraction
        else:
            coverage_weight += weight
    coverage = coverage_weight / Decimal(6)
    temporal = _mean(temporal_terms) or Decimal(0)
    quality = _mean(quality_terms) or Decimal(0)
    agreement_terms = []
    for dimension in Dimension:
        if dimension not in covered:
            continue
        agreement_terms.append(Decimal(0) if dimension in contradictory else Decimal(1))
    agreement = _mean(agreement_terms) or Decimal(0)
    freshness = _mean(freshness_terms) or Decimal(0)
    raw = (
        _CONFIDENCE_WEIGHTS["coverage"] * coverage
        + _CONFIDENCE_WEIGHTS["temporal"] * temporal
        + _CONFIDENCE_WEIGHTS["quality"] * quality
        + _CONFIDENCE_WEIGHTS["agreement"] * agreement
        + _CONFIDENCE_WEIGHTS["freshness"] * freshness
    )
    return quantize(raw)


def _busyness_for_window(
    observations: list[BusynessObservation],
    starts_at: datetime,
    ends_at: datetime,
) -> list[BusynessObservation]:
    matched: list[BusynessObservation] = []
    for observation in observations:
        observed_start = datetime.combine(
            starts_at.date(),
            observation.hour_start,
            tzinfo=starts_at.tzinfo,
        )
        observed_end = observed_start + timedelta(hours=1)
        same_day = observation.day_of_week.value == starts_at.strftime("%A").lower()
        if same_day and starts_at < observed_end and ends_at > observed_start:
            matched.append(observation)
    matched.sort(key=lambda item: (item.hour_start, item.relative_popularity, item.captured_at))
    return matched


def _busyness_fit(observations: list[BusynessObservation]) -> Decimal | None:
    if not observations:
        return None
    popularities = [Decimal(item.relative_popularity) for item in observations]
    relative = _mean(popularities) or Decimal(0)
    return Decimal(1) - Decimal(2) * (relative / Decimal(100))


def _signed_polarities(
    signals: list[AcceptedSignal],
    dimension: Dimension,
    starts_at: datetime,
    ends_at: datetime,
) -> set[Polarity]:
    found: set[Polarity] = set()
    for signal in signals:
        if signal.dimension is not dimension:
            continue
        relevance = temporal_relevance(
            signal.temporal_hint,
            signal.temporal_span,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        if relevance > 0 and signal.polarity is not Polarity.mixed:
            found.add(signal.polarity)
    return found


def _recency(published_at: date | None, as_of: datetime) -> Decimal:
    if published_at is None:
        return Decimal("0.50")
    age = (as_of.date() - published_at).days
    if age < 0 or age > 730:
        return Decimal("0.50")
    if age <= 180:
        return Decimal(1)
    return Decimal("0.75")


def _mean(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal(0)) / Decimal(len(values))


def _selection_key(
    assessment: WindowAssessment,
    priorities: list[Dimension],
    order: dict[str, tuple[str, datetime]],
) -> tuple[Decimal, Decimal, Decimal, datetime, str, str]:
    name, starts_at = order[assessment.window_id]
    return (
        -assessment.fit_score,
        -assessment.confidence_score,
        -assessment.dimension_scores[priorities[0]],
        starts_at,
        name,
        assessment.window_id,
    )


def _normalized_name(name: str) -> str:
    return " ".join(name.casefold().split())
