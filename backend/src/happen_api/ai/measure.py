"""Write the aggregate model-quality report. Raw completions are not stored."""

from __future__ import annotations

import hashlib
import json
import resource
import subprocess
from datetime import datetime
from pathlib import Path

from happen_api.ai.evaluate import score_held_out
from happen_api.ai.extractor import (
    ExtractionError,
    complete_prompt,
    model_file,
    model_load_seconds,
)
from happen_api.ai.planning_dataset import PLANNING_EXAMPLES
from happen_api.ai.planning_proposal import (
    ESSENTIAL_FIELD_MIN,
    REVIEW_PAIR_MIN,
    SCHEMA_PARSE_MIN,
    evaluate_planning,
)
from happen_api.ai.quality import BASELINE_REPORT_PATH, QUALITY_REPORT_PATH
from happen_api.config import get_settings
from happen_api.domain.timing import KOLKATA

_ONE_B = {
    "huggingface_repo": "bartowski/google_gemma-3-1b-it-GGUF",
    "revision": "116f76234503685a98f572982177b11d44ec8ff1",
    "filename": "google_gemma-3-1b-it-Q4_K_M.gguf",
    "sha256": "12bf0fff8815d5f73a3c9b586bd8fee8e7b248c935de70dec367679873d0f29d",
    "size_bytes": 806058496,
}
# 80 percent of the 1c-2g instance (2 GiB), the recorded deployment budget.
_RSS_BUDGET_BYTES = int(2 * 1024 * 1024 * 1024 * 0.80)


def main() -> int:
    """Measure the installed 270M artifact and record whether the 1B file fits."""

    settings = get_settings()
    baseline = json.loads(BASELINE_REPORT_PATH.read_text(encoding="utf-8"))
    planning: dict[str, object] = {
        "measured": False,
        "example_count": len(PLANNING_EXAMPLES),
        "schema_gate": False,
        "essential_gate": False,
    }
    review: dict[str, object] = {"measured": False}
    resources: dict[str, object] = {
        "file_size_bytes": None,
        "load_seconds": None,
        "median_inference_seconds": None,
        "peak_rss_bytes": None,
    }
    path = model_file(settings)
    if path.is_file():
        resources["file_size_bytes"] = path.stat().st_size
        try:
            complete_prompt("Reply with {}", settings=settings)
            loaded = model_load_seconds()
            resources["load_seconds"] = None if loaded is None else round(loaded, 3)
            planning = evaluate_planning(
                list(PLANNING_EXAMPLES),
                lambda prompt: complete_prompt(prompt, settings=settings),
            )
            latencies = planning.pop("inference_seconds", [])
            if isinstance(latencies, list) and latencies:
                ordered = sorted(float(item) for item in latencies)
                resources["median_inference_seconds"] = round(ordered[len(ordered) // 2], 3)
            review = score_held_out(settings)
            review["measured"] = True
            planning["measured"] = True
        except ExtractionError as exc:
            planning["error_code"] = exc.code
        resources["peak_rss_bytes"] = _peak_rss_bytes()
    preserved_parse = float(baseline["parse_rate"])
    preserved_accuracy = float(baseline["dimension_polarity_accuracy"])
    review_parse = float(review.get("parse_rate", preserved_parse))
    review_accuracy = float(review.get("dimension_polarity_accuracy", preserved_accuracy))
    schema_gate = bool(planning.get("schema_gate")) and review_parse >= SCHEMA_PARSE_MIN
    essential_gate = bool(planning.get("essential_gate"))
    review_gate = review_accuracy >= REVIEW_PAIR_MIN and review_parse >= SCHEMA_PARSE_MIN
    claims_enabled = schema_gate and essential_gate and review_gate
    candidate = _candidate_1b()
    measured_sha = settings.model_sha256
    fallback = "deterministic_parser" if not claims_enabled else "measured_model"
    if candidate.get("selected") is True:
        claims_enabled = True
        measured_sha = str(_ONE_B["sha256"])
        fallback = "gemma3_1b_q4"
    report = {
        "report_version": "1",
        "created_on": datetime.now(KOLKATA).date().isoformat(),
        "selected_fallback": fallback,
        "claims_enabled": claims_enabled,
        "measured_sha256": measured_sha,
        "gates": {
            "schema_parse_min": SCHEMA_PARSE_MIN,
            "planning_essential_min": ESSENTIAL_FIELD_MIN,
            "review_dimension_polarity_min": REVIEW_PAIR_MIN,
        },
        "baseline_270m": {
            "source_report": "ml/reports/baseline-270m.json",
            "model_filename": baseline["model_filename"],
            "model_sha256": baseline["model_sha256"],
            "held_out_count": baseline["held_out_count"],
            "parse_rate": preserved_parse,
            "dimension_polarity_accuracy": preserved_accuracy,
            "schema_gate": bool(baseline["ac05_parse"]),
            "review_gate": bool(baseline["ac05_accuracy"]),
            "preserved": True,
        },
        "planning": _planning_public(planning),
        "review": _review_public(review),
        "resources": resources,
        "candidate_1b": candidate,
        "selection_reason": _reason(claims_enabled, planning, review_gate),
    }
    QUALITY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUALITY_REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Fallback {report['selected_fallback']}. "
        f"Claims enabled {claims_enabled}. "
        f"Planning parse {planning.get('parse_rate')}. "
        f"Planning essential {planning.get('essential_field_accuracy')}."
    )
    return 0


def _planning_public(planning: dict[str, object]) -> dict[str, object]:
    public = dict(planning)
    public.pop("inference_seconds", None)
    return public


def _review_public(review: dict[str, object]) -> dict[str, object]:
    if not review.get("measured"):
        return review
    return {
        "measured": True,
        "held_out_count": review["held_out_count"],
        "parsed_count": review["parsed_count"],
        "parse_rate": review["parse_rate"],
        "correct_pairs": review["correct_pairs"],
        "pair_count": review["pair_count"],
        "dimension_polarity_accuracy": review["dimension_polarity_accuracy"],
        "schema_gate": review["schema_gate"],
        "review_gate": review["review_gate"],
        "examples": review["examples"],
    }


def _candidate_1b() -> dict[str, object]:
    cache = Path(__file__).resolve().parents[4] / "ml" / ".cache" / _ONE_B["filename"]
    record: dict[str, object] = {
        **_ONE_B,
        "public_without_token": True,
        "selected": False,
        "evaluated": False,
        "fits_memory_budget": None,
        "reason": (
            "The file is public at the pinned revision and its LFS checksum is "
            f"{_ONE_B['sha256']}. It was not selected."
        ),
    }
    if not cache.is_file():
        record["reason"] = (
            "The pinned public Gemma 3 1B Q4_K_M file can be downloaded without "
            "a Hugging Face token, but it is not in the local cache, so its quality was not measured. "
            "The deterministic parser remains the fallback."
        )
        return record
    digest = _sha256(cache)
    size = cache.stat().st_size
    record["local_sha256_matches"] = digest == _ONE_B["sha256"] and size == _ONE_B["size_bytes"]
    if record["local_sha256_matches"] is not True:
        record["reason"] = (
            "A local file uses the pinned 1B filename, but its checksum or size does not "
            "match the public revision. It was not evaluated."
        )
        return record
    probed = _probe_candidate(cache.name, str(_ONE_B["sha256"]))
    record["load_seconds"] = probed.get("load_seconds")
    record["peak_rss_bytes"] = probed.get("peak_rss_bytes")
    peak = probed.get("peak_rss_bytes")
    fits = isinstance(peak, int) and peak <= _RSS_BUDGET_BYTES
    record["fits_memory_budget"] = fits
    if probed.get("error"):
        record["reason"] = (
            "The pinned 1B file verifies without a Hugging Face token, but loading it for a memory "
            "measurement failed. It was not selected."
        )
        return record
    if not fits:
        record["reason"] = (
            "The pinned Gemma 3 1B Q4_K_M file verifies without a Hugging Face token. "
            f"Peak RSS was {peak} bytes, above the {_RSS_BUDGET_BYTES} byte budget "
            "for the 1c-2g plan. Quality was not used for selection."
        )
        return record
    quality = _evaluate_candidate(cache.name, str(_ONE_B["sha256"]))
    evaluated_peak = quality.get("peak_rss_bytes")
    if isinstance(evaluated_peak, int) and (not isinstance(peak, int) or evaluated_peak > peak):
        peak = evaluated_peak
        record["peak_rss_bytes"] = evaluated_peak
        record["fits_memory_budget"] = peak <= _RSS_BUDGET_BYTES
    record["evaluated"] = quality.get("evaluated") is True
    if quality.get("planning") is not None:
        record["planning"] = quality["planning"]
    if quality.get("review") is not None:
        record["review"] = quality["review"]
    passed = (
        record["fits_memory_budget"] is True
        and quality.get("schema_gate") is True
        and quality.get("essential_gate") is True
        and quality.get("review_gate") is True
    )
    record["selected"] = passed
    if passed:
        record["reason"] = "The pinned 1B file fits the memory budget and passed the quality gates."
    elif record["fits_memory_budget"] is not True:
        record["reason"] = (
            "The pinned Gemma 3 1B Q4_K_M file verifies without a Hugging Face token. "
            f"Peak RSS was {peak} bytes, above the {_RSS_BUDGET_BYTES} byte budget "
            "for the 1c-2g plan. It was not selected."
        )
    else:
        record["reason"] = (
            "The pinned 1B file verifies without a Hugging Face token and fits the memory budget, "
            "but it missed a quality gate. The deterministic parser remains the fallback."
        )
    return record


def _reason(claims_enabled: bool, planning: dict[str, object], review_gate: bool) -> str:
    if claims_enabled:
        return "The measured artifact passed the planning and review gates."
    if planning.get("measured") is not True:
        return (
            "The preserved 270M review baseline misses the review gate. "
            "Planning quality was not measured in this process, so model claims stay off "
            "and the deterministic parser remains usable."
        )
    return (
        "The measured model missed a selection gate. "
        f"Review gate passed: {review_gate}. "
        "Model claims stay off. The deterministic parser remains usable."
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _probe_candidate(filename: str, digest: str) -> dict[str, object]:
    script = """
import json, os, resource, sys
os.environ["MODEL_FILENAME"] = sys.argv[1]
os.environ["MODEL_SHA256"] = sys.argv[2]
from happen_api.ai.extractor import ExtractionError, complete_prompt, model_load_seconds
from happen_api.config import get_settings
settings = get_settings()
try:
    complete_prompt("Reply with {}", settings=settings)
except ExtractionError as exc:
    print(json.dumps({"error": exc.code}))
    raise SystemExit(0)
print(json.dumps({
    "load_seconds": None if model_load_seconds() is None else round(model_load_seconds(), 3),
    "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
}))
"""
    return _run_candidate(script, filename, digest, timeout=180)


def _evaluate_candidate(filename: str, digest: str) -> dict[str, object]:
    script = """
import json, os, resource, sys
os.environ["MODEL_FILENAME"] = sys.argv[1]
os.environ["MODEL_SHA256"] = sys.argv[2]
from happen_api.ai.evaluate import score_held_out
from happen_api.ai.extractor import complete_prompt
from happen_api.ai.planning_dataset import PLANNING_EXAMPLES
from happen_api.ai.planning_proposal import evaluate_planning
from happen_api.config import get_settings
settings = get_settings()
planning = evaluate_planning(
    list(PLANNING_EXAMPLES),
    lambda prompt: complete_prompt(prompt, settings=settings),
)
planning.pop("inference_seconds", None)
review = score_held_out(settings)
print(json.dumps({
    "evaluated": True,
    "schema_gate": bool(planning["schema_gate"]) and bool(review["schema_gate"]),
    "essential_gate": bool(planning["essential_gate"]),
    "review_gate": bool(review["review_gate"]) and bool(review["schema_gate"]),
    "planning": planning,
    "review": {
        "measured": True,
        "held_out_count": review["held_out_count"],
        "parsed_count": review["parsed_count"],
        "parse_rate": review["parse_rate"],
        "correct_pairs": review["correct_pairs"],
        "pair_count": review["pair_count"],
        "dimension_polarity_accuracy": review["dimension_polarity_accuracy"],
        "schema_gate": review["schema_gate"],
        "review_gate": review["review_gate"],
    },
    "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
}))
"""
    return _run_candidate(script, filename, digest, timeout=3600)


def _run_candidate(script: str, filename: str, digest: str, *, timeout: int) -> dict[str, object]:
    backend = Path(__file__).resolve().parents[3]
    try:
        completed = subprocess.run(
            ["uv", "run", "python", "-c", script, filename, digest],
            cwd=backend,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"error": "probe_failed"}
    if completed.returncode != 0 or not completed.stdout.strip():
        return {"error": "probe_failed"}
    try:
        loaded = json.loads(completed.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError:
        return {"error": "probe_failed"}
    return loaded if isinstance(loaded, dict) else {"error": "probe_failed"}


def _peak_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # Linux reports ru_maxrss in kilobytes.
    return int(usage.ru_maxrss) * 1024


if __name__ == "__main__":
    raise SystemExit(main())
