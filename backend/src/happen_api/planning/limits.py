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

    `spent` counts real outbound provider attempts. It is only ever increased
    by an atomic claim taken at the moment an attempt is about to be sent, so
    the counter cannot lag behind what the network has already seen.
    """

    spent: int = 0

    @property
    def remaining(self) -> int:
        return max(0, PLAN_BILLED_REQUEST_LIMIT - self.spent)


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
            return max(0, self._limit - found.spent)

    def spent(self, token: str) -> int:
        """Return how many billed requests this plan has actually sent."""

        with self._lock:
            found = self._items.get(token)
            if found is None:
                raise AllowanceError("unknown plan token")
            return found.spent

    def claim_attempt(self, token: str, count: int = 1) -> None:
        """Atomically claim `count` outbound attempts before they are sent.

        This is the only place a request is charged, and it runs immediately
        before the network send. Claiming per attempt rather than per wrapper
        call is what makes a retry cost its own attempt: an inner client that
        sends twice has claimed twice. Claiming before the send is also what
        makes a concurrent pair safe, because the second caller sees the first
        claim and refuses rather than overspending the shared budget.
        """

        if count < 1:
            raise AllowanceError("an outbound attempt must claim at least one request")
        with self._lock:
            found = self._items.get(token)
            if found is None:
                raise AllowanceError("unknown plan token")
            if found.spent + count > self._limit:
                raise AllowanceError("plan allowance reached")
            found.spent += count

    def reset(self, token: str) -> None:
        """Restore a plan's whole allowance, keeping the same opaque token."""

        with self._lock:
            found = self._items.get(token)
            if found is None:
                raise AllowanceError("unknown plan token")
            found.spent = 0

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
    """Wraps a provider client so every outbound attempt draws on a plan allowance.

    A real `SerpApiClient` runs the allowance gate itself, once per network
    send, so each retry is charged separately and a cancelled call costs
    nothing. A provider that does not implement the gate is charged per billed
    call instead, which is correct for the scripted in-memory fakes used by
    tests and still refuses a call the plan cannot afford.

    The free Locations call, `close`, and every other attribute pass through.
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
        self._gated = False

    @property
    def credits_charged(self) -> int:
        """Billed sends made through this wrapper, retries included."""

        return self._billed

    def _gated_provider(self) -> bool:
        """Whether the inner client charges itself at the send boundary."""

        if self._gated:
            return True
        setter = getattr(self._inner, "set_attempt_gate", None)
        if not callable(setter):
            return False
        setter(self._claim)
        self._gated = True
        return True

    def _claim(self) -> None:
        """Claim one outbound attempt, or stop it before the network."""

        try:
            self._store.claim_attempt(self._token)
        except AllowanceError as exc:
            # Reuse the provider's own budget signal so discovery and destination
            # resolution stop gracefully instead of failing the whole request.
            raise _exhausted() from exc
        self._billed += 1

    def _call(self, name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> object:
        if self._gated_provider():
            return getattr(self._inner, name)(*args, **kwargs)
        self._claim()
        return getattr(self._inner, name)(*args, **kwargs)

    def __getattr__(self, name: str) -> object:
        attribute = getattr(self._inner, name)
        if name not in self.BILLED or not callable(attribute):
            return attribute

        def _bound(*args: object, **kwargs: object) -> object:
            return self._call(name, args, kwargs)

        return _bound
