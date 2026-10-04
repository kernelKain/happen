"""Public claims must match measured runtime behavior.

The customer path is deterministic local parsing plus Python selection. The
pinned Gemma artifact was measured and missed its gates, so it stays disabled.
These tests read the shipped files as a reviewer would and fail if a sentence
reappears that the measurements do not support.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_QUALITY = _REPO / "ml" / "reports" / "model-quality.json"

# Sentences that would assert a model does something it measurably does not do.
# Kept lowercase and space-normalised so line wrapping does not hide a match.
_BANNED = (
    "gemma runs locally",
    "gemma reads",
    "gemma reads the request",
    "gemma extracts evidence",
    "model reads the request",
    "local model reads",
    "open-source ai is at the runtime core",
    "best use of gemma",
    "powered by gemma",
)


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").casefold().split())


def _customer_copy() -> list[Path]:
    return [
        _REPO / "frontend" / "src" / "app" / "landing" / "Landing.tsx",
        _REPO / "frontend" / "src" / "app" / "landing" / "timeline.tsx",
    ]


def test_the_measured_report_is_untouched_and_still_refuses_claims() -> None:
    """The quality report must keep recording the failure. Do not edit it to pass."""

    report = json.loads(_QUALITY.read_text(encoding="utf-8"))
    assert report["claims_enabled"] is False
    assert report["selected_fallback"] == "deterministic_parser"
    assert report["planning"]["schema_gate"] is False
    assert report["planning"]["essential_gate"] is False
    assert report["review"]["review_gate"] is False


def test_the_customer_page_does_not_claim_a_model_reads_the_request() -> None:
    """The landing copy must not describe the disabled model as active."""

    for path in _customer_copy():
        text = _normalized(path)
        for phrase in _BANNED:
            assert phrase not in text, f"{path.name} still claims: {phrase}"


def test_the_customer_page_states_the_real_mechanism() -> None:
    """The page must name the deterministic parser and Python selection."""

    landing = _normalized(_REPO / "frontend" / "src" / "app" / "landing" / "Landing.tsx")
    assert "deterministic" in landing
    assert "python picks the stops" in landing
    # The model may be named only as measured and switched off.
    assert "gemma" in landing
    assert "missed its quality gates" in landing


def test_readme_does_not_claim_the_model_reads_the_prompt() -> None:
    """README statements must stay inside what the report measured."""

    readme = _normalized(_REPO / "README.md")
    for phrase in _BANNED:
        assert phrase not in readme, f"README still claims: {phrase}"
    assert "the customer path loads no model" in readme
    assert "deterministic parser" in readme
    # The failure must be reported, not spun as a win.
    assert "missed its gates" in readme or "failed" in readme


def test_no_document_claims_a_gemma_prize_or_ai_runtime_core() -> None:
    """Submission guidance must not promise a prize the build does not earn."""

    for path in sorted((_REPO / "docs").glob("*.md")) + [_REPO / "README.md"]:
        text = _normalized(path)
        for phrase in ("best use of gemma", "open-source ai is at the runtime core"):
            assert phrase not in text, f"{path.name} still claims: {phrase}"


def test_the_python_scoring_claim_is_now_backed_by_code() -> None:
    """Docs say Python scores constraints. Confirm the code path exists."""

    scoring = _REPO / "backend" / "src" / "happen_api" / "planning" / "itinerary.py"
    text = scoring.read_text(encoding="utf-8")
    assert "constraint_points" in text
    assert "preferences" in text


@pytest.mark.parametrize(
    "phrase",
    [
        "Gemma runs locally",
        "Gemma reads the request",
        "Gemma extracts evidence",
    ],
)
def test_each_banned_phrase_is_itself_rejected(phrase: str) -> None:
    """Guard the guard: the banned list is lowercased and normalized."""

    assert phrase.casefold() in _BANNED
