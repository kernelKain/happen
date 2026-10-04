"""Shared settings for API tests. No secret values are required."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from happen_api.config import ConfigError, Settings, safe_config_message

PUBLIC_SETTINGS = {
    "APP_ENV": "development",
    "CORS_ALLOWED_ORIGINS": "http://127.0.0.1:5173",
    "HF_MODEL_REPO": "bartowski/google_gemma-3-270m-it-GGUF",
    "HF_MODEL_REVISION": "d127a4e2c6ed47fdf409a956867b604c040432f9",
    "MODEL_FILENAME": "google_gemma-3-270m-it-Q4_K_M.gguf",
    "MODEL_SHA256": "c866c9f113f2e9aa2225c5997ede437392b8fa844ba5db9e4c77e315ffe20800",
    "HAPPEN_LIVE_ENABLED": False,
    "LOG_LEVEL": "info",
    "SERPAPI_API_KEY": "",
    "HF_TOKEN": "",
}


def make_settings(**overrides: object) -> Settings:
    values = {**PUBLIC_SETTINGS, **overrides}
    try:
        return Settings(_env_file=None, **values)
    except ValidationError as exc:
        raise ConfigError(safe_config_message(exc)) from None


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    return make_settings()


@pytest.fixture
def settings_factory(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    return make_settings
