"""Load the installed fixture after a checksum check.

The development scenario is synthetic. It is not reported as live evidence
or as a verified SerpApi capture. Checksum and schema failures stop loading.
Evidence older than seven days still loads and is marked stale.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from happen_api.catalog import SCORING_POLICY_VERSION
from happen_api.domain.timing import KOLKATA
from happen_api.fixtures.schema import (
    FIXTURE_SCHEMA_VERSION,
    FixtureError,
    FixtureManifest,
    FixtureRequest,
    FixtureScenario,
    LoadedFixture,
)

_FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "v1"
_CAPTURED_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[3] / "data" / "fixtures" / "captured" / "v1"
)
_STALE_AFTER = timedelta(days=7)


def captured_fixture_root() -> Path:
    """Return the installed SerpApi capture, separate from the synthetic fixture."""

    return _CAPTURED_FIXTURE_ROOT


def load_fixture(
    request: FixtureRequest,
    *,
    visit_date: datetime | date | None = None,
    root: Path | None = None,
    as_of: datetime | None = None,
) -> LoadedFixture:
    """Return the scenario that matches the request, or raise FixtureError."""

    fixture_root = (root or _FIXTURE_ROOT).resolve()
    manifest = _read_manifest(fixture_root)
    observed_at = _aware_as_of(as_of)
    requested_date = _requested_date(visit_date)
    matches: list[LoadedFixture] = []
    for entry in manifest.scenarios:
        scenario, checksum = _read_scenario(fixture_root, entry.path, entry.sha256)
        if scenario.fixture_id != entry.scenario_id:
            raise FixtureError("FIXTURE_SCHEMA_INVALID", "The fixture scenario id does not match.")
        if scenario.schema_version != FIXTURE_SCHEMA_VERSION:
            raise FixtureError(
                "FIXTURE_SCHEMA_INVALID", "The fixture schema version is not supported."
            )
        if not _same_request(scenario.request, request):
            continue
        if requested_date is not None and scenario.visit_date != requested_date:
            continue
        matches.append(_loaded(scenario, manifest.fixture_version, checksum, observed_at))
    if len(matches) != 1:
        raise FixtureError("FIXTURE_NOT_AVAILABLE", "No installed fixture matches this request.")
    return matches[0]


def _read_manifest(root: Path) -> FixtureManifest:
    path = root / "manifest.json"
    if not path.is_file():
        raise FixtureError("FIXTURE_NOT_AVAILABLE", "The fixture manifest is missing.")
    payload = _json_object(path)
    try:
        return FixtureManifest.model_validate(payload)
    except ValidationError:
        raise FixtureError(
            "FIXTURE_SCHEMA_INVALID", "The fixture manifest schema is invalid."
        ) from None


def _read_scenario(root: Path, relative: str, expected_sha256: str) -> tuple[FixtureScenario, str]:
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise FixtureError("FIXTURE_SCHEMA_INVALID", "The fixture scenario path is not allowed.")
    if not path.is_file():
        raise FixtureError("FIXTURE_NOT_AVAILABLE", "The fixture scenario file is missing.")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise FixtureError(
            "FIXTURE_CHECKSUM_INVALID", "The fixture checksum does not match the manifest."
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise FixtureError(
            "FIXTURE_SCHEMA_INVALID", "The fixture scenario is not valid JSON."
        ) from None
    if not isinstance(payload, dict):
        raise FixtureError("FIXTURE_SCHEMA_INVALID", "The fixture scenario schema is invalid.")
    try:
        return FixtureScenario.model_validate(payload), digest
    except ValidationError:
        raise FixtureError(
            "FIXTURE_SCHEMA_INVALID", "The fixture scenario schema is invalid."
        ) from None


def _json_object(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise FixtureError(
            "FIXTURE_SCHEMA_INVALID", "The fixture manifest is not valid JSON."
        ) from None


def _loaded(
    scenario: FixtureScenario,
    fixture_version: str,
    checksum: str,
    as_of: datetime,
) -> LoadedFixture:
    return LoadedFixture(
        fixture_id=scenario.fixture_id,
        fixture_version=fixture_version,
        schema_version=scenario.schema_version,
        data_label=scenario.data_label,
        checksum=checksum,
        stale=as_of - scenario.captured_at > _STALE_AFTER,
        captured_at=scenario.captured_at,
        timezone="Asia/Kolkata",
        visit_date=scenario.visit_date,
        request=scenario.request,
        places=scenario.places,
        source_urls=list(scenario.source_urls),
        safe_request_ids=list(scenario.safe_request_ids),
        attribution=scenario.attribution,
        disclaimer=scenario.disclaimer,
        scoring_policy_version=SCORING_POLICY_VERSION,
        adapter_id="none",
    )


def _same_request(installed: FixtureRequest, requested: FixtureRequest) -> bool:
    return installed.model_dump() == requested.model_dump()


def _requested_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise FixtureError("FIXTURE_SCHEMA_INVALID", "The visit date must be timezone-aware.")
        return value.astimezone(KOLKATA).date()
    return value


def _aware_as_of(value: datetime | None) -> datetime:
    current = value or datetime.now(KOLKATA)
    if current.tzinfo is None or current.utcoffset() is None:
        raise FixtureError("FIXTURE_SCHEMA_INVALID", "The freshness clock must be timezone-aware.")
    return current
