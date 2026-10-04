"""Process-local admission control and a bounded plan cache.

One small process keeps a short hit list per caller and at most a few billed
plans at once. Cached places are normalized records, keyed by a hash.
"""

from __future__ import annotations

import threading
import time

from cachetools import TTLCache

from happen_api.planning.discovery import DiscoveredPlace

_CALLERS = 256
_ACTIVE_BILLED = 3
_CACHE_MAX = 32
_CACHE_TTL_SECONDS = 15 * 60


class PlanningThrottle:
    """In-memory request throttle. It does not store prompts or provider payloads."""

    def __init__(self) -> None:
        self._hits: TTLCache[str, list[float]] = TTLCache(maxsize=_CALLERS, ttl=3600)
        self._active = 0
        self._lock = threading.Lock()

    def start(
        self,
        caller: str,
        *,
        limit: int,
        window_seconds: int,
        billed: bool,
        now: float | None = None,
    ) -> int | None:
        """Reserve one request. Return seconds to wait when the caller must stop."""

        moment = time.monotonic() if now is None else now
        with self._lock:
            recent = [
                stamp for stamp in self._hits.get(caller, []) if moment - stamp < window_seconds
            ]
            if len(recent) >= limit:
                wait = window_seconds - (moment - min(recent))
                return max(1, int(wait))
            if billed and self._active >= _ACTIVE_BILLED:
                return 1
            recent.append(moment)
            self._hits[caller] = recent
            if billed:
                self._active += 1
            return None

    def finish(self, billed: bool) -> None:
        """Release a billed reservation. An unbilled request has nothing to release."""

        if not billed:
            return
        with self._lock:
            self._active = max(0, self._active - 1)


class PlanCache:
    """Bounded reuse of normalized places. Raw provider documents are not stored."""

    def __init__(self, *, maxsize: int = _CACHE_MAX, ttl: int = _CACHE_TTL_SECONDS) -> None:
        self._items: TTLCache[str, list[DiscoveredPlace]] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = threading.Lock()

    def get(self, key: str) -> list[DiscoveredPlace] | None:
        """Return a copy of cached places, or None when the key is unsafe or missing."""

        if not _safe_key(key):
            return None
        with self._lock:
            found = self._items.get(key)
        if found is None:
            return None
        return [place.model_copy(deep=True) for place in found]

    def put(self, key: str, places: list[DiscoveredPlace]) -> None:
        """Store a copy of places when the key is a hash and the list is not empty."""

        if not places or not _safe_key(key):
            return
        stored = [place.model_copy(deep=True) for place in places]
        with self._lock:
            self._items[key] = stored

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


def _safe_key(key: str) -> bool:
    return len(key) == 64 and all(character in "0123456789abcdef" for character in key)
