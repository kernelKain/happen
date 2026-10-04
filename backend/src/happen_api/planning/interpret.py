"""Deterministic reading of one evening prompt.

Prompt text is untrusted data. Instruction-like sentences are ignored.
Nothing in this module calls SerpApi or loads a model.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal
from itertools import pairwise

from pydantic import ValidationError

from happen_api.planning.clock import Clock
from happen_api.planning.contracts import (
    MAX_PROMPT_LENGTH,
    Ambiguity,
    BriefConfidence,
    BriefField,
    Budget,
    BudgetBound,
    BudgetTier,
    EssentialField,
    IntentKind,
    LivePlanOutcome,
    LivePlanResponse,
    MissingField,
    PlaceIntent,
    PlanningBrief,
    PlanningErrorCode,
    PlanningInputError,
    PlanningPromptRequest,
    PlanningUserError,
)
from happen_api.planning.follow_up import question_for, select_follow_up

_INSTRUCTION = re.compile(
    r"(?i)("
    r"ignore (?:all |any )?(?:previous|prior|above) instructions"
    r"|disregard (?:all |any )?(?:previous|prior|above)"
    r"|you are now"
    r"|system prompt"
    r"|new instructions"
    r"|override (?:the |all )?(?:rules|destination|plan)"
    r"|set (?:the )?(?:destination|date|time|budget|intent)"
    r"|do not follow"
    r"|reveal (?:the )?(?:secret|api key|prompt)"
    r")"
)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?\n]?")

_ERRORS = {
    PlanningErrorCode.prompt_empty: (
        "The prompt is empty.",
        "Describe the evening you want to plan.",
        False,
    ),
    PlanningErrorCode.prompt_too_large: (
        "The prompt is too long.",
        "Shorten the prompt and try again.",
        False,
    ),
    PlanningErrorCode.prompt_invalid: (
        "The prompt contains characters Happen cannot use.",
        "Remove unusual characters and try again.",
        False,
    ),
}


@dataclass(frozen=True)
class _Place:
    canonical: str
    aliases: tuple[str, ...]
    alternatives: tuple[str, ...] = ()
    qualifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Hit:
    start: int
    end: int
    place: _Place


_PLACES = (
    _Place("Bengaluru", ("bengaluru", "bangalore")),
    _Place("Mumbai", ("mumbai",)),
    _Place("New Delhi", ("new delhi",)),
    _Place("Delhi", ("delhi",)),
    _Place("Kolkata", ("kolkata",)),
    _Place("Chennai", ("chennai",)),
    _Place("Hyderabad", ("hyderabad",)),
    _Place("Pune", ("pune",)),
    _Place("Jaipur", ("jaipur",)),
    _Place("Indiranagar", ("indiranagar",)),
    _Place(
        "London",
        ("london",),
        ("London, United Kingdom", "London, Ontario"),
        ("united kingdom", "u.k.", "uk", "england", "britain", "ontario", "canada"),
    ),
    _Place(
        "Manchester",
        ("manchester",),
        ("Manchester, United Kingdom", "Manchester, New Hampshire"),
        ("united kingdom", "uk", "england", "new hampshire", "nh"),
    ),
    _Place("Edinburgh", ("edinburgh",)),
    _Place("Glasgow", ("glasgow",)),
    _Place(
        "Birmingham",
        ("birmingham",),
        ("Birmingham, United Kingdom", "Birmingham, Alabama"),
        ("united kingdom", "uk", "england", "alabama"),
    ),
    _Place(
        "Cambridge",
        ("cambridge",),
        ("Cambridge, United Kingdom", "Cambridge, Massachusetts"),
        ("united kingdom", "uk", "england", "massachusetts"),
    ),
    _Place("Oxford", ("oxford",)),
    _Place("Bristol", ("bristol",)),
    _Place("Leeds", ("leeds",)),
    _Place("Cardiff", ("cardiff",)),
    _Place("New York", ("new york", "nyc")),
    _Place("Brooklyn", ("brooklyn",)),
    _Place("Chicago", ("chicago",)),
    _Place("San Francisco", ("san francisco",)),
    _Place("Los Angeles", ("los angeles",)),
    _Place("Seattle", ("seattle",)),
    _Place("Austin", ("austin",)),
    _Place("Boston", ("boston",)),
    _Place(
        "Portland",
        ("portland",),
        ("Portland, Oregon", "Portland, Maine"),
        ("oregon", "maine"),
    ),
    _Place("Tokyo", ("tokyo",)),
    _Place("Kyoto", ("kyoto",)),
    _Place("Osaka", ("osaka",)),
    _Place("Hiroshima", ("hiroshima",)),
    _Place("Sapporo", ("sapporo",)),
    _Place("Yokohama", ("yokohama",)),
    _Place("Nara", ("nara",)),
    _Place("Kobe", ("kobe",)),
    _Place(
        "Paris",
        ("paris",),
        ("Paris, France", "Paris, Texas"),
        ("france", "texas"),
    ),
    _Place(
        "Naples",
        ("naples",),
        ("Naples, Italy", "Naples, Florida"),
        ("italy", "florida"),
    ),
    _Place(
        "Valencia",
        ("valencia",),
        ("Valencia, Spain", "Valencia, California"),
        ("spain", "california"),
    ),
)

_ALIASES = tuple(
    sorted(
        ((alias, place) for place in _PLACES for alias in place.aliases),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_INTENTS: tuple[tuple[IntentKind, str], ...] = (
    (IntentKind.live_music, r"\blive music\b|\bjazz\b"),
    (IntentKind.dinner, r"\b(?:dinner|supper|restaurant)\b"),
    (IntentKind.drinks, r"\b(?:drinks|cocktails|cocktail|bar|pub)\b"),
    (IntentKind.coffee, r"\b(?:coffee|cafe|café)\b"),
    (IntentKind.dessert, r"\b(?:dessert|desserts)\b"),
    (IntentKind.show, r"\b(?:show|concert|theatre|theater|gig|movie|cinema|film)\b"),
    (IntentKind.walk, r"\b(?:walk|stroll)\b"),
    (IntentKind.museum, r"\b(?:museum|gallery)\b"),
)
_PREFERENCES: tuple[tuple[str, str], ...] = (
    (r"\bvegetarian\b", "vegetarian"),
    (r"\bvegan\b", "vegan"),
    (r"\bromantic\b", "romantic"),
    (r"\boutdoor\b", "outdoor seating"),
    (r"\b(?:quiet|not too loud)\b", "quiet"),
    (r"\bcasual\b", "casual"),
    (r"\bformal\b", "formal"),
    (r"\bspicy\b", "spicy"),
)
_ACCESS: tuple[tuple[str, str], ...] = (
    (r"\bwheelchair(?:\s+accessible)?\b", "wheelchair access"),
    (r"\b(?:step-free|step free|no stairs)\b", "step-free"),
    (r"\bhearing loop\b", "hearing loop"),
)
_PLACE_STOP = frozenset(
    {
        "the",
        "this",
        "next",
        "tonight",
        "tomorrow",
        "today",
        "evening",
        "morning",
        "afternoon",
        "night",
        "weekend",
        "please",
        "ignore",
        "dinner",
        "drinks",
        "coffee",
        *_WEEKDAYS,
        *_MONTHS,
    }
)
_UNKNOWN_PLACE = re.compile(r"\b(?:in|near|around)\s+([A-Z][a-z]+(?:[ '-][A-Z][a-z]+){0,2})\b")
_JOIN_GAP = re.compile(r"\A\s*(?:,|in|near)\s*\Z")
_SPLIT_GAP = re.compile(r"(?i)\bor\b|\band\b")


def interpret(prompt: str, clock: Clock) -> LivePlanResponse:
    """Read explicit evening facts and attach at most one follow-up question."""

    request = _request(prompt)
    evidence = _without_instructions(request.prompt)
    today = clock.now().date()
    destination, destination_note = _destination(evidence)
    local_date, date_note = _date(evidence, today)
    local_start, time_note = _start_time(evidence)
    party_size, party_note = _party(evidence)
    budget, budget_note = _budget(evidence)
    intents, intent_note = _intents(evidence)
    ambiguities = [
        note
        for note in (destination_note, date_note, time_note, party_note, budget_note, intent_note)
        if note is not None
    ]
    missing = _missing(
        destination=destination,
        local_date=local_date,
        local_start=local_start,
        intents=intents,
        ambiguities=ambiguities,
    )
    brief = PlanningBrief(
        raw_prompt=request.prompt,
        destination_text=destination,
        local_date=local_date,
        local_start=local_start,
        party_size=party_size,
        budget=budget,
        intents=intents,
        preferences=_phrases(evidence, _PREFERENCES),
        accessibility_needs=_phrases(evidence, _ACCESS),
        missing_essentials=missing,
        ambiguities=ambiguities,
        confidence=_confidence(destination, local_date, local_start, intents),
    )
    follow_up = select_follow_up(brief)
    warnings: list[str] = []
    if follow_up is None:
        warnings.append("Live place retrieval has not run.")
    return LivePlanResponse(
        outcome=(
            LivePlanOutcome.needs_follow_up
            if follow_up is not None
            else LivePlanOutcome.ready_for_retrieval
        ),
        brief=brief,
        follow_up=follow_up,
        warnings=warnings,
    )


def _request(prompt: str) -> PlanningPromptRequest:
    if not isinstance(prompt, str):
        raise _input_error(PlanningErrorCode.prompt_invalid)
    if not prompt.strip():
        raise _input_error(PlanningErrorCode.prompt_empty)
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise _input_error(PlanningErrorCode.prompt_too_large)
    try:
        return PlanningPromptRequest(prompt=prompt)
    except ValidationError as exc:
        text = str(exc)
        if "empty" in text:
            raise _input_error(PlanningErrorCode.prompt_empty) from None
        if "unsupported characters" in text:
            raise _input_error(PlanningErrorCode.prompt_invalid) from None
        raise _input_error(PlanningErrorCode.prompt_too_large) from None


def _input_error(code: PlanningErrorCode) -> PlanningInputError:
    message, action, retryable = _ERRORS[code]
    return PlanningInputError(
        PlanningUserError(code=code, message=message, retryable=retryable, next_action=action)
    )


def _without_instructions(prompt: str) -> str:
    kept: list[str] = []
    for match in _SENTENCE.finditer(prompt):
        sentence = match.group(0)
        instruction = _INSTRUCTION.search(sentence)
        if instruction is None:
            kept.append(sentence)
            continue
        prefix = sentence[: instruction.start()].strip(" ,;")
        if prefix:
            kept.append(prefix)
    return " ".join(kept)


def _destination(text: str) -> tuple[str | None, Ambiguity | None]:
    hits = _collapse(_known_hits(text))
    if not hits:
        unknown = _UNKNOWN_PLACE.search(text)
        if unknown is None:
            return None, None
        phrase = unknown.group(1)
        if phrase.split()[0].casefold() in _PLACE_STOP:
            return None, None
        return phrase, None
    if len(hits) == 1:
        return _single_destination(text, hits[0])
    if _one_phrase(text, hits):
        start = hits[0].start
        end = max(_qualified_end(text, hit) for hit in hits)
        for hit in hits:
            if hit.place.alternatives and _qualified_end(text, hit) == hit.end:
                return None, _place_ambiguity(hit.place)
        return text[start:end].strip(" ,"), None
    return None, Ambiguity(
        field=BriefField.destination,
        message="Which place should this evening be in?",
        candidates=[text[hit.start : hit.end] for hit in hits[:6]],
        blocking=True,
    )


def _known_hits(text: str) -> list[_Hit]:
    occupied: list[tuple[int, int]] = []
    hits: list[_Hit] = []
    for alias, place in _ALIASES:
        pattern = re.compile(rf"(?i)(?<![\w]){re.escape(alias)}(?![\w])")
        for match in pattern.finditer(text):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in occupied):
                continue
            occupied.append(span)
            hits.append(_Hit(span[0], span[1], place))
    hits.sort(key=lambda item: item.start)
    return hits


def _collapse(hits: list[_Hit]) -> list[_Hit]:
    unique: list[_Hit] = []
    for hit in hits:
        if any(item.place.canonical == hit.place.canonical for item in unique):
            continue
        unique.append(hit)
    return unique


def _single_destination(text: str, hit: _Hit) -> tuple[str | None, Ambiguity | None]:
    end = _qualified_end(text, hit)
    if hit.place.alternatives and end == hit.end:
        return None, _place_ambiguity(hit.place)
    return text[hit.start : end].strip(" ,"), None


def _qualified_end(text: str, hit: _Hit) -> int:
    window = text[hit.end : hit.end + 40]
    best = hit.end
    for qualifier in sorted(hit.place.qualifiers, key=len, reverse=True):
        match = re.search(rf"(?i)^[\s,]*{re.escape(qualifier)}\b", window)
        if match is not None and hit.end + match.end() > best:
            best = hit.end + match.end()
    return best


def _one_phrase(text: str, hits: list[_Hit]) -> bool:
    for earlier, later in pairwise(hits):
        gap = text[earlier.end : later.start]
        if _SPLIT_GAP.search(gap) or _JOIN_GAP.fullmatch(gap) is None:
            return False
    return True


def _place_ambiguity(place: _Place) -> Ambiguity:
    return Ambiguity(
        field=BriefField.destination,
        message="Which place do you mean?",
        candidates=list(place.alternatives),
        blocking=True,
    )


def _date(text: str, today: date) -> tuple[date | None, Ambiguity | None]:
    resolved: list[date] = []
    ambiguous: list[str] = []
    occupied: list[tuple[int, int]] = []

    def take(span: tuple[int, int]) -> bool:
        if any(span[0] < end and start < span[1] for start, end in occupied):
            return False
        occupied.append(span)
        return True

    for match in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text):
        if take(match.span()):
            parsed = _valid_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            if parsed is not None:
                resolved.append(parsed)
    named = (
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({'|'.join(_MONTHS)})\s+(20\d{{2}})\b"
        rf"|\b({'|'.join(_MONTHS)})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b"
    )
    for match in re.finditer(named, text, re.IGNORECASE):
        if not take(match.span()):
            continue
        if match.group(1):
            parsed = _valid_date(
                int(match.group(3)), _MONTHS[match.group(2).lower()], int(match.group(1))
            )
        else:
            parsed = _valid_date(
                int(match.group(6)), _MONTHS[match.group(4).lower()], int(match.group(5))
            )
        if parsed is not None:
            resolved.append(parsed)
    for match in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", text):
        if not take(match.span()):
            continue
        first, second, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if first > 12 and second <= 12:
            parsed = _valid_date(year, second, first)
            if parsed is not None:
                resolved.append(parsed)
        elif second > 12 and first <= 12:
            parsed = _valid_date(year, first, second)
            if parsed is not None:
                resolved.append(parsed)
        elif first <= 12 and second <= 12:
            day_first = _valid_date(year, second, first)
            month_first = _valid_date(year, first, second)
            ambiguous.extend(
                item.isoformat() for item in (day_first, month_first) if item is not None
            )
    for match in re.finditer(r"\b(?:today|tonight|tomorrow)\b", text, re.IGNORECASE):
        if take(match.span()):
            resolved.append(
                today + timedelta(days=1 if match.group(0).lower() == "tomorrow" else 0)
            )
    weekend = re.search(r"\b(?:this\s+)?weekend\b", text, re.IGNORECASE)
    if weekend is not None and take(weekend.span()):
        ambiguous.extend(item.isoformat() for item in _weekend_dates(today))
    weekday = re.compile(
        rf"\b(?:(this|next)\s+)?({'|'.join(_WEEKDAYS)})\b",
        re.IGNORECASE,
    )
    for match in weekday.finditer(text):
        if not take(match.span()):
            continue
        soon = _upcoming(_WEEKDAYS[match.group(2).lower()], today)
        if (match.group(1) or "").lower() == "next":
            ambiguous.extend((soon.isoformat(), (soon + timedelta(days=7)).isoformat()))
        else:
            resolved.append(soon)
    pool = list(dict.fromkeys([*ambiguous, *(item.isoformat() for item in resolved)]))
    if len(pool) > 1:
        return None, Ambiguity(
            field=BriefField.date,
            message="Which date should this evening be?",
            candidates=pool[:6],
            blocking=True,
        )
    if len(pool) == 1:
        return date.fromisoformat(pool[0]), None
    return None, None


def _valid_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _upcoming(weekday: int, today: date) -> date:
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def _weekend_dates(today: date) -> tuple[date, ...]:
    if today.weekday() == 6:
        return (today,)
    saturday = _upcoming(5, today)
    return (saturday, saturday + timedelta(days=1))


def _start_time(text: str) -> tuple[time | None, Ambiguity | None]:
    found: list[tuple[time | None, tuple[str, ...]]] = []
    occupied: list[tuple[int, int]] = []

    def claim(match: re.Match[str], parsed: time | None, choices: tuple[str, ...] = ()) -> None:
        span = match.span()
        if any(span[0] < end and start < span[1] for start, end in occupied):
            return
        occupied.append(span)
        found.append((parsed, choices))

    clock_12 = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE)
    for match in clock_12.finditer(text):
        parsed = _twelve_hour(int(match.group(1)), int(match.group(2) or 0), match.group(3))
        if parsed is not None:
            claim(match, parsed)
    evening = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s+in the evening\b", re.IGNORECASE)
    for match in evening.finditer(text):
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if 1 <= hour <= 11 and minute < 60:
            claim(match, time(hour + 12, minute))
    clock_24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
    for match in clock_24.finditer(text):
        claim(match, time(int(match.group(1)), int(match.group(2))))
    bare = re.compile(r"\b(?:at|from)\s+(\d{1,2})(?::(\d{2}))?\b", re.IGNORECASE)
    for match in bare.finditer(text):
        choices = _ambiguous_clock(int(match.group(1)), int(match.group(2) or 0))
        if choices:
            claim(match, None, choices)
    explicit = [parsed for parsed, _choices in found if parsed is not None]
    labels = [label for _parsed, choices in found for label in choices]
    labels.extend(item.strftime("%H:%M") for item in explicit)
    unique_labels = list(dict.fromkeys(labels))
    if len(unique_labels) > 1 or (labels and not explicit):
        return None, Ambiguity(
            field=BriefField.time,
            message="What time should the evening start?",
            candidates=unique_labels[:6],
            blocking=True,
        )
    if len(explicit) == 1:
        return explicit[0], None
    return None, None


def _ambiguous_clock(hour: int, minute: int) -> tuple[str, ...]:
    if hour < 1 or hour > 12 or minute > 59:
        return ()
    morning = time(0, minute) if hour == 12 else time(hour, minute)
    evening = time(12, minute) if hour == 12 else time(hour + 12, minute)
    return (morning.strftime("%H:%M"), evening.strftime("%H:%M"))


def _twelve_hour(hour: int, minute: int, marker: str) -> time | None:
    if hour < 1 or hour > 12 or minute > 59:
        return None
    if hour == 12:
        hour = 0
    if marker.lower() == "pm":
        hour += 12
    return time(hour, minute)


def _party(text: str) -> tuple[int | None, Ambiguity | None]:
    ranged = re.search(
        r"\b(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s+(?:people|guests|persons)\b",
        text,
        re.IGNORECASE,
    )
    if ranged is not None:
        return None, Ambiguity(
            field=BriefField.party_size,
            message="How many people is the evening for?",
            candidates=[ranged.group(1), ranged.group(2)],
            blocking=False,
        )
    if re.search(
        r"\b(?:a couple of (?:us|people|guests)|the two of us|just us two)\b",
        text,
        re.IGNORECASE,
    ):
        return 2, None
    if re.search(r"\b(?:solo|just me|by myself|on my own)\b", text, re.IGNORECASE):
        return 1, None
    numbered = re.search(
        r"\b(?:for|party of)\s+(\d{1,2})\b|\b(\d{1,2})\s+(?:people|guests|persons)\b",
        text,
        re.IGNORECASE,
    )
    if numbered is not None:
        size = int(numbered.group(1) or numbered.group(2))
        return (size, None) if 1 <= size <= 20 else (None, None)
    words = "|".join(_WORDS)
    spelled = re.search(
        rf"\b(?:for|party of)\s+({words})\b|\b({words})\s+(?:people|guests|of us)\b",
        text,
        re.IGNORECASE,
    )
    if spelled is not None:
        word = (spelled.group(1) or spelled.group(2)).lower()
        return _WORDS[word], None
    if re.search(r"\ba few\b", text, re.IGNORECASE):
        return None, Ambiguity(
            field=BriefField.party_size,
            message="How many people is the evening for?",
            candidates=[],
            blocking=False,
        )
    return None, None


def _budget(text: str) -> tuple[Budget | None, Ambiguity | None]:
    bound = r"under|below|less than|up to|about|around|roughly"
    amount = r"\d{1,7}(?:\.\d{1,2})?"
    code = r"gbp|usd|eur|inr|jpy|cny|rs"
    word = r"pounds?|dollars?|euros?|rupees?|yen|yuan|bucks"
    symbol = r"[£€₹$]"
    patterns = (
        re.compile(
            rf"(?i)\b(?:(?P<bound>{bound})\s+)?(?P<currency>{code})\b\.?\s*(?P<amount>{amount})(?![\d.])"
        ),
        re.compile(
            rf"(?i)(?:(?P<bound>{bound})\s+)?(?P<currency>{symbol})\s*(?P<amount>{amount})(?![\d.])"
        ),
        re.compile(
            rf"(?i)\b(?:(?P<bound>{bound})\s+)?(?P<amount>{amount})(?![\d.])\s*(?P<currency>{word})\b"
        ),
    )
    matches = _unoverlapping(match for pattern in patterns for match in pattern.finditer(text))
    currencies = {_currency_code(match.group("currency")) for match in matches}
    currencies.discard(None)
    if len(currencies) > 1:
        return None, Ambiguity(
            field=BriefField.budget,
            message="Which currency is the budget in?",
            candidates=sorted(code for code in currencies if code is not None),
            blocking=False,
        )
    tier = _tier(text)
    bare_yen = re.search(rf"(?i)¥\s*(?:{amount})(?![\d.])", text)
    if len(matches) == 1:
        match = matches[0]
        currency = _currency_code(match.group("currency"))
        if currency is None:
            return _tier_only(tier)
        return (
            Budget(
                amount=Decimal(match.group("amount")),
                currency=currency,
                tier=tier,
                bound=_bound(match.group("bound")),
            ),
            None,
        )
    if bare_yen is not None and not currencies:
        budget, _note = _tier_only(tier)
        return budget, Ambiguity(
            field=BriefField.budget,
            message="Yen and yuan use the same symbol. Which currency do you mean?",
            candidates=["JPY", "CNY"],
            blocking=False,
        )
    return _tier_only(tier)


def _currency_code(token: str) -> str | None:
    codes = {
        "gbp": "GBP",
        "£": "GBP",
        "pound": "GBP",
        "pounds": "GBP",
        "usd": "USD",
        "$": "USD",
        "dollar": "USD",
        "dollars": "USD",
        "bucks": "USD",
        "eur": "EUR",
        "€": "EUR",
        "euro": "EUR",
        "euros": "EUR",
        "inr": "INR",
        "rs": "INR",
        "rs.": "INR",
        "₹": "INR",
        "rupee": "INR",
        "rupees": "INR",
        "jpy": "JPY",
        "yen": "JPY",
        "cny": "CNY",
        "yuan": "CNY",
    }
    return codes.get(token.lower())


def _unoverlapping(matches: Iterable[re.Match[str]]) -> list[re.Match[str]]:
    ordered = sorted(matches, key=lambda match: (match.start(), -(match.end() - match.start())))
    kept: list[re.Match[str]] = []
    occupied: list[tuple[int, int]] = []
    for match in ordered:
        span = match.span()
        if any(span[0] < end and start < span[1] for start, end in occupied):
            continue
        occupied.append(span)
        kept.append(match)
    return kept


def _tier(text: str) -> BudgetTier | None:
    if re.search(r"\b(?:cheap|inexpensive|low-cost|on a budget)\b", text, re.IGNORECASE):
        return BudgetTier.low
    if re.search(r"\b(?:mid-range|moderate|reasonably priced)\b", text, re.IGNORECASE):
        return BudgetTier.moderate
    if re.search(r"\b(?:expensive|upscale|fancy|high-end|splurge)\b", text, re.IGNORECASE):
        return BudgetTier.high
    return None


def _tier_only(tier: BudgetTier | None) -> tuple[Budget | None, Ambiguity | None]:
    if tier is None:
        return None, None
    return Budget(tier=tier), None


def _bound(word: str | None) -> BudgetBound:
    if word is None:
        return BudgetBound.exact
    if word.lower() in {"about", "around", "roughly"}:
        return BudgetBound.about
    return BudgetBound.at_most


def _intents(text: str) -> tuple[list[PlaceIntent], Ambiguity | None]:
    found: list[tuple[int, IntentKind, str]] = []
    for kind, pattern in _INTENTS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match is not None:
            found.append((match.start(), kind, match.group(0)))
    found.sort(key=lambda item: item[0])
    chosen = found[:2]
    intents = [
        PlaceIntent(kind=kind, label=label.casefold(), position=index)
        for index, (_start, kind, label) in enumerate(chosen, start=1)
    ]
    if len(found) <= 2:
        return intents, None
    return intents, Ambiguity(
        field=BriefField.intents,
        message="This evening keeps two stops. Later activities were left unplanned.",
        candidates=[label.casefold() for _start, _kind, label in found[2:6]],
        blocking=False,
    )


def _phrases(text: str, table: tuple[tuple[str, str], ...]) -> list[str]:
    found: list[tuple[int, str]] = []
    for pattern, label in table:
        match = re.search(pattern, text, re.IGNORECASE)
        if match is not None:
            found.append((match.start(), label))
    found.sort(key=lambda item: item[0])
    return list(dict.fromkeys(label for _start, label in found))


def _missing(
    *,
    destination: str | None,
    local_date: date | None,
    local_start: time | None,
    intents: list[PlaceIntent],
    ambiguities: list[Ambiguity],
) -> list[MissingField]:
    blocked = {item.field for item in ambiguities if item.blocking}
    present = {
        EssentialField.destination: destination is not None,
        EssentialField.date: local_date is not None,
        EssentialField.time: local_start is not None,
        EssentialField.primary_intent: bool(intents),
    }
    fields = {
        EssentialField.destination: BriefField.destination,
        EssentialField.date: BriefField.date,
        EssentialField.time: BriefField.time,
        EssentialField.primary_intent: BriefField.primary_intent,
    }
    return [
        question_for(essential)
        for essential, filled in present.items()
        if not filled and fields[essential] not in blocked
    ]


def _confidence(
    destination: str | None,
    local_date: date | None,
    local_start: time | None,
    intents: list[PlaceIntent],
) -> BriefConfidence:
    score = sum(
        (
            destination is not None,
            local_date is not None,
            local_start is not None,
            bool(intents),
        )
    )
    if score == 4:
        return BriefConfidence.high
    if score >= 2:
        return BriefConfidence.medium
    if score == 1:
        return BriefConfidence.low
    return BriefConfidence.insufficient
