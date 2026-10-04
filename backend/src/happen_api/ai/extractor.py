"""Run one local Gemma extraction and validate it before scoring can see it."""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable
from pathlib import Path

from happen_api.ai.prompt import excerpt_is_delimited, extraction_prompt, retry_prompt
from happen_api.ai.validation import ValidatedExtraction, validate_extraction
from happen_api.config import Settings, get_settings
from happen_api.domain.models import ReviewExcerpt

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LOCK = threading.Lock()
_MODEL: object | None = None


class ExtractionError(Exception):
    """The local model could not run. The message omits paths and secrets."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def model_file(settings: Settings) -> Path:
    """Return the pinned GGUF path without requiring the file to exist yet."""

    return _REPO_ROOT / "ml" / ".cache" / settings.model_filename


def extract_excerpt(
    excerpt: ReviewExcerpt,
    *,
    settings: Settings | None = None,
    generate: Callable[[str], str] | None = None,
) -> ValidatedExtraction:
    """Extract one excerpt, with one retry only when the first reply is malformed."""

    if not excerpt_is_delimited(excerpt):
        return validate_extraction("", excerpt, attempt=1)
    producer = generate or _model_generate(settings or get_settings())
    first = validate_extraction(producer(extraction_prompt(excerpt)), excerpt, attempt=1)
    if not first.malformed:
        return first
    return validate_extraction(producer(retry_prompt(excerpt)), excerpt, attempt=2)


def _model_generate(settings: Settings) -> Callable[[str], str]:
    def generate(prompt: str) -> str:
        with _LOCK:
            model = _load_model(settings)
            response = model.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=384,
                repeat_penalty=1.0,
                seed=0,
            )
        return _message_text(response)

    return generate


def _load_model(settings: Settings) -> object:
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    path = model_file(settings)
    if not path.is_file():
        raise ExtractionError("MODEL_UNAVAILABLE", "The evidence model is not installed.")
    if _sha256(path) != settings.model_sha256:
        raise ExtractionError("MODEL_UNAVAILABLE", "The evidence model checksum does not match.")
    try:
        from llama_cpp import Llama

        _MODEL = Llama(
            model_path=str(path),
            n_ctx=2048,
            n_threads=os.cpu_count() or 1,
            n_gpu_layers=0,
            verbose=False,
            seed=0,
        )
    except (OSError, RuntimeError, ValueError):
        raise ExtractionError(
            "MODEL_UNAVAILABLE", "The evidence model could not be loaded."
        ) from None
    return _MODEL


def _message_text(response: object) -> str:
    if not isinstance(response, dict):
        return ""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        return "".join(parts)
    return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
