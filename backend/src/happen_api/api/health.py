"""Process health and runtime metadata. Neither route loads the model."""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from happen_api import __version__
from happen_api.catalog import (
    CANONICAL_PRESET,
    CATEGORIES,
    CONTRACT_VERSION,
    EXPERIENCES,
    NEIGHBORHOODS,
    PRIORITIES,
    SCORING_POLICY_VERSION,
    TIMEZONE,
)
from happen_api.config import Settings
from happen_api.readiness import (
    FixtureStatus,
    ModelStatus,
    captured_fixture_status,
    model_artifact_status,
)

router = APIRouter()


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    service_version: str
    contract_version: str
    model_status: ModelStatus
    fixture_status: FixtureStatus
    uptime_seconds: float = Field(ge=0)


class CanonicalPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    neighborhood: str
    restaurant_category: str
    arrival_start: str
    arrival_end: str
    desired_experience: str
    priorities: list[str]


class MetaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str
    service_version: str
    supported_neighborhoods: list[str]
    supported_categories: list[str]
    supported_experiences: list[str]
    priority_dimensions: list[str]
    canonical_preset: CanonicalPreset
    fixture_available: bool
    live_available: bool
    model_status: ModelStatus
    scoring_policy_version: str
    timezone: str


def dependency_status(
    settings: Settings,
) -> tuple[Literal["ok", "degraded"], ModelStatus, FixtureStatus, bool]:
    """Report file readiness without loading the Gemma runtime."""

    model_status = model_artifact_status(settings)
    fixture_status, fixture_available = captured_fixture_status()
    status: Literal["ok", "degraded"] = (
        "ok" if model_status == "ready" and fixture_status == "ready" else "degraded"
    )
    return status, model_status, fixture_status, fixture_available


@router.get("/healthz", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Return process health and uptime without loading the Gemma runtime."""

    settings: Settings = request.app.state.settings
    status, model_status, fixture_status, _fixture_available = dependency_status(settings)
    uptime = time.monotonic() - request.app.state.started_at
    return HealthResponse(
        status=status,
        service_version=__version__,
        contract_version=CONTRACT_VERSION,
        model_status=model_status,
        fixture_status=fixture_status,
        uptime_seconds=round(max(uptime, 0), 3),
    )


@router.get("/api/v1/meta", response_model=MetaResponse)
def meta(request: Request) -> MetaResponse:
    """Return supported planner choices, the preset, and configured service availability."""

    settings: Settings = request.app.state.settings
    _, model_status, _, fixture_available = dependency_status(settings)
    return MetaResponse(
        contract_version=CONTRACT_VERSION,
        service_version=__version__,
        supported_neighborhoods=list(NEIGHBORHOODS),
        supported_categories=list(CATEGORIES),
        supported_experiences=list(EXPERIENCES),
        priority_dimensions=list(PRIORITIES),
        canonical_preset=CanonicalPreset.model_validate(CANONICAL_PRESET),
        fixture_available=fixture_available,
        live_available=settings.live_configured,
        model_status=model_status,
        scoring_policy_version=SCORING_POLICY_VERSION,
        timezone=TIMEZONE,
    )
