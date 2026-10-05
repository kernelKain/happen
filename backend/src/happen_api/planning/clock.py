"""Clock used to supply one instant. Relative dates use it only after a destination zone exists."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Supplies one timezone-aware instant for a later destination-local date."""

    def now(self) -> datetime:
        """Return the current timezone-aware moment."""


class FixedClock:
    """Returns one moment so relative-date tests do not depend on the host clock."""

    def __init__(self, moment: datetime) -> None:
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("clock moment must be timezone-aware")
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class SystemClock:
    """Returns the current UTC moment for a live request."""

    def now(self) -> datetime:
        return datetime.now(UTC)
