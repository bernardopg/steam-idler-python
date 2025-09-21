#!/bin/bash
# Steam Idle Bot Runner Script

# Ensure src/ is on PYTHONPATH for the src/ layout
export PYTHONPATH="$(cd "$(dirname "$0")" && pwd)/src:${PYTHONPATH}"

# Ensure UV environment is set up and dependencies are installed
uv sync

# Activate UV-managed environment and run the package entry
uv run python -m steam_idle_bot "$@"
