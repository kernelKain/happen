"""Measured model quality. A checksum match does not enable model claims."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from happen_api.config import Settings

_REPO_ROOT = Path(__file__).resolve().parents[4]
QUALITY_REPORT_PATH = _REPO_ROOT / "ml" / "reports" / "model-quality.json"
BASELINE_REPORT_PATH = _REPO_ROOT / "ml" / "reports" / "baseline-270m.json"
ModelQuality = Literal["passed", "failed", "unmeasured"]


def model_quality(settings: Settings) -> tuple[ModelQuality, bool]:
    """Return the measured gate for this artifact and whether its claims may be used."""

    report = _report()
    if report is None or report.get("measured_sha256") != settings.model_sha256:
        return "unmeasured", False
    enabled = report.get("claims_enabled") is True
    return ("passed" if enabled else "failed"), enabled


def model_claims_enabled(settings: Settings) -> bool:
    """Allow model-derived claims only after the checked-in gate has passed."""

    return model_quality(settings)[1]


def _report() -> dict[str, object] | None:
    if not QUALITY_REPORT_PATH.is_file():
        return None
    loaded = json.loads(QUALITY_REPORT_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return None
    return loaded
