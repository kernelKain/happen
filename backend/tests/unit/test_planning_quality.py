"""Planning quality gate. Inference is mocked and no GGUF is required."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from happen_api.ai.planning_dataset import PLANNING_EXAMPLES
from happen_api.ai.planning_proposal import (
    evaluate_planning,
    parse_planning_proposal,
    propose_preferences,
)
from happen_api.ai.quality import BASELINE_REPORT_PATH, QUALITY_REPORT_PATH, model_claims_enabled
from happen_api.config import Settings
from happen_api.planning import FixedClock, interpret


def test_planning_dataset_covers_the_required_cases() -> None:
    """The authored set spans countries, money, dates, gaps, ambiguity, and attacks."""

    tags = {tag for example in PLANNING_EXAMPLES for tag in example.tags}
    assert {"india", "uk", "us", "japan", "france", "korea"} <= tags
    assert {"jpy", "inr", "gbp", "usd", "eur"} <= tags
    assert {"two-intent", "ambiguity", "missing", "adversarial", "explicit-date"} <= tags
    assert len(PLANNING_EXAMPLES) >= 24


def test_gold_matches_the_deterministic_parser() -> None:
    """The dataset labels are the deterministic reading, including unresolved dates."""

    clock = FixedClock(datetime(2026, 10, 4, 15, 0, tzinfo=UTC))
    for example in PLANNING_EXAMPLES:
        brief = interpret(example.prompt, clock).brief
        intent = brief.intents[0].kind.value if brief.intents else None
        start = None if brief.local_start is None else brief.local_start.strftime("%H:%M")
        local_date = None if brief.local_date is None else brief.local_date.isoformat()
        assert brief.destination_text == example.destination_text
        assert local_date == example.local_date
        assert start == example.local_start
        assert intent == example.primary_intent


def test_strict_schema_rejects_prose_and_a_winning_place() -> None:
    """A proposal that names a winner is not a valid preference object."""

    valid = (
        '{"schema_version":"1","destination_text":"Kyoto","local_date":null,'
        '"local_start":null,"primary_intent":"dinner","secondary_intent":null,'
        '"preferences":[]}'
    )
    assert parse_planning_proposal("Here is the plan: {}") is None
    assert parse_planning_proposal(f"```json\n{valid}\n```") is not None
    assert (
        parse_planning_proposal(
            '{"schema_version":"1","destination_text":"Kyoto","local_date":null,'
            '"local_start":null,"primary_intent":"dinner","secondary_intent":null,'
            '"preferences":[],"winner":"Kyoto Grill"}'
        )
        is None
    )


def test_mocked_generator_is_scored_without_a_model_file() -> None:
    """Parse rate and essential-field accuracy come from the injected generator."""

    perfect = evaluate_planning(list(PLANNING_EXAMPLES), _perfect)
    assert perfect["parse_rate"] == 1
    assert perfect["essential_field_accuracy"] == 1
    assert perfect["schema_gate"] is True
    assert perfect["essential_gate"] is True

    failed = evaluate_planning(list(PLANNING_EXAMPLES), lambda _prompt: "not json")
    assert failed["parse_rate"] == 0
    assert failed["essential_field_accuracy"] == 0
    assert failed["schema_gate"] is False


def test_failed_gate_does_not_call_the_model(settings: Settings) -> None:
    """Model claims stay off, and the proposer does not ask the generator."""

    def explode(_prompt: str) -> str:
        raise AssertionError("the model should not be called")

    assert model_claims_enabled(settings) is False
    assert (
        propose_preferences("Dinner in Kyoto on 2026-10-05 at 7pm", explode, settings=settings)
        is None
    )


def test_quality_report_keeps_the_270m_baseline_and_disables_claims() -> None:
    """The preserved review baseline remains a failed gate."""

    baseline = json.loads(BASELINE_REPORT_PATH.read_text(encoding="utf-8"))
    quality = json.loads(QUALITY_REPORT_PATH.read_text(encoding="utf-8"))
    assert baseline["parse_rate"] == 0.0667
    assert baseline["dimension_polarity_accuracy"] == 0.0444
    assert baseline["selected_artifact"] == "untuned_270m"
    assert quality["baseline_270m"]["parse_rate"] == baseline["parse_rate"]
    assert (
        quality["baseline_270m"]["dimension_polarity_accuracy"]
        == baseline["dimension_polarity_accuracy"]
    )
    assert quality["claims_enabled"] is False
    assert quality["selected_fallback"] == "deterministic_parser"
    assert quality["candidate_1b"]["selected"] is False
    rendered = json.dumps(quality)
    assert "api_key" not in rendered
    assert "hf_" not in rendered.lower()


def _perfect(prompt: str) -> str:
    for example in PLANNING_EXAMPLES:
        if example.prompt in prompt:
            return json.dumps(
                {
                    "schema_version": "1",
                    "destination_text": example.destination_text,
                    "local_date": example.local_date,
                    "local_start": example.local_start,
                    "primary_intent": example.primary_intent,
                    "secondary_intent": None,
                    "preferences": [],
                }
            )
    return "not json"
