"""Process-local admission control, plan allowances, and a bounded plan cache.

One small process keeps a short hit list per caller, at most a few billed plans
at once, and a bounded allowance per submitted plan. The cache stores the
normalized candidate pool, keyed by a hash.

The allowance store holds only an opaque random token and two integers. It never
holds a prompt, a destination, a credential, or a provider payload. It is
process-local: a restart clears it, and more than one process would not share
it. That limitation is stated honestly rather than hidden.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

from cachetools import TTLCache

from happen_api.planning.discovery import CandidatePool
from happen_api.providers.serpapi.client import SerpApiFailure

_CALLERS = 256
_ACTIVE_BILLED = 3
_CACHE_MAX = 32
_CACHE_TTL_SECONDS = 15 * 60
_TOKEN_BYTES = 32
_ALLOWANCE_MAX = 512
_ALLOWANCE_TTL_SECONDS = 30 * 60
PLAN_BILLED_REQUEST_LIMIT = 8


@dataclass
class Allowance:
    """One submitted plan's remaining budget.

    `spent` counts requests that were actually sent. `reserved` counts requests
    a concurrent request has claimed but not yet sent, so two simultaneous
    requests cannot jointly exceed the limit.
    """

    spent: int = 0
    reserved: int = 0

    @property
    def claimed(self) -> int:
        """Everything already sent plus everything currently claimed."""

        return self.spent + self.reserved

    @property
    def remaining(self) -> int:
        return max(0, PLAN_BILLED_REQUEST_LIMIT - self.claimed)


class AllowanceError(Exception):
    """The token is unknown, malformed, or expired. No provider call is made."""


class AllowanceStore:
    """Short-lived, bounded, process-local allowance per submitted plan.

    Tokens are cryptographically random and carry no meaning. A caller cannot
    guess another token and cannot reset its own by sending a number.
    """

    def __init__(
        self,
        *,
        maxsize: int = _ALLOWANCE_MAX,
        ttl: int = _ALLOWANCE_TTL_SECONDS,
        limit: int = PLAN_BILLED_REQUEST_LIMIT,
    ) -> None:
        self._items: TTLCache[str, Allowance] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = threading.Lock()
        self._limit = limit

    def issue(self) -> str:
        """Create a new plan identity and return its opaque token."""

        token = secrets.token_urlsafe(_TOKEN_BYTES)
        with self._lock:
            self._items[token] = Allowance()
        return token

    def remaining(self, token: str) -> int:
        """Return the remaining allowance, or raise for an unknown token."""

        with self._lock:
            found = self._items.get(token)
            if found is None:
                raise AllowanceError("unknown plan token")
            return max(0, self._limit - found.claimed)

    def spent(self, token: str) -> int:
        """Return how many billed requests this plan has actually sent."""

        with self._lock:
            found = self._items.get(token)
            if found is None:
                raise AllowanceError("unknown plan token")
            return found.spent

    def reserve(self, token: str, count: int = 1) -> None:
        """Claim `count` sends atomically, or raise when the plan cannot afford them.

        Reserving before the call is what makes a concurrent pair safe: the
        second request sees the first request's claim and stops.
        """

        if count < 0:
            raise AllowanceError("a negative reservation is not a request")
        with self._lock:
            found = self._items.get(token)
            if found is None:
                raise AllowanceError("unknown plan token")
            if found.claimed + count > self._limit:
                raise AllowanceError("plan allowance reached")
            found.reserved += count

    def charge(self, token: str, sent: int, *, release: int = 0) -> None:
        """Turn `sent` claims into spent requests, and drop `release` unused ones.

        `sent` is one client's own billed-send count and is added to the plan's
        total, because each request builds its own client. A retry that reached
        the network is inside `sent`, so it stays charged. A call cancelled
        before it reached the network is not inside `sent`, so it is refunded
        through `release`. Other concurrent claims are left alone.
        """

        if sent < 0 or release < 0:
            return
        with self._lock:
            found = self._items.get(token)
            if found is None:
                return
            found.spent += sent
            found.reserved = max(0, found.reserved - sent - release)

    def release(self, token: str, count: int = 1) -> None:
        """Refund claims for requests that were never sent.

        A cancelled request that reached no provider call consumes nothing.
        """

        if count <= 0:
            return
        with self._lock:
            found = self._items.get(token)
            if found is None:
                return
            found.reserved = max(0, found.reserved - count)

    def forget(self, token: str) -> None:
        """Drop one plan identity. Used when a refinement starts a new plan."""

        with self._lock:
            self._items.pop(token, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


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
    """Bounded reuse of a candidate pool. Raw provider documents are not stored."""

    def __init__(self, *, maxsize: int = _CACHE_MAX, ttl: int = _CACHE_TTL_SECONDS) -> None:
        self._items: TTLCache[str, CandidatePool] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = threading.Lock()

    def get(self, key: str) -> CandidatePool | None:
        """Return a copy of the cached pool, or None when the key is unsafe or missing."""

        if not _safe_key(key):
            return None
        with self._lock:
            found = self._items.get(key)
        if found is None:
            return None
        return found.model_copy(deep=True)

    def put(self, key: str, pool: CandidatePool) -> None:
        """Store a copy of the pool when the key is a hash and the pool is not empty."""

        if not pool.places or not _safe_key(key):
            return
        stored = pool.model_copy(deep=True)
        with self._lock:
            self._items[key] = stored

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


def _safe_key(key: str) -> bool:
    return len(key) == 64 and all(character in "0123456789abcdef" for character in key)


def _exhausted() -> SerpApiFailure:
    """The signal the provider already uses for a spent credit budget."""

    return SerpApiFailure(
        "CREDIT_BUDGET_EXCEEDED",
        "This plan's search allowance is exhausted.",
        retryable=False,
    )


class MeteredProvider:
    """Wraps a provider client so billed calls come out of a plan's allowance.

    Only a known billed lookup is claimed. Anything else, including the free
    Locations call, `close`, and every attribute, passes straight through.
    """

    BILLED = frozenset(
        {
            "lookup_maps_coordinates",
            "place_details",
            "place_reviews",
            "search_places",
            "web_search",
        }
    )

    def __init__(self, inner: object, store: AllowanceStore, token: str) -> None:
        self._inner = inner
        self._store = store
        self._token = token
        self._billed = 0

    @property
    def credits_charged(self) -> int:
        """Billed sends made through this wrapper, retries included."""

        return self._billed

    def _call(self, name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> object:
        try:
            self._store.reserve(self._token)
        except AllowanceError as exc:
            # Reuse the provider's own budget signal so discovery and destination
            # resolution stop gracefully instead of failing the whole request.
            raise _exhausted() from exc
        try:
            result = getattr(self._inner, name)(*args, **kwargs)
        except AllowanceError:
            raise
        except BaseException as exc:
            # The inner client counts every billed request it actually sent.
            sent = int(getattr(exc, "billed_requests", 0) or 0)
            if sent > 0:
                self._billed += sent
                self._store.charge(self._token, sent)
            else:
                self._store.release(self._token)
            raise
        self._billed += 1
        self._store.charge(self._token, 1)
        return result

    def __getattr__(self, name: str) -> object:
        attribute = getattr(self._inner, name)
        if name not in self.BILLED or not callable(attribute):
            return attribute

        def _bound(*args: object, **kwargs: object) -> object:
            return self._call(name, args, kwargs)

        return _bound
