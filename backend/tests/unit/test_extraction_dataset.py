"""The extraction dataset stays disjoint, labeled, and large enough to measure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from happen_api.ai.dataset import (
    _HARD_KINDS,
    EXTRACTION_DIR,
    held_out_examples,
    pair_correct,
    training_examples,
)
from happen_api.domain.models import Dimension, Polarity

_REPORT = EXTRACTION_DIR.parent / "reports" / "baseline-270m.json"


def test_splits_are_large_enough_and_do_not_share_text() -> None:
    """Verify training and held-out text stay separate and the held-out set is hard enough."""

    training = training_examples()
    held_out = held_out_examples()
    train_text = [example.text for example in training]
    held_text = [example.text for example in held_out]

    assert 80 <= len(training) <= 150
    assert len(held_out) >= 24
    assert len(set(train_text)) == len(train_text)
    assert len(set(held_text)) == len(held_text)
    for held in held_text:
        assert all(held not in train for train in train_text)
    hard = [example for example in held_out if example.kind in _HARD_KINDS]
    assert len(hard) / len(held_out) >= 0.20


def test_unknown_gold_and_matching_polarity_are_scored_apart() -> None:
    """Verify accuracy credits a gold polarity and withholds credit for an invented one."""

    example = held_out_examples()[0]
    gold = {signal.dimension: signal.polarity for signal in example.signals}
    assert pair_correct(example, gold) == len(Dimension)
    invented = dict(gold)
    invented[Dimension.seating] = Polarity.positive
    assert pair_correct(example, invented) == len(Dimension) - 1


def test_baseline_report_uses_the_checked_in_dataset() -> None:
    """Verify the recorded baseline cites this dataset and does not hide a failed gate."""

    report = json.loads(_REPORT.read_text(encoding="utf-8"))
    assert report["held_out_count"] >= 24
    assert report["selected_artifact"] == "untuned_270m"
    assert report["ac05_parse"] is (report["parse_rate"] >= 0.95)
    assert report["ac05_accuracy"] is (report["dimension_polarity_accuracy"] >= 0.80)
    assert report["ac05_parse"] is False
    assert report["ac05_accuracy"] is False
    assert _sha256(EXTRACTION_DIR / "train.jsonl") == report["train_sha256"]
    assert _sha256(EXTRACTION_DIR / "held_out.jsonl") == report["held_out_sha256"]
    assert len(_lines(EXTRACTION_DIR / "train.jsonl")) == len(training_examples())
    assert len(_lines(EXTRACTION_DIR / "held_out.jsonl")) == len(held_out_examples())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
