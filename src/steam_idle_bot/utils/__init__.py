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
from .idle_tracker import IdleTracker
from .logger import SteamIdleLogger, setup_logging

__all__ = [
    "IdleTracker",
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
