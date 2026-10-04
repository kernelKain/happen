"""Process settings. Secret values stay out of logs, responses, and repr."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    Field,
    SecretStr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"
_MANIFEST_PATH = _REPO_ROOT / "ml" / "model-manifest.json"


def _model_defaults() -> dict[str, str]:
    """Read model identity from the manifest, using empty defaults if it is absent."""

    if not _MANIFEST_PATH.is_file():
        return {"repo": "", "revision": "", "filename": "", "sha256": ""}
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        "repo": str(manifest["huggingface_repo"]),
        "revision": str(manifest["revision"]),
        "filename": str(manifest["filename"]),
        "sha256": str(manifest["sha256"]),
    }


_MODEL = _model_defaults()

AppEnv = Literal["development", "production"]
LogLevel = Literal["debug", "info", "warning", "error"]


def _origin(value: str, *, app_env: AppEnv) -> str:
    """Normalize an exact CORS origin or raise ValueError if the environment forbids it."""

    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("CORS origin must be an absolute http or https origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("CORS origin must not include credentials, a query, or a fragment")
    if parsed.path not in {"", "/"} or "*" in value:
        raise ValueError("CORS origin must be an exact origin without a path or wildcard")
    host = parsed.hostname
    local = host in {"localhost", "127.0.0.1"}
    if app_env == "production":
        if parsed.scheme != "https" or local:
            raise ValueError("Production CORS allows only the exact https frontend origin")
    elif not local:
        raise ValueError("Development CORS allows only local origins")
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{host}{port}"


class Settings(BaseSettings):
    """Runtime configuration loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE if _ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
        populate_by_name=True,
    )

    app_env: AppEnv = Field(default="development", alias="APP_ENV")
    cors_allowed_origins: str = Field(
        default="http://127.0.0.1:5173",
        alias="CORS_ALLOWED_ORIGINS",
    )
    hf_model_repo: str = Field(default=_MODEL["repo"], alias="HF_MODEL_REPO", min_length=1)
    hf_model_revision: str = Field(
        default=_MODEL["revision"],
        alias="HF_MODEL_REVISION",
        min_length=1,
    )
    model_filename: str = Field(default=_MODEL["filename"], alias="MODEL_FILENAME", min_length=1)
    model_sha256: str = Field(
        default=_MODEL["sha256"],
        alias="MODEL_SHA256",
        pattern=r"^[0-9a-f]{64}$",
    )
    happen_live_enabled: bool = Field(default=False, alias="HAPPEN_LIVE_ENABLED")
    log_level: LogLevel = Field(default="info", alias="LOG_LEVEL")
    serpapi_api_key: SecretStr = Field(alias="SERPAPI_API_KEY", default=SecretStr(""), repr=False)
    hf_token: SecretStr = Field(alias="HF_TOKEN", default=SecretStr(""), repr=False)

    @field_validator("log_level", mode="before")
    @classmethod
    def lowercase_level(cls, value: object) -> object:
        """Normalize string log levels before validating the supported values."""

        if isinstance(value, str):
            return value.lower()
        return value

    @field_validator("model_sha256", mode="before")
    @classmethod
    def lowercase_checksum(cls, value: object) -> object:
        """Normalize string checksums before validating their hexadecimal format."""

        if isinstance(value, str):
            return value.lower()
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def parse_origins(cls, value: str, info: ValidationInfo) -> str:
        """Validate and normalize a nonempty comma-separated list of unique origins."""

        app_env = info.data.get("app_env")
        if app_env not in {"development", "production"}:
            raise ValueError("APP_ENV must be development or production")
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if not parts:
            raise ValueError("At least one CORS origin is required")
        normalized = [_origin(part, app_env=app_env) for part in parts]
        if len(set(normalized)) != len(normalized):
            raise ValueError("CORS origins must be unique")
        return ",".join(normalized)

    @model_validator(mode="after")
    def live_mode_requires_key(self) -> Settings:
        """Reject enabled live mode when the provider key is empty or whitespace."""

        if self.happen_live_enabled and not self.serpapi_api_key.get_secret_value().strip():
            raise ValueError("Live mode requires SERPAPI_API_KEY to be configured")
        return self

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        """Return the validated CORS origins as a tuple for middleware configuration."""

        return tuple(self.cors_allowed_origins.split(","))

    @property
    def live_configured(self) -> bool:
        """Report whether live mode is enabled with a nonblank provider key."""

        return self.happen_live_enabled and bool(self.serpapi_api_key.get_secret_value().strip())


class ConfigError(RuntimeError):
    """Invalid configuration. The message names fields and never includes secret values."""


def safe_config_message(exc: ValidationError) -> str:
    """Summarize validation locations and messages without including input values."""

    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ())) or "configuration"
        parts.append(f"{location}: {error.get('msg', 'invalid')}")
    return "Invalid configuration. " + " ".join(parts)


def get_settings() -> Settings:
    """Load settings. Invalid configuration raises and the process does not start."""

    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigError(safe_config_message(exc)) from None
