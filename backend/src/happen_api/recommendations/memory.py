"""In-process idempotency, result reuse, and recommendation rate limits."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from cachetools import TTLCache

from happen_api.recommendations.contracts import RecommendationResponse

_RESULT_TTL_SECONDS = 10 * 60
_RESULT_MAX = 64
_IDEMPOTENCY_TTL_SECONDS = 10 * 60
_IDEMPOTENCY_MAX = 128
_MAX_ACTIVE = 3
_GUARD = threading.Lock()


class MemoryError(Exception):
    """A duplicate or busy recommendation request. The message is public."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        next_action: str,
        *,
        retryable: bool,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.next_action = next_action
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


@dataclass
class _Idempotent:
    payload_hash: str
    response: RecommendationResponse


class RecommendationMemory:
    """Bounded process memory. Errors are not stored as successful results."""

    def __init__(self) -> None:
        self._results: TTLCache[tuple[str, ...], RecommendationResponse] = TTLCache(
            maxsize=_RESULT_MAX,
            ttl=_RESULT_TTL_SECONDS,
        )
        self._idempotency: TTLCache[str, _Idempotent] = TTLCache(
            maxsize=_IDEMPOTENCY_MAX,
            ttl=_IDEMPOTENCY_TTL_SECONDS,
        )
        self._inflight: set[str] = set()
        self._active = 0
        self._hits: dict[str, list[float]] = {}

    def begin(
        self,
        key: str,
        payload_hash: str,
        *,
        client: str,
        limit: int,
        window_seconds: int,
    ) -> RecommendationResponse | None:
        """Reserve a new submission, or return the completed response for the same payload."""

        now = time.monotonic()
        with _GUARD:
            stored = self._idempotency.get(key)
            if stored is not None:
                if stored.payload_hash != payload_hash:
                    raise MemoryError(
                        409,
                        "IDEMPOTENCY_CONFLICT",
                        "This idempotency key was already used for a different request.",
                        "Submit again with a new idempotency key.",
                        retryable=False,
                    )
                return stored.response
            if key in self._inflight:
                raise MemoryError(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "That submission is already running.",
                    "Wait for the original submission to finish.",
                    retryable=True,
                )
            retry_after = self._retry_after(
                client, limit=limit, window_seconds=window_seconds, now=now
            )
            if retry_after is not None:
                raise MemoryError(
                    429,
                    "RATE_LIMITED",
                    "Happen is handling too many recommendation requests.",
                    "Wait and try again.",
                    retryable=True,
                    retry_after_seconds=retry_after,
                )
            if self._active >= _MAX_ACTIVE:
                raise MemoryError(
                    429,
                    "RATE_LIMITED",
                    "Happen is handling another request.",
                    "Wait and try again.",
                    retryable=True,
                    retry_after_seconds=1,
                )
            self._inflight.add(key)
            self._active += 1
            self._hits.setdefault(client, []).append(now)
        return None

    def finish(self, key: str, payload_hash: str, response: RecommendationResponse) -> None:
        """Store a completed response and release the in-flight slot."""

        with _GUARD:
            self._release(key)
            self._idempotency[key] = _Idempotent(payload_hash=payload_hash, response=response)

    def abort(self, key: str) -> None:
        """Release an in-flight slot when the recommendation does not succeed."""

        with _GUARD:
            self._release(key)

    def get_result(self, key: tuple[str, ...]) -> RecommendationResponse | None:
        """Return a completed recommendation for the same evidence versions."""

        with _GUARD:
            return self._results.get(key)

    def save_result(self, key: tuple[str, ...], response: RecommendationResponse) -> None:
        """Remember a successful recommendation until the cache expires."""

        with _GUARD:
            self._results[key] = response

    def _release(self, key: str) -> None:
        if key in self._inflight:
            self._inflight.remove(key)
            self._active = max(0, self._active - 1)

    def _retry_after(
        self,
        client: str,
        *,
        limit: int,
        window_seconds: int,
        now: float,
    ) -> int | None:
        recent = [stamp for stamp in self._hits.get(client, []) if now - stamp < window_seconds]
        if recent:
            self._hits[client] = recent
        else:
            self._hits.pop(client, None)
        if len(recent) < limit:
            return None
        oldest = min(recent)
        return max(1, int(window_seconds - (now - oldest)) + 1)
