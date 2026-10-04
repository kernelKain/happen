"""Public recommendation request and response shapes."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from happen_api.catalog import CONTRACT_VERSION
from happen_api.domain.models import (
    ConfidenceLabel,
    Dimension,
    ExtractionConfidence,
    FitLabel,
    Outcome,
    Polarity,
    TemporalHint,
)

_CLOCK = r"^([01]\d|2[0-3]):(00|30)$"


class RecommendationRequest(BaseModel):
    """Shared planner request. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    neighborhood: Literal["indiranagar"]
    restaurant_category: Literal["restaurants"]
    arrival_start: str = Field(pattern=_CLOCK)
    arrival_end: str = Field(pattern=_CLOCK)
    desired_experience: Literal["easier_conversation"]
    priorities: list[Dimension] = Field(min_length=3, max_length=3)
    visit_date: date | None = None

    @field_validator(
        "neighborhood",
        "restaurant_category",
        "desired_experience",
        "arrival_start",
        "arrival_end",
        mode="before",
    )
    @classmethod
    def _trim(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("priorities", mode="before")
    @classmethod
    def _trim_priorities(cls, value: object) -> object:
        if isinstance(value, list):
            return [item.strip() if isinstance(item, str) else item for item in value]
        return value

    @field_validator("priorities")
    @classmethod
    def _ranked_once(cls, value: list[Dimension]) -> list[Dimension]:
        if set(value) != set(Dimension):
            raise ValueError("priorities must rank each dimension once")
        return value

    @model_validator(mode="after")
    def _arrival_span(self) -> RecommendationRequest:
        start = _minutes(self.arrival_start)
        end = _minutes(self.arrival_end)
        duration = end - start
        if duration < 60 or duration > 240:
            raise ValueError("arrival range must be between one and four hours")
        return self


class NormalizedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    neighborhood: str
    restaurant_category: str
    arrival_start: str
    arrival_end: str
    desired_experience: str
    priorities: list[str]
    visit_date: date


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["live", "captured_fixture"]
    captured_at: datetime
    generated_at: datetime
    timezone: Literal["Asia/Kolkata"]
    source_count: int = Field(ge=0)
    source_urls: list[str]
    safe_request_ids: list[str]
    model_id: str
    adapter_id: Literal["none"]
    extraction_schema_version: str
    scoring_policy_version: str
    fixture_version: str
    contract_version: str
    stale: bool
    data_label: Literal["synthetic_development", "captured_fixture", "live"]


class PublicWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: str
    arrival_start: str
    arrival_end: str
    feasibility: Literal["verified_open"]
    status: FitLabel
    fit_label: FitLabel
    confidence_label: ConfidenceLabel
    evidence_references: list[str]
    reason_codes: list[str]


class PublicCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    name: str
    source_url: str
    hours_summary: str
    evidence_summary: str
    windows: list[PublicWindow]
    missing_dimensions: list[Dimension]
    warnings: list[str]


class SelectedMoment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    window_id: str
    restaurant_name: str
    arrival_start: str
    arrival_end: str
    fit_label: FitLabel
    confidence_label: ConfidenceLabel
    explanation: str
    evidence_references: list[str]


class PublicEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    dimension: Dimension
    polarity: Polarity
    temporal_hint: TemporalHint
    quoted_span: str
    source_url: str
    captured_at: datetime
    extraction_confidence: ExtractionConfidence
    validation_status: Literal["accepted", "partially_accepted"]
    candidate_id: str
    window_ids: list[str]


class WarningItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    contract_version: str = CONTRACT_VERSION
    outcome: Outcome
    input: NormalizedInput
    provenance: Provenance
    candidates: list[PublicCandidate]
    recommendation: SelectedMoment | None
    fallback: SelectedMoment | None
    warnings: list[WarningItem]
    rejected_evidence_count: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    evidence: list[PublicEvidence]


def _minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)
