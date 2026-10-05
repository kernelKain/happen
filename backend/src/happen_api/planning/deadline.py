"""One monotonic planning deadline shared by every stage of one request.

A planning request has one budget of wall-clock time. This module owns that
budget so no stage can quietly invent a second one. A deadline is monotonic, so
a host clock change cannot extend or shorten it.

Two properties matter for the rest of the planner:

- Cancellation is checked *before* work starts. A cancelled request that never
  began must not reach the network, and must not spend plan allowance.
- A stage is told the time it may use, not the time it may take in total, so
  concurrent work shares one budget instead of each restarting a clock.

Nothing here knows about SerpApi, and nothing here reads or writes a plan
allowance. That belongs to the caller.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Self

# The hard planning deadline from the approved contract. A request that has not
# produced a complete answer by now reports partial evidence or a timeout.
PLANNING_DEADLINE_SECONDS = 14.0

# Per-stage ceilings. A stage may never exceed the deadline it was handed, and
# these caps keep one slow call from consuming the whole request budget.
DESTINATION_SECONDS = 6.0
SEARCH_SECONDS = 8.0
DETAILS_SECONDS = 4.0
REVIEWS_SECONDS = 4.0
WEB_SECONDS = 4.0
DIRECTIONS_SECONDS = 4.0
EXTRACTION_SECONDS = 6.0

# A cached read has no network, so it gets a short ceiling of its own. The
# contract's cached-swap target is well inside this.
CACHED_SECONDS = 0.3

# Below this, a stage is not worth starting: it cannot finish, and starting it
# would push the request past its deadline.
_MIN_USEFUL_SECONDS = 1.0


class Stage(str):
    """Named planning stages, used for diagnostics only."""

    destination = "destination"
    search = "search"
    details = "details"
    reviews = "reviews"
    web = "web"
    directions = "directions"
    extraction = "extraction"
    cached = "cached"


class DeadlineExceeded(Exception):
    """The planning budget ran out before this stage could start its work."""


@dataclass
class StageTiming:
    """How long one stage took, and whether it finished in time.

    Only the stage name, the elapsed seconds, and the outcome are kept. A
    timing record never carries a prompt, a destination, a URL, a credential,
    or review text, so it is safe to log.
    """

    stage: str
    elapsed_ms: int = 0
    outcome: str = "ok"

    def as_dict(self) -> dict[str, object]:
        return {"stage": self.stage, "elapsed_ms": self.elapsed_ms, "outcome": self.outcome}


@dataclass
class PlanningDeadline:
    """One monotonic budget for one planning request.

    `cancel` is a caller-supplied predicate, normally "has this HTTP request
    been disconnected". It is polled at stage boundaries and immediately before
    any outbound send, which is what makes a cancelled request cost nothing.
    """

    budget_seconds: float = PLANNING_DEADLINE_SECONDS
    now: Callable[[], float] = time.monotonic
    cancel: Callable[[], bool] = lambda: False
    _started: float | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _timings: list[StageTiming] = field(default_factory=list, repr=False)

    def start(self) -> PlanningDeadline:
        """Record the starting moment. Starting twice keeps the first moment."""

        with self._lock:
            if self._started is None:
                self._started = self.now()
        return self

    @property
    def elapsed(self) -> float:
        """Seconds consumed so far."""

        with self._lock:
            if self._started is None:
                return 0.0
            return self.now() - self._started

    @property
    def remaining(self) -> float:
        """Seconds left before the hard deadline."""

        return max(0.0, self.budget_seconds - self.elapsed)

    @property
    def expired(self) -> bool:
        return self.remaining <= 0.0

    def cancelled(self) -> bool:
        """Whether the caller went away before the work could proceed."""

        if self.cancel():
            return True
        return self.expired

    def budget_for(self, cap: float) -> float:
        """Return how long one stage may run: its own cap, inside the deadline.

        A stage is never handed more time than the request has left, so
        concurrent work cannot overrun the deadline between them.
        """

        return max(0.0, min(cap, self.remaining))

    def can_start(self, cap: float) -> bool:
        """Whether a stage should begin at all.

        A stage is refused once the request has less than a usable minimum left.
        Starting one then would run the request past its deadline, because a
        stage cannot be interrupted from outside and its own work continues
        after its last network call.

        This bounds the total overrun to that minimum rather than eliminating
        it, which is the honest guarantee: a stage already inside a call when
        the budget expires always finishes first. `cap` is unused here on
        purpose. Refusing on the cap instead would stop a two-stop discovery
        that legitimately needs more than one slice.
        """

        del cap  # The floor is about remaining time, not the stage's wish.
        return self.remaining >= _MIN_USEFUL_SECONDS

    def check(self) -> None:
        """Raise when the request may not start more work."""

        if self.cancelled():
            raise DeadlineExceeded(
                "the planning budget is exhausted" if self.expired else "cancelled"
            )

    def allow_send(self) -> bool:
        """Whether one outbound attempt may start.

        This is the last gate before a network call. Returning False means the
        attempt must not be sent, so it must not be charged either.
        """

        return not self.cancelled()

    def stage(self, stage: Stage | str, cap: float) -> _StageScope:
        """Run one stage inside the deadline and record how long it took."""

        return _StageScope(self, str(stage), cap)

    def timings(self) -> list[dict[str, object]]:
        """Return the recorded stage timings in the order they finished."""

        with self._lock:
            return [item.as_dict() for item in self._timings]

    def _record(self, stage: str, elapsed_ms: int, outcome: str) -> None:
        with self._lock:
            if len(self._timings) >= _MAX_TIMINGS:
                return
            self._timings.append(StageTiming(stage=stage, elapsed_ms=elapsed_ms, outcome=outcome))


_MAX_TIMINGS = 64


class _StageScope:
    """Context manager for one stage.

    A stage that cannot be given any of its time is refused at entry rather than
    started and cut off. Recording `exhausted` without refusing would let a
    sequence of stages each run to completion past the deadline, because the
    last of them is already inside the call when the budget runs out. The
    stage's own transport timeout still bounds the call it does make.
    """

    def __init__(self, deadline: PlanningDeadline, stage: str, cap: float) -> None:
        self._deadline = deadline
        self._stage = stage
        self._cap = cap
        self._entered = 0.0
        self.exhausted = False

    def __enter__(self) -> Self:
        self._deadline.check()
        self._entered = self._deadline.now()
        # A stage is refused when the request has too little time left to be
        # worth starting it. Recording only the fact and running anyway would
        # let a sequence of stages each start with a sliver and carry the
        # request past its deadline.
        self.exhausted = not self._deadline.can_start(self._cap)
        if self.exhausted:
            raise DeadlineExceeded(
                f"the {self._stage} stage has no usable time left in the planning budget"
            )
        return self

    def __exit__(self, exc_type: object, *_rest: object) -> None:
        elapsed_ms = int((self._deadline.now() - self._entered) * 1000)
        if exc_type is None:
            outcome = "timeout" if self.exhausted else "ok"
        elif exc_type is DeadlineExceeded:
            outcome = "cancelled"
        else:
            outcome = "failed"
        self._deadline._record(self._stage, elapsed_ms, outcome)


def stage_timings_are_safe(timings: list[dict[str, object]]) -> bool:
    """Whether a timing list carries only the keys that are safe to record.

    Used by tests to keep a prompt, a URL, or review text out of diagnostics.
    """

    allowed = {"stage", "elapsed_ms", "outcome"}
    return all(set(item) <= allowed for item in timings)
