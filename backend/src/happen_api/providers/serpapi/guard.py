"""Process-local SerpApi circuit and search budget.

Authentication and quota failures disable live mode. Transient failures open
the circuit. The search budget is an in-process count, not the provider balance.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from cachetools import TTLCache

_WINDOW_SECONDS = 300
_OPEN_SECONDS = 120
_FAILURES_TO_OPEN = 3
_SNAPSHOT_TTL_SECONDS = 15 * 60
_SNAPSHOT_MAX = 32


@dataclass
class CachedEvidence:
    """Normalized live evidence reused until the snapshot cache expires."""

    places: list[object]
    safe_request_ids: list[str]
    source_urls: list[str]
    captured_at: object
    reason_codes: list[str] = field(default_factory=list)


@dataclass
class LiveGuard:
    """In-process protection for live SerpApi calls."""

    budget: int
    spent: int = 0
    disabled_code: str | None = None
    consecutive_failures: int = 0
    failure_times: list[float] = field(default_factory=list)
    open_until: float | None = None
    snapshots: TTLCache[str, CachedEvidence] = field(
        default_factory=lambda: TTLCache(maxsize=_SNAPSHOT_MAX, ttl=_SNAPSHOT_TTL_SECONDS)
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def blocked(self, now: float) -> str | None:
        """Return a public failure code when a new live call must not start."""

        with self._lock:
            if self.disabled_code == "AUTHENTICATION_FAILED":
                return "LIVE_MODE_DISABLED"
            if self.disabled_code == "QUOTA_EXHAUSTED":
                return "SERPAPI_QUOTA_EXHAUSTED"
            if self.spent >= self.budget:
                return "SERPAPI_QUOTA_EXHAUSTED"
            if self.open_until is not None and now < self.open_until:
                return "SERPAPI_UNAVAILABLE"
        return None

    def remaining(self) -> int:
        """Return how many search attempts this process may still record."""

        with self._lock:
            return max(self.budget - self.spent, 0)

    def spend(self, count: int) -> None:
        """Record attempts that may have consumed provider credit."""

        if count <= 0:
            return
        with self._lock:
            self.spent += count

    def note_success(self) -> None:
        """Close the transient circuit after a usable provider response."""

        with self._lock:
            self.consecutive_failures = 0
            self.failure_times.clear()
            self.open_until = None

    def note_failure(self, code: str, now: float) -> None:
        """Disable live mode or open the circuit from a provider failure code."""

        with self._lock:
            if code == "AUTHENTICATION_FAILED":
                self.disabled_code = code
                return
            if code == "QUOTA_EXHAUSTED":
                self.disabled_code = code
                return
            if code != "TRANSIENT_DEPENDENCY":
                return
            self.failure_times = [
                stamp for stamp in self.failure_times if now - stamp <= _WINDOW_SECONDS
            ]
            self.failure_times.append(now)
            self.consecutive_failures += 1
            if (
                self.consecutive_failures >= _FAILURES_TO_OPEN
                and len(self.failure_times) >= _FAILURES_TO_OPEN
            ):
                self.open_until = now + _OPEN_SECONDS
                self.consecutive_failures = 0

    def get_snapshot(self, key: str) -> CachedEvidence | None:
        """Return cached normalized evidence, if it is still fresh."""

        with self._lock:
            return self.snapshots.get(key)

    def save_snapshot(self, key: str, evidence: CachedEvidence) -> None:
        """Store normalized evidence. Raw provider documents are not cached."""

        with self._lock:
            self.snapshots[key] = evidence
