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
elif [[ -n "$(find "$FRONTEND_DIR/src" "$FRONTEND_DIR/index.html" "$FRONTEND_DIR/package.json" "$FRONTEND_DIR/package-lock.json" "$FRONTEND_DIR/vite.config.ts" -newer "$DIST_DIR" -print -quit 2>/dev/null)" ]]; then
  needs_build=1
fi

if [[ "$needs_build" == "1" ]]; then
  echo "🔨 Building frontend..."
  (
    cd "$FRONTEND_DIR" || exit 1
    # npm ci installs exactly what package-lock.json pins (never rewrites it).
    if [[ ! -d node_modules || package-lock.json -nt node_modules ]]; then
      npm ci --silent --no-audit --no-fund || exit 1
    fi
    npm run build
  ) || exit 1
fi

if [[ "${STEAM_IDLE_SKIP_SYNC:-}" != "1" ]]; then
  echo "🔧 Preparing uv environment..."
  uv sync --quiet || exit 1
fi

# The server prints the exact URL (it honours --web-port).
echo "🚀 Starting web UI..."
exec uv run python -m steam_idle_bot --web "$@"
