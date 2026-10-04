"""Domain records used by timing and deterministic scoring."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Dimension(StrEnum):
    conversation = "conversation"
    short_wait = "short_wait"
    seating = "seating"


class Polarity(StrEnum):
    positive = "positive"
    mixed = "mixed"
    negative = "negative"


class TemporalHint(StrEnum):
    specific_time = "specific_time"
    early_evening = "early_evening"
    mid_evening = "mid_evening"
    late_evening = "late_evening"
    weekday = "weekday"
    weekend = "weekend"
    general = "general"
    unknown = "unknown"


class ExtractionConfidence(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class FitLabel(StrEnum):
    strong = "strong"
    possible = "possible"
    weak = "weak"
    unknown = "unknown"


class ConfidenceLabel(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    insufficient = "insufficient"


class HoursConfidence(StrEnum):
    verified = "verified"
    uncertain = "uncertain"


class OpenStatus(StrEnum):
    verified_open = "verified_open"
    uncertain = "uncertain"


class Outcome(StrEnum):
    recommendation = "recommendation"
    partial_evidence = "partial_evidence"
    insufficient_evidence = "insufficient_evidence"


class DayOfWeek(StrEnum):
    monday = "monday"
    tuesday = "tuesday"
    wednesday = "wednesday"
    thursday = "thursday"
    friday = "friday"
    saturday = "saturday"
    sunday = "sunday"


def _http_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source_url must be an http or https URL")
    return value


class OpeningInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    opens_at: time
    closes_at: time
    source_url: str
    confidence: HoursConfidence

    @field_validator("source_url")
    @classmethod
    def _source_url(cls, value: str) -> str:
        return _http_url(value)


class BusynessObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_of_week: DayOfWeek
    hour_start: time
    relative_popularity: int = Field(ge=0, le=100)
    observation_kind: Literal["typical_popularity"] = "typical_popularity"
    source_url: str
    captured_at: datetime

    @field_validator("source_url")
    @classmethod
    def _source_url(cls, value: str) -> str:
        return _http_url(value)

    @field_validator("hour_start")
    @classmethod
    def _hour_boundary(cls, value: time) -> time:
        if value.minute or value.second or value.microsecond:
            raise ValueError("hour_start must be an hour boundary")
        return value

    @field_validator("captured_at")
    @classmethod
    def _aware_capture(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        return value


class ArrivalWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: str = Field(min_length=1, max_length=160)
    candidate_id: str = Field(min_length=1, max_length=80)
    starts_at: datetime
    ends_at: datetime
    open_status: OpenStatus
    busyness_refs: list[str]
    evidence_refs: list[str]

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("window bounds must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _half_hour(self) -> ArrivalWindow:
        if self.ends_at - self.starts_at != timedelta(minutes=30):
            raise ValueError("an arrival window must last 30 minutes")
        return self


class ReviewExcerpt(BaseModel):
    """Bounded, identity-free review text for one candidate."""

    model_config = ConfigDict(extra="forbid")

    excerpt_id: str = Field(min_length=1, max_length=80)
    candidate_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=400)
    published_at: date | None = None
    captured_at: datetime
    source_url: str
    language: Literal["en"]
    truncated: bool

    @field_validator("source_url")
    @classmethod
    def _source_url(cls, value: str) -> str:
        return _http_url(value)

    @field_validator("text")
    @classmethod
    def _plain_text(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("excerpt text must not include control characters")
        return value

    @field_validator("captured_at")
    @classmethod
    def _aware_capture(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        return value


class NormalizedPlace(BaseModel):
    """Provider-independent restaurant candidate."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=80)
    provider_place_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    category_tags: list[str] = Field(min_length=1, max_length=8)
    source_url: str
    opening_intervals: list[OpeningInterval] = Field(max_length=8)
    busyness_observations: list[BusynessObservation] = Field(max_length=24)
    review_excerpts: list[ReviewExcerpt] = Field(max_length=8)
    eligibility_reasons: list[str] = Field(max_length=8)
    warnings: list[str] = Field(max_length=8)

    @field_validator("source_url")
    @classmethod
    def _source_url(cls, value: str) -> str:
        return _http_url(value)


class AcceptedSignal(BaseModel):
    """One review signal that has already passed exact-span validation."""

    model_config = ConfigDict(extra="forbid")

    signal_id: str = Field(min_length=1, max_length=80)
    candidate_id: str = Field(min_length=1, max_length=80)
    dimension: Dimension
    polarity: Polarity
    temporal_hint: TemporalHint
    temporal_span: str | None = None
    confidence: ExtractionConfidence
    published_at: date | None = None


class HoursParse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["verified", "closed", "uncertain"]
    intervals: list[OpeningInterval]
    reason_codes: list[str]


class CandidateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    windows: list[ArrivalWindow]
    signals: list[AcceptedSignal]
    busyness: list[BusynessObservation]


class WindowAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: str
    candidate_id: str
    dimension_scores: dict[Dimension, Decimal]
    fit_score: Decimal
    confidence_score: Decimal
    fit_label: FitLabel
    confidence_label: ConfidenceLabel
    eligible: bool
    reason_codes: list[str]
    evidence_refs: list[str]
    policy_version: str


class RecommendationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Outcome
    candidate_assessments: list[WindowAssessment]
    primary_window_id: str | None
    fallback_window_id: str | None
    reason_codes: list[str]
    missing_dimensions: list[Dimension]
    policy_version: str
