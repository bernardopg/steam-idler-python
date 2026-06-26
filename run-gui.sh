#!/bin/bash
# Steam Idle Bot GUI Runner Script

export PYTHONPATH="$(cd "$(dirname "$0")" && pwd)/src:${PYTHONPATH}"

# Prefer the repository .env for local GUI runs. Stale exported shell variables
# can otherwise override settings saved from the GUI or recovered browser
# cookies. Set STEAM_IDLE_PRESERVE_ENV=1 to intentionally keep env overrides.
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

uv sync
uv run python -m steam_idle_bot --gui "$@"
