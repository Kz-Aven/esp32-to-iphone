#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v uv >/dev/null 2>&1; then
  echo 'Missing uv. Install it first: https://docs.astral.sh/uv/getting-started/installation/' >&2
  exit 1
fi
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != '--dev' ) ]]; then
  echo 'Usage: ./setup.sh [--dev]' >&2
  exit 1
fi
extras=(--extra mcp)
if [[ "${1:-}" == '--dev' ]]; then extras+=(--extra dev); fi
uv sync --project server --python 3.12 "${extras[@]}"
echo 'Python environment ready. Next: configure and flash the board, then ./run-local.sh'
