"""Download the pinned Gemma GGUF and reject a checksum mismatch."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "ml" / "model-manifest.json"
DEST_DIR = ROOT / "ml" / ".cache"


def sha256(path: Path) -> str:
    """Return the file's SHA-256 hex digest, reading it in 1 MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    """Stream the URL to dest, using HF_TOKEN for authorization when set."""
    request = urllib.request.Request(url, headers={"User-Agent": "happen-model-download"})
    token = os.environ.get("HF_TOKEN", "").strip()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


def main() -> int:
    """Ensure the pinned model is cached and matches its checksum and size.

    Return 0 for a valid cached or downloaded file, or delete an invalid
    download and return 1. File, manifest, and network errors propagate.
    """
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    filename = manifest["filename"]
    expected = manifest["sha256"]
    dest = DEST_DIR / filename
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    if dest.exists() and sha256(dest) == expected and dest.stat().st_size == manifest["size_bytes"]:
        print(f"checksum-ok {filename}")
        return 0
    if dest.exists():
        dest.unlink()
    url = (
        f"https://huggingface.co/{manifest['huggingface_repo']}"
        f"/resolve/{manifest['revision']}/{filename}"
    )
    print(f"downloading {filename}")
    download(url, dest)
    actual = sha256(dest)
    if actual != expected or dest.stat().st_size != manifest["size_bytes"]:
        dest.unlink()
        print("checksum-mismatch", file=sys.stderr)
        return 1
    print(f"checksum-ok {filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
