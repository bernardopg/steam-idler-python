"""Steam client wrapper with improved error handling and logging."""

import logging
import time
from typing import Any, Optional

from ..config.settings import Settings
from ..utils.exceptions import (
    ConfigurationError,
    SteamAuthenticationError,
    SteamConnectionError,
)

logger = logging.getLogger(__name__)


class SteamClientWrapper:
    """Wrapper for Steam client with enhanced functionality."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Optional[Any] = None
        self._steam_id: Optional[str] = None
        self._username: Optional[str] = None

    def initialize(self) -> bool:
        """
        Initialize the Steam client.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            from steam.client import SteamClient

            self._client = SteamClient()
            logger.info("Steam client initialized successfully")
            return True

        except ImportError as e:
            logger.error(f"Failed to import Steam client: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Steam client: {e}")
            return False

    def login(self) -> bool:
        """
        Login to Steam using configured credentials.

        Returns:
            True if login successful, False otherwise

        Raises:
            ConfigurationError: If credentials are not configured
            SteamAuthenticationError: If authentication fails
        """
        if not self._client:
            raise SteamConnectionError("Steam client not initialized")

        # Validate credentials
        if not self.settings.username or not self.settings.password:
            raise ConfigurationError(
                "Steam credentials not configured. Please check your configuration."
            )

        try:
            logger.info("=" * 60)
            logger.info("🔐 STEAM LOGIN REQUIRED")
            logger.info("=" * 60)
            logger.info(f"Username: {self.settings.username}")
            logger.info("⚠️  IMPORTANT: Check your Steam Mobile App or Email")
            logger.info("⚠️  Enter the 2FA code when prompted in the terminal")
            logger.info("⚠️  Use Ctrl+C to stop the bot at any time")
            logger.info("=" * 60)

            # Try different login methods based on available API
            if hasattr(self._client, "cli_login"):
                result = self._client.cli_login(
                    username=self.settings.username, password=self.settings.password
                )
                if result != 1:
                    raise SteamAuthenticationError("Login failed with cli_login")
            elif hasattr(self._client, "log_on"):
                self._client.log_on(
                    username=self.settings.username, password=self.settings.password
                )
            elif hasattr(self._client, "login"):
                self._client.login(
                    username=self.settings.username, password=self.settings.password
                )
            else:
                raise SteamAuthenticationError("No compatible login method found")

            # Get user info after login
            self._update_user_info()

            logger.info("✅ Successfully logged in to Steam")
            return True

        except KeyboardInterrupt:
            logger.info("Login interrupted by user")
            return False
        except Exception as e:
            raise SteamAuthenticationError(f"Login failed: {e}") from e

    def _update_user_info(self) -> None:
        """Update user information after login."""
        try:
            if self._client and hasattr(self._client, "steam_id"):
                self._steam_id = str(self._client.steam_id)

            if self._client and hasattr(self._client, "username"):
                self._username = self._client.username
            elif self._client and hasattr(self._client, "user") and self._client.user:
                self._username = getattr(self._client.user, "username", "Unknown")

            logger.info(f"Logged in as: {self._username or 'Unknown'}")
            if self._steam_id:
                logger.debug(f"Steam ID: {self._steam_id}")

        except Exception as e:
            logger.warning(f"Could not retrieve user info: {e}")

    def start_idling(self, game_ids: list[int]) -> bool:
        """
        Start idling the specified games.

        Args:
            game_ids: List of game app IDs to idle

        Returns:
            True if successful, False otherwise
        """
        if not self._client:
            raise SteamConnectionError("Steam client not initialized")

        if not self.is_connected():
            raise SteamConnectionError("Not connected to Steam")

        try:
            if hasattr(self._client, "games_played"):
                self._client.games_played(game_ids)
                logger.info(f"Started idling {len(game_ids)} games: {game_ids}")
                return True
            else:
                logger.error("No method available to set games played")
                return False

        except Exception as e:
            logger.error(f"Failed to start idling: {e}")
            return False

    def stop_idling(self) -> bool:
        """Stop idling all games."""
        if not self._client:
            return False

        try:
            if hasattr(self._client, "games_played"):
                self._client.games_played([])
                logger.info("Stopped idling all games")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to stop idling: {e}")
            return False

    def is_connected(self) -> bool:
        """Check if connected to Steam."""
        if not self._client:
            return False

        try:
            return getattr(self._client, "connected", False)
        except Exception:
            return False

    def logout(self) -> bool:
        """Logout from Steam."""
        if not self._client:
            return True

        try:
            if hasattr(self._client, "logout"):
                self._client.logout()
            elif hasattr(self._client, "disconnect"):
                self._client.disconnect()

            logger.info("Logged out from Steam")
            return True

        except Exception as e:
            logger.error(f"Error during logout: {e}")
            return False

    def sleep(self, seconds: float) -> None:
        """Yield control to the Steam client's event loop while idling."""
        if self._client and hasattr(self._client, "sleep"):
            try:
                self._client.sleep(seconds)
                return
            except Exception as exc:
                logger.debug(f"Steam client sleep failed, falling back to time.sleep: {exc}")

        time.sleep(seconds)

    def refresh_games(self, game_ids: list[int]) -> bool:
        """
        Refresh the list of games being idled.

        Args:
            game_ids: New list of game IDs to idle

        Returns:
            True if successful, False otherwise
        """
        return self.start_idling(game_ids)

    @property
    def steam_id(self) -> Optional[str]:
        """Get the Steam ID of the logged in user."""
        return self._steam_id

    @property
    def username(self) -> Optional[str]:
        """Get the username of the logged in user."""
        return self._username

    @property
    def client(self) -> Optional[Any]:
        """Get the underlying Steam client."""
        return self._client
