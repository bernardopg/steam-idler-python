"""Custom exceptions for Steam Idle Bot."""

from typing import Optional


class SteamIdleBotError(Exception):
    """Base exception for all Steam Idle Bot errors."""

    def __init__(self, message: str, error_code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class ConfigurationError(SteamIdleBotError):
    """Raised when there's an issue with configuration."""
    pass


class SteamAuthenticationError(SteamIdleBotError):
    """Raised when Steam authentication fails."""
    pass


class SteamConnectionError(SteamIdleBotError):
    """Raised when there's a connection issue with Steam."""
    pass


class SteamAPITimeoutError(SteamIdleBotError):
    """Raised when Steam API calls timeout."""
    pass


class TradingCardDetectionError(SteamIdleBotError):
    """Raised when trading card detection fails."""
    pass


class GameLibraryError(SteamIdleBotError):
    """Raised when there's an issue accessing the game library."""
    pass


class RateLimitError(SteamIdleBotError):
    """Raised when rate limits are exceeded."""
    pass


class BadgeServiceError(SteamIdleBotError):
    """Raised when badge progress retrieval fails."""
    pass


class CardDropCheckError(SteamIdleBotError):
    """Raised when card drop checking fails."""
    pass
