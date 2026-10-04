"""The secret scan allows short test values and flags credential-shaped text."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "scan-secrets.py"


def load_scanner():
    spec = importlib.util.spec_from_file_location("scan_secrets", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_short_test_assignment_is_allowed() -> None:
    scanner = load_scanner()
    assert scanner.scan_text(Path("tests.py"), 'SERPAPI_API_KEY="live-key-value"') == []


def test_long_assignment_is_flagged_without_echoing_the_value() -> None:
    scanner = load_scanner()
    secret = "c" * scanner.MIN_ASSIGNMENT_LENGTH
    found = scanner.scan_text(Path("config.env"), f"HF_TOKEN={secret}")
    assert found == ["config.env:secret-assignment"]
    assert secret not in found[0]
