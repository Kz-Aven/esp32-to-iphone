#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/server"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Missing Python environment. Run ./setup.sh from the project root.' >&2
  exit 1
fi
exec .venv/bin/python -m hidagent.cli --url "${IPHONE_AGENT_URL:-http://127.0.0.1:8890}" mcp
