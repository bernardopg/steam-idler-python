#!/usr/bin/env python3
"""
Legacy entry point for Steam Idle Bot.
This file provides backward compatibility with the original interface.

Notes:
- Exposes legacy functions and constants used by older tests/scripts:
  - has_trading_cards(app_id: int) -> bool
  - filter_games_with_trading_cards(game_ids: list[int]) -> list[int]
  - ensure_credentials_configured() -> None (raises SystemExit on failure)
  - FILTER_TRADING_CARDS, MAX_GAMES_TO_IDLE, USERNAME, PASSWORD
"""

import sys
import warnings
from pathlib import Path

import requests

# Add src to path for module imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Try to load local config if present (legacy style)
try:  # pragma: no cover - simple import guard
    import config as _legacy_config
except Exception:  # noqa: BLE001 - broad for resilience in legacy path
    _legacy_config = None

# Legacy-compatible globals (mirrored from config_example.py defaults)
USERNAME = getattr(_legacy_config, "USERNAME", "your_steam_username")
PASSWORD = getattr(_legacy_config, "PASSWORD", "your_steam_password")

GAME_APP_IDS: list[int] = getattr(_legacy_config, "GAME_APP_IDS", [570, 730])
FILTER_TRADING_CARDS: bool = getattr(_legacy_config, "FILTER_TRADING_CARDS", True)
USE_OWNED_GAMES: bool = getattr(_legacy_config, "USE_OWNED_GAMES", True)
MAX_GAMES_TO_IDLE: int = getattr(_legacy_config, "MAX_GAMES_TO_IDLE", 30)


def has_trading_cards(app_id: int) -> bool:
    """Return True if the app has Steam Trading Cards.

    Legacy, network-light implementation that tolerates failures by returning False.
    """
    try:
        url = "https://store.steampowered.com/api/appdetails"
        params = {"appids": app_id, "filters": "categories"}
        headers = {"User-Agent": "Steam-Idle-Bot/legacy-compat"}
        resp = requests.get(url, params=params, timeout=10, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        entry = data.get(str(app_id))
        if not entry or not entry.get("success"):
            return False
        categories = entry.get("data", {}).get("categories", [])
        return any(cat.get("id") == 29 for cat in categories)
    except Exception:
        # Be conservative for legacy tests: treat failures as "no cards"
        return False


def filter_games_with_trading_cards(game_ids: list[int]) -> list[int]:
    """Filter provided game ids to those that have trading cards.

    Respects MAX_GAMES_TO_IDLE and FILTER_TRADING_CARDS globals.
    """
    max_count = int(MAX_GAMES_TO_IDLE or 0)
    if max_count <= 0:
        return []

    if not FILTER_TRADING_CARDS:
        return list(game_ids)[:max_count]

    result: list[int] = []
    for gid in game_ids:
        try:
            if has_trading_cards(gid):
                result.append(gid)
                if len(result) >= max_count:
                    break
        except Exception:
            # Ignore individual failures in legacy path
            continue
    return result


def ensure_credentials_configured() -> None:
    """Exit the program if legacy USERNAME/PASSWORD look like placeholders."""
    user = (USERNAME or "").strip().lower()
    pwd = (PASSWORD or "").strip().lower()
    if user in ("", "your_steam_username") or pwd in ("", "your_steam_password"):
        # Match legacy behavior by exiting the process
        sys.exit(1)


# Import the new main function for actual execution
from steam_idle_bot.main import main  # noqa: E402  (after sys.path tweak)

# Show deprecation warning upon import
warnings.warn(
    "idle_bot.py is deprecated. Use 'python -m steam_idle_bot' instead.",
    DeprecationWarning,
    stacklevel=2,
)

if __name__ == "__main__":
    main()
