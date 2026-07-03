#!/bin/bash
# Steam Idle Bot terminal runner.
#
# Runner UX goals:
# - keep Python out of a pipeline so Ctrl+C reaches the bot directly;
# - save bot output under logs/runs/ for later debugging;
# - keep normal shell startup clean, but expose verbose diagnostics on demand.

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR/src:${PYTHONPATH}"

APP_NAME="Steam Idle Bot"
RUNS_DIR="$SCRIPT_DIR/logs/runs"
mkdir -p "$RUNS_DIR"
RUN_LOG="$RUNS_DIR/run_$(date -u +"%Y%m%d_%H%M%SZ").log"

USE_COLOR=0
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  USE_COLOR=1
  # The bot's stdout/stderr go through a FIFO (not a TTY), which makes rich
  # disable all color. Since the real destination *is* a terminal, tell rich
  # to keep ANSI output; the run-log copy is stripped back to plain text below.
  export FORCE_COLOR=1
fi

color() {
  local code="$1"
  if [[ "$USE_COLOR" == "1" ]]; then
    printf '\033[%sm' "$code"
  fi
}

reset_color() {
  if [[ "$USE_COLOR" == "1" ]]; then
    printf '\033[0m'
  fi
}

say() {
  local icon="$1"
  local color_code="$2"
  local message="$3"
  color "$color_code"
  printf '%s %s\n' "$icon" "$message"
  reset_color
}

print_banner() {
  color '1;36'
  printf '\n╭────────────────────────────────────────╮\n'
  printf '│           🎴 %s           │\n' "$APP_NAME"
  printf '╰────────────────────────────────────────╯\n'
  reset_color
}

format_duration() {
  local seconds="$1"
  printf '%02d:%02d' $((seconds / 60)) $((seconds % 60))
}

print_banner
say '📁' '36' "Run log: $RUN_LOG"

# Prefer the repository .env for local runs. Stale exported shell variables can
# otherwise override freshly saved GUI/browser-cookie settings and make the bot
# behave as if old cookies or temporary --duration/--max-games values were still
# configured. CLI flags still override settings inside the Python entrypoint.
if [[ "${STEAM_IDLE_PRESERVE_ENV:-}" != "1" ]]; then
  say '🧹' '36' 'Using .env-first mode; clearing Steam Idle Bot environment overrides (set STEAM_IDLE_PRESERVE_ENV=1 to keep them).'
  unset USERNAME PASSWORD GAME_APP_IDS FILTER_TRADING_CARDS USE_OWNED_GAMES
  unset FILTER_COMPLETED_CARD_DROPS EXCLUDE_APP_IDS MAX_GAMES_TO_IDLE
  unset REFRESH_INTERVAL_SECONDS IDLING_BACKEND STEAM_UTILITY_PATH STEAM_API_KEY
  unset STEAM_WEB_COOKIES LOG_LEVEL LOG_FILE API_TIMEOUT RATE_LIMIT_DELAY
  unset ENABLE_CARD_CACHE CARD_CACHE_PATH CARD_CACHE_TTL_DAYS DROP_CACHE_PATH
  unset DROP_CACHE_TTL_DAYS AUTO_BROWSER_COOKIES BROWSER_COOKIES_BROWSER
  unset MAX_CHECKS SKIP_FAILURES CHECKPOINT_MINUTES DURATION_MINUTES
  unset POST_RUN_VERIFY_SECONDS ENABLE_ENCRYPTION
else
  say '⚠️ ' '33' 'Preserving exported environment overrides because STEAM_IDLE_PRESERVE_ENV=1.'
fi

if [[ "${STEAM_IDLE_SKIP_SYNC:-}" == "1" ]]; then
  say '⏭️ ' '33' 'Skipping uv sync because STEAM_IDLE_SKIP_SYNC=1.'
else
  say '🔧' '36' 'Preparing uv environment...'
  SYNC_LOG="$(mktemp)"
  if [[ "${STEAM_IDLE_RUNNER_VERBOSE:-}" == "1" ]]; then
    uv sync
    SYNC_STATUS=$?
  else
    uv sync > "$SYNC_LOG" 2>&1
    SYNC_STATUS=$?
  fi

  if [[ "$SYNC_STATUS" -ne 0 ]]; then
    say '❌' '31' "uv sync failed with exit code $SYNC_STATUS"
    if [[ -s "$SYNC_LOG" ]]; then
      printf '\n--- uv sync output ---\n'
      cat "$SYNC_LOG"
      printf '%s\n' '----------------------'
    fi
    rm -f "$SYNC_LOG"
    exit "$SYNC_STATUS"
  fi
  rm -f "$SYNC_LOG"
  say '✅' '32' 'Environment ready.'
fi

# Persist bot output for troubleshooting. Keep Python out of a pipeline so
# Ctrl+C reaches the bot and lets it stop native idling children gracefully.
FIFO_DIR="$(mktemp -d)"
FIFO="$FIFO_DIR/bot-output.fifo"
mkfifo "$FIFO"

TEE_PID=""
# Invoked indirectly by the EXIT trap below.
# shellcheck disable=SC2329
cleanup() {
  local status=$?
  rm -f "$FIFO"
  rmdir "$FIFO_DIR" 2>/dev/null || true
  if [[ -n "$TEE_PID" ]]; then
    kill "$TEE_PID" 2>/dev/null || true
  fi
  return "$status"
}
trap cleanup EXIT

# The file copy of the transcript is de-ANSI-fied so the log stays greppable
# even when FORCE_COLOR keeps the terminal copy colored.
tee >(sed -u -E $'s/\x1b\\[[0-9;]*[A-Za-z]//g' > "$RUN_LOG") < "$FIFO" &
TEE_PID=$!

STARTED_AT=$(date +%s)
say '🚀' '36' 'Starting bot. Press Ctrl+C to stop gracefully and print the session report.'
printf '\n'

uv run python -m steam_idle_bot "$@" > "$FIFO" 2>&1
STATUS=$?

wait "$TEE_PID" 2>/dev/null || true
TEE_PID=""

ENDED_AT=$(date +%s)
DURATION=$(format_duration $((ENDED_AT - STARTED_AT)))
printf '\n'
if [[ "$STATUS" -eq 0 ]]; then
  say '✅' '32' "Bot exited successfully after $DURATION. Log saved to $RUN_LOG"
else
  say '❌' '31' "Bot exited with code $STATUS after $DURATION. Log saved to $RUN_LOG"
fi

exit "$STATUS"