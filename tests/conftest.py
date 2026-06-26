"""Shared pytest isolation for local developer environments."""

import pytest

APP_ENV_VARS = (
    "USERNAME",
    "PASSWORD",
    "GAME_APP_IDS",
    "FILTER_TRADING_CARDS",
    "USE_OWNED_GAMES",
    "FILTER_COMPLETED_CARD_DROPS",
    "EXCLUDE_APP_IDS",
    "MAX_GAMES_TO_IDLE",
    "REFRESH_INTERVAL_SECONDS",
    "IDLING_BACKEND",
    "STEAM_UTILITY_PATH",
    "STEAM_API_KEY",
    "STEAM_WEB_COOKIES",
    "LOG_LEVEL",
    "LOG_FILE",
    "API_TIMEOUT",
    "RATE_LIMIT_DELAY",
    "ENABLE_CARD_CACHE",
    "CARD_CACHE_PATH",
    "CARD_CACHE_TTL_DAYS",
    "DROP_CACHE_PATH",
    "DROP_CACHE_TTL_DAYS",
    "AUTO_BROWSER_COOKIES",
    "BROWSER_COOKIES_BROWSER",
    "MAX_CHECKS",
    "SKIP_FAILURES",
    "CHECKPOINT_MINUTES",
    "DURATION_MINUTES",
    "POST_RUN_VERIFY_SECONDS",
    "ENABLE_ENCRYPTION",
)


@pytest.fixture(autouse=True)
def isolate_app_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a developer's real Steam config from changing test defaults.

    Settings intentionally read environment variables before .env files at
    runtime. Unit tests that instantiate Settings directly should exercise the
    model defaults unless the test explicitly sets an environment variable.
    """

    for key in APP_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
