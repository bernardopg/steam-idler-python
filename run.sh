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

# Activate UV-managed environment and run the package entry.
uv run python -m steam_idle_bot "$@" 2>&1 | tee "$RUN_LOG"
exit ${PIPESTATUS[0]}
