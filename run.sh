#!/bin/bash
# Steam Idle Bot Runner Script

set -o pipefail

# Ensure src/ is on PYTHONPATH for the src/ layout
export PYTHONPATH="$(cd "$(dirname "$0")" && pwd)/src:${PYTHONPATH}"

# Prefer the repository .env for local runs. Stale exported shell variables can
# otherwise override freshly saved GUI/browser-cookie settings and make the bot
# behave as if old cookies or temporary --duration/--max-games values were still
# configured. CLI flags still override settings inside the Python entrypoint.
if [[ "${STEAM_IDLE_PRESERVE_ENV:-}" != "1" ]]; then
  unset USERNAME PASSWORD GAME_APP_IDS FILTER_TRADING_CARDS USE_OWNED_GAMES
  unset FILTER_COMPLETED_CARD_DROPS EXCLUDE_APP_IDS MAX_GAMES_TO_IDLE
  unset REFRESH_INTERVAL_SECONDS IDLING_BACKEND STEAM_UTILITY_PATH STEAM_API_KEY
  unset STEAM_WEB_COOKIES LOG_LEVEL LOG_FILE API_TIMEOUT RATE_LIMIT_DELAY
  unset ENABLE_CARD_CACHE CARD_CACHE_PATH CARD_CACHE_TTL_DAYS DROP_CACHE_PATH
  unset DROP_CACHE_TTL_DAYS AUTO_BROWSER_COOKIES BROWSER_COOKIES_BROWSER
  unset MAX_CHECKS SKIP_FAILURES CHECKPOINT_MINUTES DURATION_MINUTES
  unset POST_RUN_VERIFY_SECONDS ENABLE_ENCRYPTION
fi

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
