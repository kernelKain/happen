"""Versioned fixture documents. A loaded fixture has no precomputed winner."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from happen_api.catalog import PRIORITIES, TIMEZONE
from happen_api.domain.models import Dimension, NormalizedPlace

FIXTURE_SCHEMA_VERSION = "1.0.0"
FIXTURE_VERSION = "1.0.0"
SYNTHETIC_LABEL = "synthetic_development"
LOCKED_DISCLAIMER = "Planning evidence—not live occupancy."
_FORBIDDEN_PHRASES = ("currently quiet", "live wait", "available now")


class FixtureError(Exception):
    """A fixture could not be loaded. The message omits paths and secrets."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class FixtureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    neighborhood: Literal["indiranagar"]
    restaurant_category: Literal["restaurants"]
    arrival_start: str = Field(pattern=r"^([01]\d|2[0-3]):(00|30)$")
    arrival_end: str = Field(pattern=r"^([01]\d|2[0-3]):(00|30)$")
    desired_experience: Literal["easier_conversation"]
    priorities: list[Dimension] = Field(min_length=3, max_length=3)

    @field_validator("priorities")
    @classmethod
    def _ranked_once(cls, value: list[Dimension]) -> list[Dimension]:
        if set(value) != set(Dimension):
            raise ValueError("priorities must rank each dimension once")
        return value


class ExpectedStructure(BaseModel):
    """Test-only shape check. It does not name a winning window."""

    model_config = ConfigDict(extra="forbid")

    candidate_count: int = Field(ge=1, le=3)
    labeled_synthetic: Literal[True]


class FixtureScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: str = Field(min_length=1, max_length=80)
    schema_version: Literal["1.0.0"]
    data_label: Literal["synthetic_development"]
    visit_date: date
    timezone: Literal["Asia/Kolkata"]
    captured_at: datetime
    request: FixtureRequest
    places: list[NormalizedPlace] = Field(min_length=1, max_length=3)
    source_urls: list[str] = Field(min_length=1, max_length=6)
    safe_request_ids: list[str] = Field(min_length=1, max_length=4)
    attribution: str = Field(min_length=1, max_length=400)
    disclaimer: str = Field(min_length=1, max_length=400)
    expected_structure: ExpectedStructure

    @field_validator("captured_at")
    @classmethod
    def _aware_capture(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _synthetic_contract(self) -> FixtureScenario:
        if self.expected_structure.candidate_count != len(self.places):
            raise ValueError("candidate_count must match the places in the fixture")
        if "Synthetic" not in self.attribution or "not a SerpApi capture" not in self.attribution:
            raise ValueError("synthetic fixtures must say they are fictional")
        if LOCKED_DISCLAIMER not in self.disclaimer:
            raise ValueError("disclaimer must include the locked planning sentence")
        texts = [self.attribution, self.disclaimer]
        for place in self.places:
            texts.append(place.name)
            for excerpt in place.review_excerpts:
                texts.append(excerpt.text)
                if excerpt.candidate_id != place.candidate_id:
                    raise ValueError("review excerpts must belong to their candidate")
                if not excerpt.text.startswith("Synthetic note:"):
                    raise ValueError("synthetic excerpts must be visibly labeled")
        lowered = "\n".join(texts).casefold()
        if any(phrase in lowered for phrase in _FORBIDDEN_PHRASES):
            raise ValueError("fixture copy must not claim live conditions")
        if self.timezone != TIMEZONE:
            raise ValueError("fixture timezone must be Asia/Kolkata")
        return self


class ManifestScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=160)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        if value.startswith("/") or "\\" in value or ".." in value.split("/"):
            raise ValueError("fixture scenario path must stay inside the fixture directory")
        return value


class FixtureManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    fixture_version: Literal["1.0.0"]
    scenarios: list[ManifestScenario] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _unique_ids(self) -> FixtureManifest:
        ids = [item.scenario_id for item in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("fixture scenario ids must be unique")
        return self


class LoadedFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: str
    fixture_version: str
    schema_version: str
    data_label: Literal["synthetic_development"]
    checksum: str
    stale: bool
    captured_at: datetime
    timezone: Literal["Asia/Kolkata"]
    visit_date: date
    request: FixtureRequest
    places: list[NormalizedPlace]
    source_urls: list[str]
    safe_request_ids: list[str]
    attribution: str
    disclaimer: str
    scoring_policy_version: str
    adapter_id: Literal["none"]


def canonical_request() -> FixtureRequest:
    """Return the installed Indiranagar dinner request without a visit date."""

    return FixtureRequest(
        neighborhood="indiranagar",
        restaurant_category="restaurants",
        arrival_start="18:00",
        arrival_end="21:00",
        desired_experience="easier_conversation",
        priorities=[Dimension(item) for item in PRIORITIES],
    )
