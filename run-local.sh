#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/server"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Missing Python environment. Run ./setup.sh from the project root.' >&2
  exit 1
fi
if ! command -v uxplay >/dev/null 2>&1; then
  echo 'Missing uxplay on PATH. See docs/setup.md.' >&2
  exit 1
fi
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
export HIDAGENT_DATA="${HIDAGENT_DATA:-$PWD/.local-data}"
export HOST="${HOST:-127.0.0.1}"
exec .venv/bin/python -m hidagent
