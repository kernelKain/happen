"""Parse Gemma output and keep only exact evidence spans."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from happen_api.ai.prompt import EXTRACTION_SCHEMA_VERSION
from happen_api.domain.models import (
    AcceptedSignal,
    Dimension,
    ExtractionConfidence,
    Polarity,
    ReviewExcerpt,
    TemporalHint,
)
from happen_api.domain.timing import _parse_clock

_CLOCK_TOKEN = re.compile(r"\d{1,2}(?::\d{2})?\s*(?:am|pm)?", re.IGNORECASE)


class EvidenceSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: Dimension
    polarity: Polarity
    temporal_hint: TemporalHint
    temporal_span: str | None = None
    quoted_span: str = Field(min_length=1)
    confidence: ExtractionConfidence


class _RawExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"]
    excerpt_id: str = Field(min_length=1, max_length=80)
    signals: list[EvidenceSignal] = Field(default_factory=list, max_length=6)
    unknown_dimensions: list[Dimension] = Field(default_factory=list)


class ValidatedExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    excerpt_id: str
    signals: list[EvidenceSignal]
    unknown_dimensions: list[Dimension]
    parse_attempt: int = Field(ge=1, le=2)
    validation_status: Literal["accepted", "partially_accepted", "rejected"]
    rejected_signal_count: int = Field(ge=0)
    malformed: bool


def validate_extraction(
    raw_text: str,
    excerpt: ReviewExcerpt,
    *,
    attempt: int,
) -> ValidatedExtraction:
    """Accept exact spans, drop invalid signals, and reject a malformed document."""

    parsed_result = _parse(raw_text)
    if parsed_result is None:
        return _rejected(excerpt.excerpt_id, attempt)
    parsed, dropped = parsed_result
    if parsed.excerpt_id != excerpt.excerpt_id:
        return _rejected(excerpt.excerpt_id, attempt)
    if parsed.schema_version != EXTRACTION_SCHEMA_VERSION:
        return _rejected(excerpt.excerpt_id, attempt)
    kept, span_drops = _keep_exact_signals(parsed.signals, excerpt.text)
    dropped += span_drops
    signaled = {signal.dimension for signal in kept}
    unknown = [dimension for dimension in parsed.unknown_dimensions if dimension not in signaled]
    overlap_removed = len(unknown) != len(parsed.unknown_dimensions)
    missing = [
        dimension
        for dimension in Dimension
        if dimension not in signaled and dimension not in unknown
    ]
    unknown.extend(missing)
    ordered_unknown = [dimension for dimension in Dimension if dimension in set(unknown)]
    if dropped or overlap_removed or missing:
        status = "partially_accepted"
    else:
        status = "accepted"
    return ValidatedExtraction(
        schema_version=parsed.schema_version,
        excerpt_id=excerpt.excerpt_id,
        signals=kept,
        unknown_dimensions=ordered_unknown,
        parse_attempt=attempt,
        validation_status=status,
        rejected_signal_count=dropped,
        malformed=False,
    )


def accepted_scoring_signals(
    result: ValidatedExtraction,
    excerpt: ReviewExcerpt,
) -> list[AcceptedSignal]:
    """Return scoring signals only after validation. Rejected output contributes none."""

    if result.malformed or result.validation_status == "rejected":
        return []
    return [
        AcceptedSignal(
            signal_id=f"{excerpt.excerpt_id}:{index}",
            candidate_id=excerpt.candidate_id,
            dimension=signal.dimension,
            polarity=signal.polarity,
            temporal_hint=signal.temporal_hint,
            temporal_span=signal.temporal_span,
            confidence=signal.confidence,
            published_at=excerpt.published_at,
        )
        for index, signal in enumerate(result.signals, start=1)
    ]


def _parse(raw_text: str) -> tuple[_RawExtraction, int] | None:
    text = _strip_fence(raw_text.strip())
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") == 1:
        payload["schema_version"] = "1"
    signals = payload.get("signals", None)
    if not isinstance(signals, list) or len(signals) > 6:
        return None
    parsed_signals: list[EvidenceSignal] = []
    dropped = 0
    for item in signals:
        try:
            parsed_signals.append(EvidenceSignal.model_validate(item))
        except ValidationError:
            dropped += 1
    payload["signals"] = []
    try:
        document = _RawExtraction.model_validate(payload)
    except ValidationError:
        return None
    document.signals.extend(parsed_signals)
    return document, dropped


def _strip_fence(text: str) -> str:
    """Drop a leading Markdown fence and any explanation after the closing fence."""

    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) < 2:
        return text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "```":
            return "\n".join(lines[1:index]).strip()
    return text


def _keep_exact_signals(
    signals: list[EvidenceSignal],
    excerpt_text: str,
) -> tuple[list[EvidenceSignal], int]:
    excerpt = _normalize(excerpt_text)
    kept: list[EvidenceSignal] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    dropped = 0
    for signal in signals:
        quote = _normalize(signal.quoted_span)
        temporal = _normalize(signal.temporal_span) if signal.temporal_span else None
        identity = (
            signal.dimension.value,
            signal.polarity.value,
            signal.temporal_hint.value,
            temporal or "",
            quote,
            signal.confidence.value,
        )
        if identity in seen or not _span_is_exact(signal, excerpt, quote, temporal):
            dropped += 1
            continue
        seen.add(identity)
        kept.append(signal)
    return kept, dropped


def _span_is_exact(
    signal: EvidenceSignal,
    excerpt: str,
    quote: str,
    temporal: str | None,
) -> bool:
    if not quote.strip() or quote not in excerpt:
        return False
    if temporal is not None and temporal not in excerpt:
        return False
    if signal.temporal_hint is TemporalHint.specific_time:
        return temporal is not None and _contains_clock(temporal)
    return True


def _contains_clock(span: str) -> bool:
    return any(_parse_clock(match.group(0)) is not None for match in _CLOCK_TOKEN.finditer(span))


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _rejected(excerpt_id: str, attempt: int) -> ValidatedExtraction:
    return ValidatedExtraction(
        schema_version=EXTRACTION_SCHEMA_VERSION,
        excerpt_id=excerpt_id,
        signals=[],
        unknown_dimensions=list(Dimension),
        parse_attempt=attempt,
        validation_status="rejected",
        rejected_signal_count=0,
        malformed=True,
    )
