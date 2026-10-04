#!/usr/bin/env bash
# Install the locked backend and download the pinned public GGUF.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

if ! command -v uv >/dev/null 2>&1 || [[ "$(uv --version)" != uv\ 0.12.5* ]]; then
  curl -LsSf "https://astral.sh/uv/0.12.5/install.sh" | env UV_INSTALL_DIR="${root}/.uv" sh
  export PATH="${root}/.uv:${PATH}"
fi

if ! command -v cmake >/dev/null 2>&1 || ! command -v ninja >/dev/null 2>&1; then
  uv venv "${root}/.build-tools"
  uv pip install --python "${root}/.build-tools/bin/python" cmake ninja
  export PATH="${root}/.build-tools/bin:${PATH}"
fi

export CMAKE_ARGS="${CMAKE_ARGS:--DGGML_NATIVE=OFF}"
export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-2}"
export UV_PYTHON="${UV_PYTHON:-3.13.15}"

uv sync --project backend --frozen --no-dev
python3 "${root}/scripts/download-model.py"
