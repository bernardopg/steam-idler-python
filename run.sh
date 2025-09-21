#!/bin/bash
# Steam Idle Bot Runner Script

# Ensure src/ is on PYTHONPATH for the src/ layout
export PYTHONPATH="$(cd "$(dirname "$0")" && pwd)/src:${PYTHONPATH}"

uv sync --dev # Sync the UV environment with the current project, including dev dependencies
uv pip install --dev # Install any missing dependencies into the UV environment

# Activate UV-managed environment and run the package entry
uv run python -m steam_idle_bot "$@"
