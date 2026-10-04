"""Structured logs drop credential-shaped fields."""

from __future__ import annotations

import json
import logging

from happen_api.logging import JsonFormatter, SecretRedactionFilter


def test_redaction_filter_replaces_credential_fields() -> None:
    """Verify direct and nested credentials are masked while operational log fields survive."""

    record = logging.LogRecord(
        name="happen",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request complete",
        args=(),
        exc_info=None,
    )
    record.api_key = "live-key-value"
    record.token = "hf-token-value"
    record.authorization = "Bearer live-key-value"
    record.cookie = "session=live-key-value"
    record.nested = {"secret": "live-key-value", "endpoint": "/healthz"}
    record.request_id = "abc"

    assert SecretRedactionFilter().filter(record) is True
    rendered = JsonFormatter().format(record)
    assert "live-key-value" not in rendered
    assert "hf-token-value" not in rendered
    assert record.api_key == "[redacted]"
    assert record.nested["secret"] == "[redacted]"
    assert record.nested["endpoint"] == "/healthz"
    assert json.loads(rendered)["message"] == "request complete"
