#!/usr/bin/env python3
"""Fail when tracked files or an extra path contain credential material.

Prints only the relative path and the rule name. Never prints the matched text.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSIGNMENT = re.compile(
    r"(?im)^[ \t]*(?:export[ \t]+)?(SERPAPI_API_KEY|HF_TOKEN)[ \t]*=[ \t]*([^\s#]+)"
)
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
HF_TOKEN_VALUE = re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")
MIN_ASSIGNMENT_LENGTH = 20


def scan_text(path: Path, text: str) -> list[str]:
    """Return rule findings for one file. The path is used only as a label."""

    relative = path.as_posix()
    found: list[str] = []
    name = path.name
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        found.append(f"{relative}:tracked-env-file")
    if path.suffix == ".gguf":
        found.append(f"{relative}:model-binary")
    for match in ASSIGNMENT.finditer(text):
        if len(match.group(2)) >= MIN_ASSIGNMENT_LENGTH:
            found.append(f"{relative}:secret-assignment")
            break
    if PRIVATE_KEY.search(text):
        found.append(f"{relative}:private-key")
    if HF_TOKEN_VALUE.search(text):
        found.append(f"{relative}:hf-token")
    return found


def self_check() -> None:
    """Prove the rules fire without storing a sample secret in this file."""

    empty = "SERPAPI_API_KEY=\nHF_TOKEN=\n"
    if scan_text(Path(".env.example"), empty):
        raise RuntimeError("empty example assignments were flagged")
    short = "SERPAPI_API_KEY=" + "live-key-value"
    if scan_text(Path("tests.py"), short):
        raise RuntimeError("short test assignment was flagged")
    long_value = "a" * MIN_ASSIGNMENT_LENGTH
    long_finding = scan_text(Path("secret.env"), "SERPAPI_API_KEY=" + long_value)
    if not any(item.endswith(":secret-assignment") for item in long_finding):
        raise RuntimeError("long assignment was missed")
    token = "hf_" + ("b" * 24)
    if not any(item.endswith(":hf-token") for item in scan_text(Path("notes.md"), token)):
        raise RuntimeError("token pattern was missed")
    header = "-----BEGIN " + "PRIVATE KEY-----"
    if not any(item.endswith(":private-key") for item in scan_text(Path("key.pem"), header)):
        raise RuntimeError("private key was missed")
    if not any(item.endswith(":tracked-env-file") for item in scan_text(Path(".env"), "")):
        raise RuntimeError("env file was missed")
    if not any(item.endswith(":model-binary") for item in scan_text(Path("model.gguf"), "")):
        raise RuntimeError("model binary was missed")


def tracked_files() -> list[Path]:
    """Return absolute paths for Git-tracked files, propagating Git command failures."""

    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / name.decode() for name in result.stdout.split(b"\0") if name]


def files_under(path: Path) -> list[Path]:
    """List a file or all files below a directory, raising if the path does not exist."""

    if path.is_file():
        return [path]
    if not path.exists():
        raise FileNotFoundError(path)
    return sorted(item for item in path.rglob("*") if item.is_file())


def display_path(path: Path) -> Path:
    """Use a repository-relative label when possible, preserving paths outside the repository."""

    try:
        return path.resolve().relative_to(ROOT)
    except ValueError:
        return path


def findings_in(paths: list[Path]) -> list[str]:
    """Collect findings from UTF-8 files and apply filename rules to undecodable files."""

    found: list[str] = []
    for path in paths:
        label = display_path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            found.extend(scan_text(label, ""))
            continue
        found.extend(scan_text(label, text))
    return found


def main(argv: list[str] | None = None) -> int:
    """Check scanner rules, scan tracked and extra files, and return one when findings exist."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--extra",
        type=Path,
        action="append",
        default=[],
        help="Additional file or directory to scan, such as a production bundle.",
    )
    args = parser.parse_args(argv)
    self_check()
    found = findings_in(tracked_files())
    for extra in args.extra:
        found.extend(findings_in(files_under(extra if extra.is_absolute() else ROOT / extra)))
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"scan-secrets: {exc}", file=sys.stderr)
        sys.exit(2)
