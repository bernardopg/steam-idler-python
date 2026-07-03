#!/bin/bash
# Steam Idle Bot — web UI runner (FastAPI backend + React frontend).
#
# Builds the frontend on demand (when dist/ is missing or sources changed),
# then starts the server. Flags are forwarded to the Python entrypoint
# (e.g. ./run-web.sh --web-port 9000).

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR/src:${PYTHONPATH}"

FRONTEND_DIR="$SCRIPT_DIR/frontend"
DIST_DIR="$FRONTEND_DIR/dist"

needs_build=0
if [[ ! -d "$DIST_DIR" ]]; then
  needs_build=1
elif [[ -n "$(find "$FRONTEND_DIR/src" "$FRONTEND_DIR/index.html" "$FRONTEND_DIR/package.json" -newer "$DIST_DIR" -print -quit 2>/dev/null)" ]]; then
  needs_build=1
fi

if [[ "$needs_build" == "1" ]]; then
  echo "🔨 Building frontend..."
  (cd "$FRONTEND_DIR" && npm install --silent && npm run build) || exit 1
fi

if [[ "${STEAM_IDLE_SKIP_SYNC:-}" != "1" ]]; then
  echo "🔧 Preparing uv environment..."
  uv sync --quiet || exit 1
fi

echo "🚀 Starting web UI at http://127.0.0.1:${STEAM_IDLE_WEB_PORT:-8765} (Ctrl+C stops)"
exec uv run python -m steam_idle_bot --web "$@"
