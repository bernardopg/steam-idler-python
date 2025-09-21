"""Utilities for Steam Idle Bot."""

from .exceptions import (
    ConfigurationError,
    GameLibraryError,
    RateLimitError,
    SteamAPITimeoutError,
    SteamAuthenticationError,
    SteamConnectionError,
    SteamIdleBotError,
    TradingCardDetectionError,
)
from .logger import SteamIdleLogger, setup_logging

__all__ = [
    "SteamIdleBotError",
    "ConfigurationError",
    "SteamAuthenticationError",
    "SteamConnectionError",
    "SteamAPITimeoutError",
    "TradingCardDetectionError",
    "GameLibraryError",
    "RateLimitError",
    "setup_logging",
    "SteamIdleLogger",
]
