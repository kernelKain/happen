"""Strict planning records. Unsupported prompt text is not stored as a fact."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_PROMPT_LENGTH = 2000
_CURRENCY = r"^[A-Z]{3}$"
_HTTP = r"^https?://"


class EssentialField(StrEnum):
    destination = "destination"
    date = "date"
    time = "time"
    primary_intent = "primary_intent"


class BriefField(StrEnum):
    destination = "destination"
    date = "date"
    time = "time"
    primary_intent = "primary_intent"
    party_size = "party_size"
    budget = "budget"
    intents = "intents"


class IntentKind(StrEnum):
    dinner = "dinner"
    drinks = "drinks"
    coffee = "coffee"
    dessert = "dessert"
    show = "show"
    walk = "walk"
    live_music = "live_music"
    museum = "museum"


class BudgetTier(StrEnum):
    low = "low"
    moderate = "moderate"
    high = "high"


class BudgetBound(StrEnum):
    exact = "exact"
    at_most = "at_most"
    about = "about"


class BriefConfidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    insufficient = "insufficient"


class LivePlanOutcome(StrEnum):
    needs_follow_up = "needs_follow_up"
    ready_for_retrieval = "ready_for_retrieval"


class DatePhrase(StrEnum):
    """A date the prompt stated relative to the destination's local day."""

    today = "today"
    tonight = "tonight"
    tomorrow = "tomorrow"
    weekday = "weekday"
    next_weekday = "next_weekday"
    weekend = "weekend"


class ResolutionSource(StrEnum):
    """Which SerpApi call supplied the coordinates that were kept."""

    locations_api = "locations_api"
    maps_lookup = "maps_lookup"


class PlanningErrorCode(StrEnum):
    prompt_empty = "PROMPT_EMPTY"
    prompt_too_large = "PROMPT_TOO_LARGE"
    prompt_invalid = "PROMPT_INVALID"


def _reject_controls(value: str) -> str:
    for char in value:
        code = ord(char)
        if code < 32 and char not in "\n\t\r":
            raise ValueError("prompt contains unsupported characters")
        if code == 127:
            raise ValueError("prompt contains unsupported characters")
    return value


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


def _iana(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone_name must be an IANA zone") from exc
    return value


def _coordinate(value: float | None, *, minimum: float, maximum: float, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"{name} is out of range")
    return float(value)


class PlanningUserError(BaseModel):
    """User-safe planning error. The message never includes the prompt or a traceback."""

    model_config = ConfigDict(extra="forbid")

    code: PlanningErrorCode
    message: str = Field(min_length=1, max_length=200)
    retryable: bool
    next_action: str = Field(min_length=1, max_length=200)


class PlanningInputError(Exception):
    """Raised when a prompt cannot be accepted. The string form is the public code only."""

    def __init__(self, error: PlanningUserError) -> None:
        super().__init__(error.code.value)
        self.error = error


class PlanningPromptRequest(BaseModel):
    """One untrusted evening prompt. The text is data, not application instructions."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)

    @field_validator("prompt")
    @classmethod
    def _prompt_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt is empty")
        return _reject_controls(value)


class Budget(BaseModel):
    """Stated money or a stated price tier. A missing amount stays absent."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    currency: str | None = Field(default=None, pattern=_CURRENCY)
    tier: BudgetTier | None = None
    bound: BudgetBound | None = None

    @field_validator("amount")
    @classmethod
    def _cents(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            raise ValueError("amount keeps at most two decimal places")
        return value

    @model_validator(mode="after")
    def _amount_has_currency(self) -> Budget:
        if (self.amount is None) != (self.currency is None):
            raise ValueError("amount and currency are set together")
        if self.amount is None and self.bound is not None:
            raise ValueError("a bound requires an amount")
        if self.amount is not None and self.bound is None:
            raise ValueError("an amount requires a bound")
        if self.amount is None and self.tier is None:
            raise ValueError("a budget needs an amount or a tier")
        return self


class PlaceIntent(BaseModel):
    """One evening activity. A brief holds at most two of these."""

    model_config = ConfigDict(extra="forbid")

    kind: IntentKind
    label: str = Field(min_length=1, max_length=40)
    position: int = Field(ge=1, le=2)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        return _reject_controls(value)


class MissingField(BaseModel):
    """One essential fact the prompt did not state."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["missing"] = "missing"
    field: EssentialField
    question: str = Field(min_length=1, max_length=200)


class Ambiguity(BaseModel):
    """One phrase that matches more than one fact. Candidates are choices, not a plan."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["ambiguity"] = "ambiguity"
    field: BriefField
    message: str = Field(min_length=1, max_length=200)
    candidates: list[str] = Field(default_factory=list, max_length=6)
    blocking: bool

    @field_validator("candidates")
    @classmethod
    def _candidates(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            if len(item) > 80:
                raise ValueError("candidate text is too long")
            cleaned.append(_reject_controls(item))
        return cleaned


FollowUp = Annotated[MissingField | Ambiguity, Field(discriminator="kind")]


class PendingDate(BaseModel):
    """A relative date. It becomes a calendar date only after a destination zone is known."""

    model_config = ConfigDict(extra="forbid")

    phrase: DatePhrase
    weekday: int | None = Field(default=None, ge=0, le=6)

    @model_validator(mode="after")
    def _weekday_matches_phrase(self) -> PendingDate:
        needs_weekday = self.phrase in {DatePhrase.weekday, DatePhrase.next_weekday}
        if needs_weekday and self.weekday is None:
            raise ValueError("a weekday phrase names a weekday")
        if not needs_weekday and self.weekday is not None:
            raise ValueError("only a weekday phrase names a weekday")
        return self


class SourceProvenance(BaseModel):
    """Where a shown place fact came from, and when it was retrieved."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["serpapi"]
    source_url: str = Field(min_length=8, max_length=500, pattern=_HTTP)
    retrieved_at: datetime
    label: str = Field(min_length=1, max_length=120)

    @field_validator("retrieved_at")
    @classmethod
    def _retrieved(cls, value: datetime) -> datetime:
        return _aware(value)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        return _reject_controls(value)


class ResolvedDestination(BaseModel):
    """One canonical place. Coordinates stay empty when the provider did not supply them."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    source_text: str = Field(min_length=1, max_length=120)
    locality: str | None = Field(default=None, max_length=80)
    region: str | None = Field(default=None, max_length=80)
    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    timezone_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    serpapi_location: str | None = Field(default=None, max_length=120)
    confidence: BriefConfidence | None = None
    resolution_source: ResolutionSource | None = None
    provenance: SourceProvenance | None = None

    @field_validator("timezone_name")
    @classmethod
    def _zone(cls, value: str | None) -> str | None:
        return _iana(value)

    @field_validator("latitude")
    @classmethod
    def _latitude(cls, value: float | None) -> float | None:
        return _coordinate(value, minimum=-90, maximum=90, name="latitude")

    @field_validator("longitude")
    @classmethod
    def _longitude(cls, value: float | None) -> float | None:
        return _coordinate(value, minimum=-180, maximum=180, name="longitude")

    @field_validator("locality", "region", "serpapi_location")
    @classmethod
    def _place_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _reject_controls(value)

    @model_validator(mode="after")
    def _coordinates_together(self) -> ResolvedDestination:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude are set together")
        return self


class LocalDateTimeWindow(BaseModel):
    """Destination-local date and start. The zone stays empty until a destination is resolved."""

    model_config = ConfigDict(extra="forbid")

    local_date: date
    start_time: time
    end_time: time | None = None
    timezone_name: str | None = None

    @field_validator("timezone_name")
    @classmethod
    def _zone(cls, value: str | None) -> str | None:
        return _iana(value)

    @model_validator(mode="after")
    def _end_after_start(self) -> LocalDateTimeWindow:
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time on the same date")
        return self


class PlaceOption(BaseModel):
    """A retrieved place. It cannot exist without source provenance."""

    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    provenance: SourceProvenance
    unknown_fields: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("unknown_fields")
    @classmethod
    def _unknown(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item.isidentifier() or len(item) > 40:
                raise ValueError("unknown field names are short identifiers")
        return value


class ItineraryStop(BaseModel):
    """One stop. A plan has at most two."""

    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=1, le=2)
    intent: PlaceIntent
    place: PlaceOption | None = None
    window: LocalDateTimeWindow | None = None
    unknown_fields: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("unknown_fields")
    @classmethod
    def _unknown(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item.isidentifier() or len(item) > 40:
                raise ValueError("unknown field names are short identifiers")
        return value


class PlanningBrief(BaseModel):
    """Editable reading of one prompt. Absent facts stay null or unknown."""

    model_config = ConfigDict(extra="forbid")

    raw_prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    destination_text: str | None = Field(default=None, max_length=120)
    local_date: date | None = None
    pending_date: PendingDate | None = None
    local_start: time | None = None
    party_size: int | None = Field(default=None, ge=1, le=20)
    budget: Budget | None = None
    intents: list[PlaceIntent] = Field(default_factory=list, max_length=2)
    preferences: list[str] = Field(default_factory=list, max_length=8)
    accessibility_needs: list[str] = Field(default_factory=list, max_length=8)
    missing_essentials: list[MissingField] = Field(default_factory=list, max_length=4)
    ambiguities: list[Ambiguity] = Field(default_factory=list, max_length=8)
    confidence: BriefConfidence

    @field_validator("raw_prompt", "destination_text")
    @classmethod
    def _text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _reject_controls(value)

    @field_validator("preferences", "accessibility_needs")
    @classmethod
    def _phrases(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item or len(item) > 40:
                raise ValueError("preference text is too long")
            _reject_controls(item)
        return value

    @model_validator(mode="after")
    def _intent_order(self) -> PlanningBrief:
        positions = [item.position for item in self.intents]
        expected = list(range(1, len(positions) + 1))
        if positions != expected:
            raise ValueError("intent positions must be 1..n in order")
        return self


class LivePlanResponse(BaseModel):
    """A user-facing plan shell. This layer leaves stops empty until live retrieval."""

    model_config = ConfigDict(extra="forbid")

    outcome: LivePlanOutcome
    brief: PlanningBrief
    destination: ResolvedDestination | None = None
    stops: list[ItineraryStop] = Field(default_factory=list, max_length=2)
    follow_up: FollowUp | None = None
    warnings: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("warnings")
    @classmethod
    def _warnings(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item or len(item) > 200:
                raise ValueError("warning text is too long")
        return value

    @model_validator(mode="after")
    def _one_question_and_two_stops(self) -> LivePlanResponse:
        if self.outcome is LivePlanOutcome.needs_follow_up and self.follow_up is None:
            raise ValueError("a follow-up outcome includes one question")
        if self.outcome is LivePlanOutcome.ready_for_retrieval and self.follow_up is not None:
            raise ValueError("a ready brief does not include a follow-up question")
        positions = [item.position for item in self.stops]
        if len(positions) != len(set(positions)):
            raise ValueError("stop positions must be unique")
        return self
