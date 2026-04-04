#!/bin/bash
# Steam Idle Bot GUI Runner Script

export PYTHONPATH="$(cd "$(dirname "$0")" && pwd)/src:${PYTHONPATH}"

uv sync
uv run python -m steam_idle_bot --gui "$@"
