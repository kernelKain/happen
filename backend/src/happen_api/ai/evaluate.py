"""Measure the installed Gemma artifact on the held-out extraction set.

The script uses the same prompt, validator, and sampling as a recommendation.
It writes a report and does not change the selected model.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from happen_api.ai.dataset import EXTRACTION_DIR, held_out_examples, pair_correct, write_jsonl
from happen_api.ai.extractor import (
    MAX_TOKENS,
    REPEAT_PENALTY,
    SEED,
    TEMPERATURE,
    ExtractionError,
    extract_excerpt,
)
from happen_api.ai.prompt import PROMPT_VERSION
from happen_api.config import get_settings
from happen_api.domain.models import Dimension, ReviewExcerpt
from happen_api.domain.timing import KOLKATA

_REPORT_PATH = EXTRACTION_DIR.parent / "reports" / "baseline-270m.json"


def main() -> int:
    """Run the held-out baseline and print the parse rate and accuracy."""

    settings = get_settings()
    train_path, held_path = write_jsonl()
    examples = held_out_examples()
    correct = 0
    parsed = 0
    rows: list[dict[str, object]] = []
    try:
        for example in examples:
            result = extract_excerpt(_excerpt(example.example_id, example.text), settings=settings)
            predicted = (
                {}
                if result.malformed
                else {signal.dimension: signal.polarity for signal in result.signals}
            )
            got = 0 if result.malformed else pair_correct(example, predicted)
            correct += got
            parsed += int(not result.malformed)
            rows.append(
                {
                    "example_id": example.example_id,
                    "kind": example.kind,
                    "malformed": result.malformed,
                    "parse_attempt": result.parse_attempt,
                    "correct_pairs": got,
                }
            )
    except ExtractionError as exc:
        print(exc.code)
        return 1
    pair_count = len(examples) * len(Dimension)
    parse_rate = parsed / len(examples)
    accuracy = correct / pair_count
    report = {
        "report_version": "1",
        "created_on": datetime.now(KOLKATA).date().isoformat(),
        "model_id": settings.hf_model_repo,
        "model_revision": settings.hf_model_revision,
        "model_filename": settings.model_filename,
        "model_sha256": settings.model_sha256,
        "prompt_version": PROMPT_VERSION,
        "sampling": {
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "repeat_penalty": REPEAT_PENALTY,
            "seed": SEED,
        },
        "train_sha256": _sha256(train_path),
        "held_out_sha256": _sha256(held_path),
        "held_out_count": len(examples),
        "parsed_count": parsed,
        "parse_rate": round(parse_rate, 4),
        "correct_pairs": correct,
        "pair_count": pair_count,
        "dimension_polarity_accuracy": round(accuracy, 4),
        "ac05_parse": parse_rate >= 0.95,
        "ac05_accuracy": accuracy >= 0.80,
        "selected_artifact": "untuned_270m",
        "selection_reason": (
            "No tuned adapter has been measured. The untuned 270M artifact stays "
            "selected until a held-out run improves accuracy by at least five "
            "percentage points without increasing invalid outputs."
        ),
        "examples": rows,
    }
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Held-out {len(examples)}. Parse rate {parse_rate:.1%}. "
        f"Dimension-plus-polarity accuracy {accuracy:.1%}. "
        f"Selected artifact untuned_270m."
    )
    return 0


def _excerpt(excerpt_id: str, text: str) -> ReviewExcerpt:
    return ReviewExcerpt(
        excerpt_id=excerpt_id,
        candidate_id="evaluation",
        text=text,
        published_at=None,
        captured_at=datetime(2026, 10, 4, 12, 0, tzinfo=KOLKATA),
        source_url="https://example.com/happen/extraction-evaluation",
        language="en",
        truncated=False,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
