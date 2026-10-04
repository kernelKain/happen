"""Write a sanitized SerpApi snapshot and check that replay matches the live decision.

The script makes one bounded provider retrieval. It does not print the API key
or store the raw provider document.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from happen_api.ai.prompt import EXTRACTION_SCHEMA_VERSION
from happen_api.catalog import CANONICAL_PRESET, CONTRACT_VERSION, SCORING_POLICY_VERSION
from happen_api.config import Settings, get_settings
from happen_api.domain.models import NormalizedPlace
from happen_api.domain.timing import KOLKATA
from happen_api.fixtures.loader import load_fixture
from happen_api.fixtures.schema import (
    LOCKED_DISCLAIMER,
    SYNTHETIC_LABEL,
    ExpectedStructure,
    FixtureRequest,
    FixtureScenario,
    canonical_request,
)
from happen_api.providers.serpapi.guard import CachedEvidence, LiveGuard
from happen_api.recommendations.contracts import (
    Provenance,
    RecommendationRequest,
    RecommendationResponse,
)
from happen_api.recommendations.live import fetch_live_evidence
from happen_api.recommendations.service import RecommendationFailure, score_places

_CAPTURE_ROOT = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "captured" / "v1"
_SCENARIO_PATH = "scenarios/indiranagar-dinner.json"
_CAPTURE_BUDGET = 14
_PHONE = re.compile(r"(?:\+\d[\s.-]?)?(?:\d[\s.-]?){9,}\d")
_IDENTIFYING_PATH = ("/contrib", "/reviews/contrib")
_ATTRIBUTION = (
    "Captured from SerpApi Google Maps for restaurants in Indiranagar, Bengaluru. "
    "Reviewer identities and phone numbers are omitted."
)


def main() -> int:
    """Capture the canonical Indiranagar snapshot once, then replay it."""

    settings = get_settings()
    if not settings.serpapi_api_key.get_secret_value().strip():
        print("SERPAPI_API_KEY is not configured.", file=sys.stderr)
        return 1
    if not settings.happen_live_enabled:
        settings = settings.model_copy(update={"happen_live_enabled": True})
    now = datetime.now(KOLKATA)
    guard = LiveGuard(budget=_CAPTURE_BUDGET)
    try:
        evidence = fetch_live_evidence(settings=settings, now=now, guard=guard)
    except RecommendationFailure as exc:
        print(f"Live capture stopped: {exc.code}. Searches recorded: {guard.spent}.")
        return 1
    places = _public_places(evidence)
    if len(places) != 3:
        print(
            "Live capture returned "
            f"{len(places)} places ({', '.join(evidence.reason_codes) or 'no reason'}). "
            f"Searches recorded: {guard.spent}."
        )
        return 1
    secret = settings.serpapi_api_key.get_secret_value()
    scenario = _scenario(evidence, places, now)
    root = _write(scenario, secret)
    loaded = load_fixture(canonical_request(), root=root, as_of=now)
    if [place.model_dump(mode="json") for place in loaded.places] != [
        place.model_dump(mode="json") for place in places
    ]:
        print("Reloaded fixture places do not match the live snapshot.")
        return 1
    body = RecommendationRequest.model_validate(CANONICAL_PRESET)
    live_decision = _score(places, body, settings, now, evidence, mode="live", label="live")
    replay_decision = _score(
        loaded.places,
        body,
        settings,
        now,
        evidence,
        mode="captured_fixture",
        label="captured_fixture",
        fixture_version=loaded.fixture_version,
        stale=loaded.stale,
    )
    if decision_signature(live_decision) != decision_signature(replay_decision):
        print("Fixture replay decision does not match the live decision.")
        return 1
    names = ", ".join(place.name for place in places)
    print(
        f"Captured 3 places ({names}). Outcome {live_decision.outcome.value}. "
        f"Searches recorded: {guard.spent}. Parity matched."
    )
    return 0


def decision_signature(response: RecommendationResponse) -> dict[str, object]:
    """Return the scored decision without request identity or provenance mode."""

    payload = response.model_dump(mode="json")
    return {
        "outcome": payload["outcome"],
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "name": candidate["name"],
                "windows": [
                    {
                        "window_id": window["window_id"],
                        "fit_label": window["fit_label"],
                        "confidence_label": window["confidence_label"],
                        "reason_codes": window["reason_codes"],
                    }
                    for window in candidate["windows"]
                ],
            }
            for candidate in payload["candidates"]
        ],
        "recommendation": _moment(payload["recommendation"]),
        "fallback": _moment(payload["fallback"]),
        "evidence": [
            {
                "candidate_id": item["candidate_id"],
                "dimension": item["dimension"],
                "polarity": item["polarity"],
                "quoted_span": item["quoted_span"],
            }
            for item in payload["evidence"]
        ],
        "rejected_evidence_count": payload["rejected_evidence_count"],
    }


def _public_places(evidence: CachedEvidence) -> list[NormalizedPlace]:
    places = [place for place in evidence.places if isinstance(place, NormalizedPlace)]
    cleaned: list[NormalizedPlace] = []
    for place in places:
        excerpts = []
        for excerpt in place.review_excerpts:
            if _PHONE.search(excerpt.text):
                continue
            source_url = (
                place.source_url if _identifying(excerpt.source_url) else excerpt.source_url
            )
            excerpts.append(excerpt.model_copy(update={"source_url": source_url}))
        cleaned.append(place.model_copy(update={"review_excerpts": excerpts}))
    return cleaned


def _scenario(
    evidence: CachedEvidence,
    places: list[NormalizedPlace],
    now: datetime,
) -> FixtureScenario:
    captured_at = evidence.captured_at if isinstance(evidence.captured_at, datetime) else now
    return FixtureScenario(
        fixture_id="indiranagar-dinner",
        schema_version="1.0.0",
        data_label="captured_fixture",
        visit_date=captured_at.astimezone(KOLKATA).date(),
        timezone="Asia/Kolkata",
        captured_at=captured_at,
        request=FixtureRequest.model_validate(CANONICAL_PRESET),
        places=places,
        source_urls=[place.source_url for place in places],
        safe_request_ids=list(evidence.safe_request_ids)[:8] or ["captured-indiranagar-dinner"],
        attribution=_ATTRIBUTION,
        disclaimer=LOCKED_DISCLAIMER,
        expected_structure=ExpectedStructure(
            candidate_count=len(places),
            labeled_synthetic=False,
        ),
    )


def _write(scenario: FixtureScenario, secret: str) -> Path:
    destination = _CAPTURE_ROOT / _SCENARIO_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(scenario.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    _reject_private(encoded, secret)
    destination.write_text(encoded, encoding="utf-8")
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    manifest = {
        "schema_version": "1.0.0",
        "fixture_version": "1.0.0",
        "scenarios": [
            {
                "scenario_id": scenario.fixture_id,
                "path": _SCENARIO_PATH,
                "sha256": digest,
            }
        ],
    }
    (_CAPTURE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return _CAPTURE_ROOT


def _score(
    places: list[NormalizedPlace],
    body: RecommendationRequest,
    settings: Settings,
    now: datetime,
    evidence: CachedEvidence,
    *,
    mode: str,
    label: str,
    fixture_version: str = "none",
    stale: bool = False,
) -> RecommendationResponse:
    captured_at = evidence.captured_at if isinstance(evidence.captured_at, datetime) else now
    provenance = Provenance.model_validate(
        {
            "mode": mode,
            "captured_at": captured_at,
            "generated_at": now,
            "timezone": "Asia/Kolkata",
            "source_count": len(places),
            "source_urls": [place.source_url for place in places],
            "safe_request_ids": list(evidence.safe_request_ids),
            "model_id": settings.hf_model_repo,
            "adapter_id": "none",
            "extraction_schema_version": EXTRACTION_SCHEMA_VERSION,
            "scoring_policy_version": SCORING_POLICY_VERSION,
            "fixture_version": fixture_version,
            "contract_version": CONTRACT_VERSION,
            "stale": stale,
            "data_label": label,
        }
    )
    return score_places(
        places,
        body,
        visit_date=captured_at.astimezone(KOLKATA).date(),
        settings=settings,
        now=now,
        generate=None,
        request_id="capture",
        provenance=provenance,
        notices=[],
    )


def _moment(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {
        "candidate_id": value["candidate_id"],
        "window_id": value["window_id"],
        "restaurant_name": value["restaurant_name"],
        "arrival_start": value["arrival_start"],
        "arrival_end": value["arrival_end"],
        "fit_label": value["fit_label"],
        "confidence_label": value["confidence_label"],
    }


def _identifying(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    return any(marker in path for marker in _IDENTIFYING_PATH)


def _reject_private(document: str, secret: str) -> None:
    if secret and secret in document:
        raise RuntimeError("The capture included the API key.")
    lowered = document.casefold()
    if "api_key" in lowered or '"phone"' in lowered or '"username"' in lowered:
        raise RuntimeError("The capture included a private field.")
    if SYNTHETIC_LABEL in document:
        raise RuntimeError("The capture was labeled synthetic.")


if __name__ == "__main__":
    raise SystemExit(main())
