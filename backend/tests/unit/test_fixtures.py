"""Synthetic fixture loading, checksums, staleness, and specific failures."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from happen_api.catalog import SCORING_POLICY_VERSION
from happen_api.domain.timing import KOLKATA, generate_arrival_windows
from happen_api.fixtures.loader import load_fixture
from happen_api.fixtures.schema import (
    LOCKED_DISCLAIMER,
    ExpectedStructure,
    FixtureError,
    FixtureScenario,
    canonical_request,
)

CAPTURED_AT = datetime(2026, 10, 3, 12, 0, tzinfo=KOLKATA)
VISIT = date(2026, 10, 3)


def test_canonical_preset_loads_the_labeled_synthetic_fixture() -> None:
    """Verify the installed dinner fixture is synthetic, checksummed, and has three places."""

    loaded = load_fixture(canonical_request(), as_of=CAPTURED_AT)
    assert loaded.data_label == "synthetic_development"
    assert loaded.fixture_id == "indiranagar-dinner"
    assert loaded.schema_version == "1.0.0"
    assert loaded.fixture_version == "1.0.0"
    assert loaded.checksum == _installed_checksum()
    assert loaded.stale is False
    assert loaded.visit_date == VISIT
    assert loaded.timezone == "Asia/Kolkata"
    assert loaded.adapter_id == "none"
    assert loaded.scoring_policy_version == SCORING_POLICY_VERSION
    assert len(loaded.places) == 3
    assert loaded.safe_request_ids == ["synthetic-indiranagar-dinner"]
    assert "Synthetic" in loaded.attribution
    assert "not a SerpApi capture" in loaded.attribution
    assert LOCKED_DISCLAIMER in loaded.disclaimer
    assert "primary_window_id" not in FixtureScenario.model_fields
    assert "primary_window_id" not in ExpectedStructure.model_fields
    rendered = loaded.model_dump_json()
    assert "reviewer" not in rendered.casefold()
    assert "api_key" not in rendered.casefold()
    assert all(url.startswith("https://") for url in loaded.source_urls)


def test_recorded_visit_date_matches_and_a_different_date_does_not() -> None:
    """Verify an omitted date uses the fixture date and another date is unavailable."""

    matched = load_fixture(canonical_request(), visit_date=VISIT, as_of=CAPTURED_AT)
    assert matched.visit_date == VISIT
    with pytest.raises(FixtureError) as missing:
        load_fixture(canonical_request(), visit_date=date(2026, 10, 4), as_of=CAPTURED_AT)
    assert missing.value.code == "FIXTURE_NOT_AVAILABLE"


def test_loaded_hours_use_the_same_window_generator() -> None:
    """Verify fixture intervals become the same 30-minute windows as direct timing input."""

    loaded = load_fixture(canonical_request(), as_of=CAPTURED_AT)
    for place in loaded.places:
        windows = generate_arrival_windows(
            candidate_id=place.candidate_id,
            visit_date=loaded.visit_date,
            arrival_start=time.fromisoformat(loaded.request.arrival_start),
            arrival_end=time.fromisoformat(loaded.request.arrival_end),
            intervals=place.opening_intervals,
            busyness=place.busyness_observations,
        )
        assert [item.starts_at.strftime("%H:%M") for item in windows] == [
            "18:00",
            "18:30",
            "19:00",
            "19:30",
            "20:00",
            "20:30",
        ]
        assert all(item.ends_at <= datetime(2026, 10, 3, 23, 0, tzinfo=KOLKATA) for item in windows)
    quiet = next(place for place in loaded.places if place.candidate_id == "north-gallery")
    missing_busyness = next(
        place for place in loaded.places if place.candidate_id == "platform-seats"
    )
    assert quiet.busyness_observations[0].relative_popularity == 20
    assert missing_busyness.busyness_observations == []
    assert missing_busyness.review_excerpts[0].text.startswith("Synthetic note:")


def test_evidence_older_than_seven_days_is_stale_and_still_loads() -> None:
    """Verify the seven-day boundary marks stale evidence without rejecting it."""

    fresh = load_fixture(canonical_request(), as_of=CAPTURED_AT + timedelta(days=7))
    stale = load_fixture(
        canonical_request(),
        as_of=CAPTURED_AT + timedelta(days=7, seconds=1),
    )
    assert fresh.stale is False
    assert stale.stale is True
    assert stale.fixture_id == fresh.fixture_id


def test_repeated_loads_match() -> None:
    """Verify the loader is stable across repeated reads."""

    first = load_fixture(canonical_request(), as_of=CAPTURED_AT).model_dump(mode="json")
    second = load_fixture(canonical_request(), as_of=CAPTURED_AT).model_dump(mode="json")
    assert first == second


def test_missing_manifest_or_scenario_is_unavailable(tmp_path: Path) -> None:
    """Verify a missing manifest or scenario fails as unavailable, without a path."""

    with pytest.raises(FixtureError) as missing_root:
        load_fixture(canonical_request(), root=tmp_path, as_of=CAPTURED_AT)
    assert missing_root.value.code == "FIXTURE_NOT_AVAILABLE"
    copied = _copy_fixture(tmp_path)
    (copied / "scenarios" / "indiranagar-dinner.json").unlink()
    with pytest.raises(FixtureError) as missing_file:
        load_fixture(canonical_request(), root=copied, as_of=CAPTURED_AT)
    assert missing_file.value.code == "FIXTURE_NOT_AVAILABLE"
    assert "indiranagar-dinner.json" not in str(missing_file.value)
    assert str(copied) not in str(missing_file.value)


def test_checksum_mismatch_fails_before_a_changed_scenario_is_used(tmp_path: Path) -> None:
    """Verify edited fixture bytes fail the manifest checksum."""

    copied = _copy_fixture(tmp_path)
    scenario = copied / "scenarios" / "indiranagar-dinner.json"
    scenario.write_text(
        scenario.read_text(encoding="utf-8").replace("quiet tables", "quiet booths")
    )
    with pytest.raises(FixtureError) as mismatch:
        load_fixture(canonical_request(), root=copied, as_of=CAPTURED_AT)
    assert mismatch.value.code == "FIXTURE_CHECKSUM_INVALID"
    assert str(copied) not in str(mismatch.value)


def test_schema_errors_are_distinct_from_a_checksum_match(tmp_path: Path) -> None:
    """Verify corrupt JSON and unknown fields fail schema validation after the checksum matches."""

    copied = _copy_fixture(tmp_path)
    scenario = copied / "scenarios" / "indiranagar-dinner.json"
    scenario.write_bytes(b"{")
    _set_checksum(copied, scenario)
    with pytest.raises(FixtureError) as corrupt:
        load_fixture(canonical_request(), root=copied, as_of=CAPTURED_AT)
    assert corrupt.value.code == "FIXTURE_SCHEMA_INVALID"

    original = _copy_fixture(tmp_path / "extra")
    extra_path = original / "scenarios" / "indiranagar-dinner.json"
    payload = json.loads(extra_path.read_text(encoding="utf-8"))
    payload["primary_window_id"] = "north-gallery:2026-10-03T19:00"
    extra_path.write_text(json.dumps(payload), encoding="utf-8")
    _set_checksum(original, extra_path)
    with pytest.raises(FixtureError) as extra:
        load_fixture(canonical_request(), root=original, as_of=CAPTURED_AT)
    assert extra.value.code == "FIXTURE_SCHEMA_INVALID"


def test_a_different_arrival_range_is_unavailable() -> None:
    """Verify a request outside the installed signature does not load the dinner fixture."""

    other = canonical_request().model_copy(
        update={"arrival_start": "19:00", "arrival_end": "22:00"}
    )
    with pytest.raises(FixtureError) as missing:
        load_fixture(other, as_of=CAPTURED_AT)
    assert missing.value.code == "FIXTURE_NOT_AVAILABLE"


def _installed_checksum() -> str:
    path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "fixtures"
        / "v1"
        / "scenarios"
        / "indiranagar-dinner.json"
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_fixture(destination: Path) -> Path:
    source = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "v1"
    target = destination / "v1"
    shutil.copytree(source, target)
    return target


def _set_checksum(root: Path, scenario: Path) -> None:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["scenarios"][0]["sha256"] = hashlib.sha256(scenario.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
