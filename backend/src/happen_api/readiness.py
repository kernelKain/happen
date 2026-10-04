"""Report whether the pinned model file and captured fixture are installed.

Health checks use this module instead of loading Gemma. A checksum is cached
for the life of the process after the first look at an unchanged file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from happen_api.ai.extractor import model_file
from happen_api.config import Settings
from happen_api.fixtures.loader import captured_fixture_root, load_fixture
from happen_api.fixtures.schema import FixtureError, canonical_request

ModelStatus = Literal["not_loaded", "loading", "ready", "unavailable"]
FixtureStatus = Literal["ready", "unavailable", "invalid"]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST_PATH = _REPO_ROOT / "ml" / "model-manifest.json"
_DIGESTS: dict[tuple[str, int, int], str] = {}


def model_artifact_status(settings: Settings) -> ModelStatus:
    """Return ready only when the configured file exists and matches its checksum."""

    path = model_file(settings)
    if not path.is_file():
        return "not_loaded"
    expected_size = _expected_size(settings)
    size = path.stat().st_size
    if expected_size is not None and size != expected_size:
        return "unavailable"
    if _sha256(path) != settings.model_sha256:
        return "unavailable"
    return "ready"


def captured_fixture_status() -> tuple[FixtureStatus, bool]:
    """Return whether the canonical captured fixture loads and verifies."""

    try:
        load_fixture(canonical_request(), root=captured_fixture_root())
    except FixtureError as exc:
        if exc.code in {"FIXTURE_CHECKSUM_INVALID", "FIXTURE_SCHEMA_INVALID"}:
            return "invalid", False
        return "unavailable", False
    return "ready", True


def _expected_size(settings: Settings) -> int | None:
    if not _MANIFEST_PATH.is_file():
        return None
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    if (
        settings.model_filename != manifest["filename"]
        or settings.model_sha256 != str(manifest["sha256"]).lower()
    ):
        return None
    return int(manifest["size_bytes"])


def _sha256(path: Path) -> str:
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    cached = _DIGESTS.get(key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    _DIGESTS[key] = value
    return value
