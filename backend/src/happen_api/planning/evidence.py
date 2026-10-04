"""One normalized supporting claim with its provenance.

Every statement shown to the user passes through here first. A claim keeps the
kind of source it came from, what it supports, the exact safe URL that carried
it, how the entity was matched, and whether it is verified. Nothing is shown
without a kind, a field, and a retrieval timestamp.

A community statement is never treated as a fact. It becomes a conflict only
when deterministic normalization shows it claims something incompatible with
the official record; otherwise it stays secondary, unverified context.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ClaimKind(StrEnum):
    """Where the statement came from."""

    maps = "maps"
    official = "official"
    community = "community"


class ClaimField(StrEnum):
    """What the statement supports."""

    hours = "hours"
    place_identity = "place_identity"
    constraint = "constraint"
    contact = "contact"
    description = "description"
    provenance = "provenance"


class MatchMethod(StrEnum):
    """How the statement was tied to this place."""

    provider_id = "provider_id"
    official_domain = "official_domain"
    name_and_location = "name_and_location"
    place_record = "place_record"
    review_text = "review_text"
    none_found = "none_found"


class Verification(StrEnum):
    """How far the claim has been checked."""

    verified = "verified"
    unverified = "unverified"
    conflicting = "conflicting"


_UNSAFE_SCHEMES = frozenset(
    {
        "file",
        "ftp",
        "ftps",
        "data",
        "javascript",
        "vbscript",
        "about",
        "blob",
        "ws",
        "wss",
    }
)
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "[::1]", "::1"})
_CREDENTIAL_PARAMS = ("api_key", "apikey", "key", "token", "access_token", "secret", "password")


def safe_link(value: object) -> HttpUrl | None:
    """Return a link only when it is a public http(s) URL with no credentials.

    A local path, a non-HTTP scheme, or a URL carrying an API key is not linked.
    Returning None is the safe answer, not an error.
    """

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    parsed = urlsplit(text)
    if parsed.scheme.casefold() not in {"http", "https"}:
        return None
    if not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    host = parsed.hostname.casefold()
    if host in _LOCAL_HOSTS or host.endswith((".local", ".internal")):
        return None
    if any(param.casefold() in _CREDENTIAL_PARAMS for param in _query_keys(parsed.query)):
        return None
    try:
        return HttpUrl(text)
    except ValueError:
        return None


def safe_link_text(value: object) -> str | None:
    """Return the exact original URL when it is safe to link, else None."""

    link = safe_link(value)
    return str(link) if link is not None else None


def _query_keys(query: str) -> list[str]:
    return [part.split("=", 1)[0] for part in query.split("&") if part]


class EvidenceClaim(BaseModel):
    """One supporting statement, traceable to where it came from."""

    model_config = ConfigDict(extra="forbid")

    kind: ClaimKind
    field: ClaimField
    text: str = Field(min_length=1, max_length=300)
    url: HttpUrl | None = None
    retrieved_at: datetime
    matched_by: MatchMethod = MatchMethod.none_found
    verification: Verification = Verification.unverified

    @property
    def linked(self) -> bool:
        """Whether this claim carries a safe, linkable source."""

        return self.url is not None


class ClaimsConflict(BaseModel):
    """Two normalized claims about one field that cannot both be true."""

    model_config = ConfigDict(extra="forbid")

    field: ClaimField
    official: EvidenceClaim
    secondary: EvidenceClaim

    @property
    def resolved(self) -> EvidenceClaim:
        """The official record wins, because it is the normalized source."""

        return self.official
