"""Map SerpApi documents into place records and choose three candidates.

Missing hours, busyness, or reviews stay missing. They are not filled in.
A place is eligible only when the provider shows a restaurant name, a usable
place id, and a provenance URL. Evidence completeness outranks search order.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from happen_api.catalog import CATEGORIES
from happen_api.domain.models import (
    BusynessObservation,
    DayOfWeek,
    NormalizedPlace,
    ReviewExcerpt,
)
from happen_api.domain.timing import parse_hours_for_visit

_RESTAURANT_CATEGORY = CATEGORIES[0]
_EXCERPT_LIMIT = 3
_EXCERPT_CHARACTERS = 400
_PLACE_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_HOUR = re.compile(
    r"^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>am|pm)?$",
    re.IGNORECASE,
)
_DAYS = {day.value: day for day in DayOfWeek}
_REJECTION_ORDER = (
    "invalid_place",
    "missing_name",
    "missing_provider_id",
    "provider_id_unusable",
    "missing_source_url",
    "category_unknown",
    "category_not_restaurant",
    "hours_closed",
    "duplicate_place",
)
_MAPS_HOSTS = {"google.com", "www.google.com", "maps.google.com", "www.maps.google.com"}


class CandidateSelection(BaseModel):
    """Three normalized restaurants, or an insufficiency result with no places."""

    model_config = ConfigDict(extra="forbid")

    places: list[NormalizedPlace] = Field(max_length=3)
    reason_codes: list[str] = Field(min_length=1, max_length=12)


@dataclass(frozen=True)
class _Prepared:
    index: int
    completeness: int
    name: str
    provider_id: str
    place: NormalizedPlace


def select_candidates(
    search_payload: dict[str, object],
    place_payloads: list[dict[str, object]] | None = None,
    review_payloads: list[dict[str, object]] | None = None,
    *,
    visit_date: date,
    captured_at: datetime,
) -> CandidateSelection:
    """Choose three candidates from one search and any details already fetched.

    When place payloads are supplied, only search rows that match those
    payloads can be selected. That keeps the choice inside the fetched shortlist.
    """

    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    rows = _search_rows(search_payload)
    if rows is None:
        return CandidateSelection(places=[], reason_codes=["invalid_search"])
    if not rows:
        return CandidateSelection(places=[], reason_codes=["empty_search"])

    details = _index_place_details(place_payloads or [])
    reviews = _index_review_lists(review_payloads or [])
    prepared: list[_Prepared] = []
    rejections: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            rejections.append("invalid_place")
            continue
        detail = _detail_for(row, details)
        if place_payloads and detail is None:
            continue
        merged = _overlay(row, detail)
        extra_reviews = _reviews_for(merged, reviews)
        result = _prepare_place(
            merged,
            extra_reviews=extra_reviews,
            index=index,
            visit_date=visit_date,
            captured_at=captured_at,
        )
        if isinstance(result, str):
            rejections.append(result)
            continue
        if result.provider_id in seen:
            rejections.append("duplicate_place")
            continue
        seen.add(result.provider_id)
        prepared.append(result)

    prepared.sort(key=_rank)
    if len(prepared) < 3:
        if place_payloads and not _any_detail_matched(rows, details):
            rejections.append("unmatched_place_details")
        return _insufficient(rejections)
    chosen = [
        item.place.model_copy(update={"eligibility_reasons": ["eligible"]}) for item in prepared[:3]
    ]
    return CandidateSelection(places=chosen, reason_codes=["three_candidates"])


def _search_rows(payload: dict[str, object]) -> list[object] | None:
    rows = payload.get("local_results")
    if isinstance(rows, list):
        return rows
    return None


def _rank(item: _Prepared) -> tuple[int, int, str, str]:
    return (-item.completeness, item.index, item.name.casefold(), item.provider_id)


def _any_detail_matched(rows: list[object], details: dict[str, dict[str, object]]) -> bool:
    return any(isinstance(row, dict) and _detail_for(row, details) is not None for row in rows)


def _insufficient(rejections: list[str]) -> CandidateSelection:
    codes = ["insufficient_candidates"]
    codes.extend(code for code in _REJECTION_ORDER if code in rejections)
    if "unmatched_place_details" in rejections:
        codes.append("unmatched_place_details")
    return CandidateSelection(places=[], reason_codes=codes)


def _prepare_place(
    record: dict[str, object],
    *,
    extra_reviews: list[dict[str, object]],
    index: int,
    visit_date: date,
    captured_at: datetime,
) -> _Prepared | str:
    name = _name(record)
    if name is None:
        return "missing_name"
    provider_id = _provider_id(record)
    if provider_id is None:
        return "missing_provider_id" if not _raw_id(record) else "provider_id_unusable"
    source_url = _source_url(record, provider_id)
    if source_url is None:
        return "missing_source_url"
    category = _restaurant_category(record)
    if category is None:
        return "category_unknown"
    if not category:
        return "category_not_restaurant"

    warnings: list[str] = []
    if len(name) > 120:
        name = name[:120]
        warnings.append("name_truncated")
    intervals, hour_code = _opening_intervals(
        record,
        visit_date=visit_date,
        source_url=source_url,
    )
    if hour_code == "hours_closed":
        return "hours_closed"
    if hour_code is not None:
        warnings.append(hour_code)
    busyness = _busyness(
        record,
        visit_date=visit_date,
        source_url=source_url,
        captured_at=captured_at,
    )
    if not busyness:
        warnings.append("missing_busyness")
    excerpts = _excerpts(
        record,
        extra_reviews,
        candidate_id=provider_id,
        source_url=source_url,
        captured_at=captured_at,
    )
    if not excerpts:
        warnings.append("missing_reviews")
    place = NormalizedPlace(
        candidate_id=provider_id,
        provider_place_id=provider_id,
        name=name,
        category_tags=[_RESTAURANT_CATEGORY],
        source_url=source_url,
        opening_intervals=intervals,
        busyness_observations=busyness,
        review_excerpts=excerpts,
        eligibility_reasons=["eligible"],
        warnings=warnings[:8],
    )
    completeness = int(bool(intervals)) + int(bool(busyness)) + int(bool(excerpts))
    return _Prepared(
        index=index,
        completeness=completeness,
        name=name,
        provider_id=provider_id,
        place=place,
    )


def _name(record: dict[str, object]) -> str | None:
    for key in ("title", "name"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return None


def _raw_id(record: dict[str, object]) -> str:
    for key in ("place_id", "data_id"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _provider_id(record: dict[str, object]) -> str | None:
    for key in ("place_id", "data_id"):
        value = record.get(key)
        if isinstance(value, str):
            cleaned = value.strip()
            if 1 <= len(cleaned) <= 80 and _safe_text(cleaned):
                return cleaned
    return None


def _source_url(record: dict[str, object], provider_id: str) -> str | None:
    for key in ("google_maps_url", "maps_url"):
        found = _maps_url(record.get(key))
        if found is not None:
            return found
    if _PLACE_ID.fullmatch(provider_id):
        return "https://www.google.com/maps/search/?api=1&query_place_id=" + quote(
            provider_id, safe=""
        )
    return None


def _maps_url(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return None
    if parsed.hostname not in _MAPS_HOSTS:
        return None
    if "api_key" in parsed.query.casefold():
        return None
    return value.strip()


def _restaurant_category(record: dict[str, object]) -> bool | None:
    labels: list[str] = []
    for key in ("type", "types"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            labels.append(value)
        elif isinstance(value, list):
            labels.extend(item for item in value if isinstance(item, str) and item.strip())
    if not labels:
        return None
    return any("restaurant" in label.casefold() for label in labels)


def _opening_intervals(
    record: dict[str, object],
    *,
    visit_date: date,
    source_url: str,
) -> tuple[list, str | None]:
    entries = _hour_entries(record)
    if not entries:
        return [], "hours_missing"
    try:
        parsed = parse_hours_for_visit(entries, visit_date=visit_date, source_url=source_url)
    except ValueError:
        return [], "hours_unparseable"
    if parsed.status == "closed":
        return [], "hours_closed"
    if parsed.status != "verified":
        return [], "hours_unparseable"
    return parsed.intervals, None


def _hour_entries(record: dict[str, object]) -> list[dict[str, str]]:
    hours = record.get("hours")
    if isinstance(hours, list):
        entries = [item for item in hours if isinstance(item, dict)]
        return [_string_mapping(item) for item in entries if _string_mapping(item)]
    operating = record.get("operating_hours")
    if isinstance(operating, dict):
        mapped = _string_mapping(operating)
        return [{day: text} for day, text in mapped.items()]
    return []


def _string_mapping(value: dict[object, object]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, str) and key.strip() and item.strip():
            mapped[key.strip()] = item.strip()
    return mapped


def _busyness(
    record: dict[str, object],
    *,
    visit_date: date,
    source_url: str,
    captured_at: datetime,
) -> list[BusynessObservation]:
    popular = record.get("popular_times")
    day = DayOfWeek(visit_date.strftime("%A").lower())
    points = _popular_points(popular, day)
    observations: list[BusynessObservation] = []
    seen_hours: set[time] = set()
    for hour_start, popularity in sorted(points, key=lambda item: item[0]):
        if hour_start in seen_hours:
            continue
        seen_hours.add(hour_start)
        observations.append(
            BusynessObservation(
                day_of_week=day,
                hour_start=hour_start,
                relative_popularity=popularity,
                source_url=source_url,
                captured_at=captured_at,
            )
        )
        if len(observations) == 24:
            break
    return observations


def _popular_points(popular: object, day: DayOfWeek) -> list[tuple[time, int]]:
    if isinstance(popular, dict):
        graph = popular.get("graph_results")
        if not isinstance(graph, dict):
            return []
        return _points_for_day(_graph_day(graph, day))
    if isinstance(popular, list):
        points: list[tuple[time, int]] = []
        for entry in popular:
            if not isinstance(entry, dict):
                continue
            entry_day = _day_name(entry.get("day"))
            if entry_day is not day:
                continue
            hours = entry.get("hours")
            points.extend(_points_for_day(hours))
        return points
    return []


def _graph_day(graph: dict[object, object], day: DayOfWeek) -> object:
    for key, value in graph.items():
        if isinstance(key, str) and key.strip().casefold() == day.value:
            return value
    return None


def _points_for_day(value: object) -> list[tuple[time, int]]:
    if not isinstance(value, list):
        return []
    points: list[tuple[time, int]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        hour_start = _hour_start(item)
        popularity = _popularity(item)
        if hour_start is None or popularity is None:
            continue
        points.append((hour_start, popularity))
    return points


def _hour_start(item: dict[str, object]) -> time | None:
    if "hour" in item and "time" not in item:
        return _hour_number(item.get("hour"))
    return _hour_text(item.get("time"))


def _hour_number(value: object) -> time | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if 0 <= value <= 23:
        return time(value, 0)
    return None


def _hour_text(value: object) -> time | None:
    if not isinstance(value, str):
        return None
    match = _HOUR.fullmatch(value.strip())
    if match is None:
        return None
    minute = int(match.group("minute") or 0)
    if minute != 0:
        return None
    hour = int(match.group("hour"))
    meridiem = match.group("meridiem")
    if meridiem is None:
        if 0 <= hour <= 23:
            return time(hour, 0)
        return None
    if not 1 <= hour <= 12:
        return None
    if hour == 12:
        hour = 0
    if meridiem.casefold() == "pm":
        hour += 12
    return time(hour, 0)


def _popularity(item: dict[str, object]) -> int | None:
    for key in ("busyness_score", "percentage"):
        parsed = _whole_number(item.get(key))
        if parsed is not None:
            return parsed
    return None


def _whole_number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        return None
    if 0 <= number <= 100:
        return number
    return None


def _day_name(value: object) -> DayOfWeek | None:
    if not isinstance(value, str):
        return None
    return _DAYS.get(value.strip().casefold())


def _excerpts(
    record: dict[str, object],
    extra_reviews: list[dict[str, object]],
    *,
    candidate_id: str,
    source_url: str,
    captured_at: datetime,
) -> list[ReviewExcerpt]:
    seen: set[str] = set()
    excerpts: list[ReviewExcerpt] = []
    for review in [*_user_reviews(record), *extra_reviews]:
        excerpt = _excerpt(
            review,
            candidate_id=candidate_id,
            source_url=source_url,
            captured_at=captured_at,
        )
        if excerpt is None or excerpt.text in seen:
            continue
        seen.add(excerpt.text)
        excerpts.append(excerpt)
        if len(excerpts) == _EXCERPT_LIMIT:
            break
    return excerpts


def _user_reviews(record: dict[str, object]) -> list[dict[str, object]]:
    raw = record.get("user_reviews")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        collected: list[dict[str, object]] = []
        for key in ("most_relevant", "reviews"):
            collected.extend(_dict_items(raw.get(key)))
        return collected
    return []


def _excerpt(
    review: dict[str, object],
    *,
    candidate_id: str,
    source_url: str,
    captured_at: datetime,
) -> ReviewExcerpt | None:
    if not _english(review.get("language", review.get("lang"))):
        return None
    text = _review_text(review)
    if text is None:
        return None
    truncated = len(text) > _EXCERPT_CHARACTERS
    if truncated:
        text = text[:_EXCERPT_CHARACTERS]
    link = _review_link(review) or source_url
    digest = hashlib.sha256(f"{candidate_id}\n{text}".encode()).hexdigest()[:16]
    return ReviewExcerpt(
        excerpt_id=f"ex-{digest}",
        candidate_id=candidate_id,
        text=text,
        published_at=_published_at(review),
        captured_at=captured_at,
        source_url=link,
        language="en",
        truncated=truncated,
    )


def _review_text(review: dict[str, object]) -> str | None:
    extracted = review.get("extracted_snippet")
    candidates: list[object] = []
    if isinstance(extracted, dict):
        candidates.extend(extracted.get(key) for key in ("original", "snippet"))
    candidates.extend(review.get(key) for key in ("snippet", "text", "description"))
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        flattened = " ".join(candidate.replace("\t", " ").split())
        if not flattened or any(ord(char) < 32 for char in flattened):
            continue
        return flattened
    return None


def _english(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return value.strip().casefold() in {"", "en", "en-us", "english"}


def _review_link(review: dict[str, object]) -> str | None:
    for key in ("link", "source", "review_link"):
        value = review.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        parsed = urlsplit(value.strip())
        host = parsed.hostname or ""
        if (
            parsed.scheme not in {"http", "https"}
            or host == "serpapi.com"
            or host.endswith(".serpapi.com")
        ):
            continue
        if parsed.username or "api_key" in parsed.query.casefold():
            continue
        return value.strip()
    return None


def _published_at(review: dict[str, object]) -> date | None:
    for key in ("iso_date", "published_at", "date"):
        value = review.get(key)
        if not isinstance(value, str):
            continue
        text = value.strip()
        if len(text) < 10 or text[4] != "-" or text[7] != "-":
            continue
        if len(text) > 10 and not text[10:].startswith("T"):
            continue
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            continue
    return None


def _dict_items(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _index_place_details(payloads: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    for payload in payloads:
        body = payload.get("place_results")
        record = body if isinstance(body, dict) else payload
        if not isinstance(record, dict):
            continue
        for identifier in _index_ids(payload) | _index_ids(record):
            indexed.setdefault(identifier, record)
    return indexed


def _index_review_lists(payloads: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    indexed: dict[str, list[dict[str, object]]] = {}
    for payload in payloads:
        reviews = _dict_items(payload.get("reviews"))
        if not reviews:
            continue
        for identifier in _index_ids(payload):
            indexed.setdefault(identifier, [])
            indexed[identifier].extend(reviews)
    return indexed


def _index_ids(record: dict[str, object]) -> set[str]:
    identifiers: set[str] = set()
    parameters = record.get("search_parameters")
    sources = [record]
    if isinstance(parameters, dict):
        sources.append(parameters)
    for source in sources:
        for key in ("place_id", "data_id"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                identifiers.add(value.strip())
    return identifiers


def _detail_for(
    row: dict[str, object], details: dict[str, dict[str, object]]
) -> dict[str, object] | None:
    for identifier in _index_ids(row):
        found = details.get(identifier)
        if found is not None:
            return found
    return None


def _reviews_for(
    record: dict[str, object],
    reviews: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    collected: list[dict[str, object]] = []
    for identifier in _index_ids(record):
        collected.extend(reviews.get(identifier, []))
    return collected


def _overlay(row: dict[str, object], detail: dict[str, object] | None) -> dict[str, object]:
    if detail is None:
        return row
    merged = dict(row)
    for key, value in detail.items():
        if _present(value):
            merged[key] = value
    return merged


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _safe_text(value: str) -> bool:
    return all(ord(char) >= 32 for char in value)
