"""Deterministic constraint checks. Unknown evidence adds nothing.

Hours stay outside this module. A met or unmet result cites the passage that
supports it. Accessibility and dietary claims are hard: an explicit
contradiction blocks the place, and a missing statement stays unknown.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from happen_api.planning.contracts import Budget, BudgetBound, BudgetTier
from happen_api.planning.discovery import DiscoveredPlace

_MET_POINTS = 4
_CONSTRAINT_CAP = 16
_ABOUT = Decimal("0.25")
_TIER_RANK = {BudgetTier.low: 1, BudgetTier.moderate: 2, BudgetTier.high: 3}
_SYMBOL = {"¥": "JPY", "$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}
_TIER = re.compile(r"^[¥$€£₹]{1,4}$")
_AMOUNT = re.compile(
    r"(?i)^(?:"
    r"(?P<cur>[A-Z]{3})\s*(?P<amt>\d+(?:\.\d{1,2})?)"
    r"|(?P<amt2>\d+(?:\.\d{1,2})?)\s*(?P<cur2>[A-Z]{3})"
    r"|(?P<sym>[¥$€£₹])\s*(?P<amt3>\d+(?:\.\d{1,2})?)"
    r")$"
)
_CAPACITY = re.compile(
    r"(?i)\b(?:seats|seating for|table for|party of|parties of|"
    r"reservation for|up to|capacity(?: of)?|accommodates)\s+(\d{1,2})\b"
)
_HARD = frozenset({"wheelchair access", "step-free", "hearing loop", "vegetarian", "vegan"})
_NOT = r"(?<!\bno )(?<!\bnot )"

Status = Literal["met", "unmet", "unknown", "not_applicable"]
SourceName = Literal["maps", "community"]


class EveningConstraints(BaseModel):
    """The constraint set a plan may score. Empty fields stay unused."""

    model_config = ConfigDict(extra="forbid")

    party_size: int | None = Field(default=None, ge=1, le=20)
    budget: Budget | None = None
    preferences: list[str] = Field(default_factory=list, max_length=8)
    accessibility_needs: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("preferences", "accessibility_needs")
    @classmethod
    def _phrases(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item or len(item) > 40:
                raise ValueError("constraint text is too long")
        return value


@dataclass(frozen=True)
class Finding:
    """One constraint result. Met and unmet always carry a passage."""

    constraint: str
    status: Status
    source: SourceName | None = None
    text: str | None = None

    def __post_init__(self) -> None:
        cited = self.status in {"met", "unmet"}
        if cited and not self.text:
            raise ValueError("a met or unmet constraint cites evidence")
        if not cited and self.text:
            raise ValueError("an unknown constraint does not cite support")


@dataclass(frozen=True)
class _Signal:
    met: tuple[str, ...]
    unmet: tuple[str, ...]


_SIGNALS: dict[str, _Signal] = {
    "quiet": _Signal(
        (rf"{_NOT}\b(?:quiet|calm|peaceful|not too loud)\b",),
        (r"\bnot quiet\b", r"(?<!\bnot too )\b(?:loud|noisy|raucous)\b"),
    ),
    "romantic": _Signal((rf"{_NOT}\b(?:romantic|intimate)\b",), (r"\bnot romantic\b",)),
    "outdoor seating": _Signal(
        (rf"{_NOT}\b(?:outdoor seating|outdoor|patio|terrace)\b",),
        (r"\b(?:indoor only|no outdoor)\b",),
    ),
    "casual": _Signal((rf"{_NOT}\bcasual\b",), (r"\b(?:formal|dress code)\b",)),
    "formal": _Signal((rf"{_NOT}\b(?:formal|dress code)\b",), (r"\bcasual\b",)),
    "spicy": _Signal(
        (rf"{_NOT}\bspicy\b",),
        (r"\b(?:not spicy|no spicy|mild only)\b",),
    ),
    "live music": _Signal(
        (rf"{_NOT}\blive (?:music|band|jazz)\b",),
        (r"\bno live music\b",),
    ),
    "vegetarian": _Signal(
        (rf"{_NOT}\b(?:vegetarian|veggie options)\b",),
        (r"\b(?:no vegetarian|not vegetarian|meat only)\b",),
    ),
    "vegan": _Signal((rf"{_NOT}\bvegan\b",), (r"\b(?:no vegan|not vegan)\b",)),
    "wheelchair access": _Signal(
        (rf"{_NOT}\bwheelchair(?: accessible| access)?\b",),
        (r"\b(?:no wheelchair|not wheelchair|stairs only|not accessible)\b",),
    ),
    "step-free": _Signal(
        (r"\b(?:step-free|step free|no stairs)\b",),
        (r"\b(?:stairs only|steps required)\b",),
    ),
    "hearing loop": _Signal(
        (rf"{_NOT}\b(?:hearing loop|induction loop)\b",),
        (r"\bno hearing loop\b",),
    ),
}


def known_phrases(items: Sequence[str]) -> list[str]:
    """Return the requested phrases this module can check."""

    found: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.casefold().strip()
        if key in _SIGNALS and key not in seen:
            seen.add(key)
            found.append(key)
    return found


def review_phrases(constraints: EveningConstraints) -> list[str]:
    """Return requested phrases whose wording a review can still confirm."""

    return known_phrases((*constraints.preferences, *constraints.accessibility_needs))


def review_gain(place: DiscoveredPlace, constraints: EveningConstraints) -> int:
    """Return points a later review could still add. Unknown text adds nothing now."""

    current = constraint_points(place, constraints)
    room = _CONSTRAINT_CAP - current
    if room <= 0:
        return 0
    pending = _MET_POINTS * sum(
        1
        for item in assess(place, constraints)
        if item.status != "met" and item.constraint.casefold() in _SIGNALS
    )
    return min(room, pending)


def assess(place: DiscoveredPlace, constraints: EveningConstraints) -> list[Finding]:
    """Assess every requested constraint. Unsupported wording stays unknown."""

    passages = _passages(place)
    findings: list[Finding] = []
    for label in _requested(constraints):
        signal = _SIGNALS.get(label.casefold())
        findings.append(_phrase(label, signal, passages) if signal else _unknown(label))
    if constraints.budget is not None:
        findings.append(_budget(place, constraints.budget))
    if constraints.party_size is not None:
        findings.append(_party(place, constraints.party_size))
    return findings


def constraint_points(place: DiscoveredPlace, constraints: EveningConstraints) -> int:
    """Add points only for a met constraint. Unknown and unmet add zero."""

    met = sum(1 for item in assess(place, constraints) if item.status == "met")
    return min(_CONSTRAINT_CAP, _MET_POINTS * met)


def blocks_selection(place: DiscoveredPlace, constraints: EveningConstraints) -> bool:
    """Return whether an accessibility or dietary contradiction rules a place out."""

    return any(
        item.status == "unmet" and _is_hard(item.constraint) for item in assess(place, constraints)
    )


def hard_unverified(findings: list[Finding]) -> list[str]:
    """Return requested hard constraints that this place did not verify."""

    return [
        item.constraint for item in findings if _is_hard(item.constraint) and item.status != "met"
    ]


def _phrase(label: str, signal: _Signal, passages: list[tuple[SourceName, str]]) -> Finding:
    met_hit: tuple[SourceName, str] | None = None
    unmet_hit: tuple[SourceName, str] | None = None
    for source, text in passages:
        if unmet_hit is None and _match(signal.unmet, text):
            unmet_hit = (source, text)
        if met_hit is None and _match(signal.met, text):
            met_hit = (source, text)
    if met_hit is not None and unmet_hit is None:
        return Finding(label, "met", met_hit[0], _clip(met_hit[1]))
    if unmet_hit is not None and met_hit is None:
        return Finding(label, "unmet", unmet_hit[0], _clip(unmet_hit[1]))
    return _unknown(label)


def _budget(place: DiscoveredPlace, budget: Budget) -> Finding:
    if not place.price:
        return _unknown("budget")
    parsed = _price(place.price)
    if parsed is None:
        return _unknown("budget")
    kind, payload = parsed
    if kind == "tier":
        if budget.tier is None or not isinstance(payload, BudgetTier):
            return _unknown("budget")
        status: Status = "met" if _TIER_RANK[payload] <= _TIER_RANK[budget.tier] else "unmet"
        return Finding("budget", status, "maps", _clip(place.price))
    if budget.amount is None or not budget.currency or budget.bound is None:
        return _unknown("budget")
    if not isinstance(payload, tuple):
        return _unknown("budget")
    currency, amount = payload
    if currency != budget.currency:
        return _unknown("budget")
    status = "met" if _amount_allows(amount, budget.amount, budget.bound) else "unmet"
    return Finding("budget", status, "maps", _clip(place.price))


def _party(place: DiscoveredPlace, size: int) -> Finding:
    best: tuple[int, SourceName, str] | None = None
    for source, text in _passages(place):
        for match in _CAPACITY.finditer(text):
            count = int(match.group(1))
            if best is None or count > best[0]:
                best = (count, source, text)
    if best is None:
        return _unknown("party size")
    status: Status = "met" if best[0] >= size else "unmet"
    return Finding("party size", status, best[1], _clip(best[2]))


def _price(value: str | None) -> tuple[str, BudgetTier | tuple[str, Decimal]] | None:
    if value is None:
        return None
    token = "".join(value.split())
    if _TIER.fullmatch(token):
        count = len(token)
        if count <= 1:
            return ("tier", BudgetTier.low)
        if count == 2:
            return ("tier", BudgetTier.moderate)
        return ("tier", BudgetTier.high)
    match = _AMOUNT.fullmatch(token)
    if match is None:
        return None
    if match.group("cur") and match.group("amt"):
        return ("amount", (match.group("cur").upper(), Decimal(match.group("amt"))))
    if match.group("cur2") and match.group("amt2"):
        return ("amount", (match.group("cur2").upper(), Decimal(match.group("amt2"))))
    symbol = match.group("sym")
    amount = match.group("amt3")
    if symbol is None or amount is None:
        return None
    return ("amount", (_SYMBOL[symbol], Decimal(amount)))


def _amount_allows(price: Decimal, amount: Decimal, bound: BudgetBound) -> bool:
    if bound is BudgetBound.at_most:
        return price <= amount
    if bound is BudgetBound.exact:
        return price == amount
    if amount == 0:
        return price == 0
    return abs(price - amount) <= amount * _ABOUT


def _requested(constraints: EveningConstraints) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for item in (*constraints.accessibility_needs, *constraints.preferences):
        label = " ".join(item.split())
        key = label.casefold()
        if not label or key in seen:
            continue
        seen.add(key)
        labels.append(label)
    return labels


def _passages(place: DiscoveredPlace) -> list[tuple[SourceName, str]]:
    rows: list[tuple[SourceName, str]] = []
    for text in (*place.highlights, *place.events, place.category or ""):
        if text.strip():
            rows.append(("maps", text.strip()))
    for text in place.community_notes:
        if text.strip():
            rows.append(("community", text.strip()))
    return rows


def _match(patterns: tuple[str, ...], text: str) -> bool:
    folded = text.casefold()
    return any(re.search(pattern, folded) for pattern in patterns)


def _is_hard(label: str) -> bool:
    return label.casefold().strip() in _HARD


def _unknown(label: str) -> Finding:
    return Finding(label, "unknown")


def _clip(text: str) -> str:
    return text[:300]
