"""Settings fail closed and do not expose secrets."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from happen_api.config import ConfigError, Settings, get_settings


def test_missing_non_secret_values_use_locked_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify absent environment settings use the locked development and model defaults."""

    for name in (
        "APP_ENV",
        "CORS_ALLOWED_ORIGINS",
        "HF_MODEL_REPO",
        "HF_MODEL_REVISION",
        "MODEL_FILENAME",
        "MODEL_SHA256",
        "HAPPEN_LIVE_ENABLED",
        "LOG_LEVEL",
        "SERPAPI_API_KEY",
        "HF_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.app_env == "development"
    assert settings.allowed_origins == ("http://127.0.0.1:5173",)
    assert settings.model_sha256 == (
        "c866c9f113f2e9aa2225c5997ede437392b8fa844ba5db9e4c77e315ffe20800"
    )
    assert settings.live_configured is False


def test_development_settings_accept_the_local_origin(
    settings_factory: Callable[..., Settings],
) -> None:
    """Verify development permits the default local origin and leaves live mode disabled."""

    settings = settings_factory()
    assert settings.allowed_origins == ("http://127.0.0.1:5173",)
    assert settings.live_configured is False


def test_repr_hides_secret_values(settings_factory: Callable[..., Settings]) -> None:
    """Verify settings representations omit both provider and model-access credentials."""

    settings = settings_factory(SERPAPI_API_KEY="live-key-value", HF_TOKEN="hf-token-value")
    rendered = repr(settings)
    assert "live-key-value" not in rendered
    assert "hf-token-value" not in rendered


def test_production_rejects_wildcard_and_local_origins(
    settings_factory: Callable[..., Settings],
) -> None:
    """Verify production rejects wildcard and local CORS origins with safe errors."""

    with pytest.raises(ConfigError) as wildcard:
        settings_factory(APP_ENV="production", CORS_ALLOWED_ORIGINS="*")
    assert "live-key-value" not in str(wildcard.value)
    with pytest.raises(ConfigError):
        settings_factory(
            APP_ENV="production",
            CORS_ALLOWED_ORIGINS="http://127.0.0.1:5173",
        )


def test_production_accepts_one_exact_https_origin(
    settings_factory: Callable[..., Settings],
) -> None:
    """Verify production accepts a specific HTTPS frontend origin."""

    settings = settings_factory(
        APP_ENV="production",
        CORS_ALLOWED_ORIGINS="https://happen.example",
    )
    assert settings.allowed_origins == ("https://happen.example",)


def test_live_mode_without_a_key_fails_without_echoing_secrets(
    settings_factory: Callable[..., Settings],
) -> None:
    """Verify live mode requires a provider key without exposing another configured secret."""

    with pytest.raises(ConfigError) as captured:
        settings_factory(
            HAPPEN_LIVE_ENABLED=True,
            SERPAPI_API_KEY="",
            HF_TOKEN="hf-token-value",
        )
    message = str(captured.value)
    assert "SERPAPI_API_KEY" in message
    assert "hf-token-value" not in message


def test_checksum_must_be_64_hex_characters(settings_factory: Callable[..., Settings]) -> None:
    """Verify malformed model checksums are rejected during settings validation."""

    with pytest.raises(ConfigError):
        settings_factory(MODEL_SHA256="not-a-checksum")


def test_process_settings_failure_omits_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify environment-loaded settings failures do not disclose model-access credentials."""

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://127.0.0.1:5173")
    monkeypatch.setenv("HF_MODEL_REPO", "bartowski/google_gemma-3-270m-it-GGUF")
    monkeypatch.setenv("HF_MODEL_REVISION", "d127a4e2c6ed47fdf409a956867b604c040432f9")
    monkeypatch.setenv("MODEL_FILENAME", "google_gemma-3-270m-it-Q4_K_M.gguf")
    monkeypatch.setenv(
        "MODEL_SHA256",
        "c866c9f113f2e9aa2225c5997ede437392b8fa844ba5db9e4c77e315ffe20800",
    )
    monkeypatch.setenv("HAPPEN_LIVE_ENABLED", "true")
    monkeypatch.setenv("LOG_LEVEL", "info")
    monkeypatch.setenv("SERPAPI_API_KEY", " ")
    monkeypatch.setenv("HF_TOKEN", "hf-token-value")
    with pytest.raises(ConfigError) as captured:
        get_settings()
    assert "hf-token-value" not in str(captured.value)


def test_empty_cors_origin_list_fails(settings_factory: Callable[..., Settings]) -> None:
    """Verify a CORS list containing only whitespace and separators is rejected."""

    with pytest.raises(ConfigError):
        settings_factory(CORS_ALLOWED_ORIGINS=" , ")
