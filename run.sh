#!/bin/bash
# Steam Idle Bot Runner Script

set -o pipefail

# Ensure src/ is on PYTHONPATH for the src/ layout
export PYTHONPATH="$(cd "$(dirname "$0")" && pwd)/src:${PYTHONPATH}"

# Ensure UV environment is set up and dependencies are installed
uv sync

# Persist a full run transcript for troubleshooting.
RUNS_DIR="$(cd "$(dirname "$0")" && pwd)/logs/runs"
mkdir -p "$RUNS_DIR"
RUN_LOG="$RUNS_DIR/run_$(date -u +"%Y%m%d_%H%M%SZ").log"
echo "Saving run output to: $RUN_LOG"

# Activate UV-managed environment and run the package entry. Keep Python out of
# a pipeline so Ctrl+C reaches the bot and lets it stop native idling children.
FIFO="$(mktemp -u)"
mkfifo "$FIFO"
tee "$RUN_LOG" < "$FIFO" &
TEE_PID=$!
trap 'rm -f "$FIFO"; kill "$TEE_PID" 2>/dev/null || true' EXIT

uv run python -m steam_idle_bot "$@" > "$FIFO" 2>&1
STATUS=$?

wait "$TEE_PID" 2>/dev/null || true
exit "$STATUS"
