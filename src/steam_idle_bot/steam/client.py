"""Steam client wrapper with improved error handling and logging."""

import builtins
import logging
import secrets
import time
from collections.abc import Callable
from typing import Any

import requests

from ..config.settings import Settings
from ..utils.exceptions import (
    ConfigurationError,
    SteamAuthenticationError,
    SteamConnectionError,
)

logger = logging.getLogger(__name__)

AuthCodeProvider = Callable[[bool, bool], str | None]


def _mask_username(username: str | None) -> str:
    """Mask a username for safe logging (e.g. 'ste***bot')."""
    if not username or len(username) <= 3:
        return "***"
    return f"{username[:3]}***{username[-1]}"


class SteamClientWrapper:
    """Wrapper for Steam client with enhanced functionality."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any | None = None
        self._steam_id: str | None = None
        self._username: str | None = None
        self.auth_code_provider: AuthCodeProvider | None = None

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

    def login(self, auth_code_provider: AuthCodeProvider | None = None) -> bool:
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
            raise ConfigurationError("Steam credentials not configured. Please check your configuration.")

        try:
            logger.info("=" * 60)
            logger.info("🔐 STEAM LOGIN REQUIRED")
            logger.info("=" * 60)
            logger.info(f"Username: {_mask_username(self.settings.username)}")
            logger.info("⚠️  IMPORTANT: Check your Steam Mobile App or Email")
            if auth_code_provider or self.auth_code_provider:
                logger.info("⚠️  Enter the authentication code in the active interface")
            else:
                logger.info("⚠️  Enter the 2FA code when prompted in the terminal")
            logger.info("⚠️  Use Ctrl+C to stop the bot at any time")
            logger.info("=" * 60)

            provider = auth_code_provider or self.auth_code_provider

            # Prefer the structured login API so GUI and CLI can share the same 2FA flow.
            if hasattr(self._client, "login"):
                result = self._login_with_auth_flow(provider)
                if not result:
                    raise SteamAuthenticationError("Login failed with login()")
            elif hasattr(self._client, "cli_login"):
                result = self._client.cli_login(username=self.settings.username, password=self.settings.password)
                if result != 1:
                    raise SteamAuthenticationError("Login failed with cli_login")
            elif hasattr(self._client, "log_on"):
                self._client.log_on(username=self.settings.username, password=self.settings.password)
            else:
                raise SteamAuthenticationError("No compatible login method found")

            # Steam client needs a moment for the logged_on flag to propagate
            # before get_web_session_cookies() will work. Try with 5s wait.
            self.sleep(5.0)

            # Get user info after login
            self._update_user_info()

            logger.info("✅ Successfully logged in to Steam")
            return True

        except KeyboardInterrupt:
            logger.info("Login interrupted by user")
            return False
        except Exception as e:
            raise SteamAuthenticationError(f"Login failed: {e}") from e

    def _login_with_auth_flow(self, auth_code_provider: AuthCodeProvider | None) -> bool:
        """Login with support for email/2FA code retries."""
        if self._client is None:
            raise SteamConnectionError("Steam client not initialized")

        client = self._client
        auth_code: str | None = None
        two_factor_code: str | None = None

        while True:
            try:
                result = client.login(
                    username=self.settings.username,
                    password=self.settings.password,
                    auth_code=auth_code,
                    two_factor_code=two_factor_code,
                )
            except TypeError:
                if auth_code is not None or two_factor_code is not None:
                    raise
                result = client.login(
                    username=self.settings.username,
                    password=self.settings.password,
                )

            if self._login_result_is_success(result):
                return True

            auth_request = self._classify_auth_requirement(result)
            if auth_request is None:
                logger.error(f"Steam login failed with result: {result}")
                return False

            is_2fa, code_mismatch = auth_request
            provider = auth_code_provider or self._prompt_for_auth_code
            code = provider(is_2fa, code_mismatch)
            if not code:
                raise SteamAuthenticationError("Authentication code entry cancelled")

            auth_code = None
            two_factor_code = None
            if is_2fa:
                two_factor_code = code.strip()
            else:
                auth_code = code.strip()

    @staticmethod
    def _login_result_is_success(result: Any) -> bool:
        """Interpret login results from different Steam client implementations."""
        if result is None:
            return True

        name = getattr(result, "name", None)
        if name == "OK":
            return True

        return result == 1

    @staticmethod
    def _classify_auth_requirement(result: Any) -> tuple[bool, bool] | None:
        """Return (is_2fa, code_mismatch) when another auth code is required."""
        result_name = getattr(result, "name", str(result))

        if result_name == "AccountLoginDeniedNeedTwoFactor":
            return True, False
        if result_name == "TwoFactorCodeMismatch":
            return True, True
        if result_name == "AccountLogonDenied":
            return False, False
        if result_name == "InvalidLoginAuthCode":
            return False, True

        return None

    @staticmethod
    def _prompt_for_auth_code(is_2fa: bool, code_mismatch: bool) -> str | None:
        """Prompt for an authentication code in the terminal."""
        code_type = "2FA" if is_2fa else "email"
        prompt = f"Incorrect {code_type} code. Enter a new code: " if code_mismatch else f"Enter {code_type} code: "
        return builtins.input(prompt)

    def _update_user_info(self) -> None:
        """Update user information after login."""
        try:
            if self._client and hasattr(self._client, "steam_id"):
                self._steam_id = str(self._client.steam_id)

            if self._client and hasattr(self._client, "username"):
                self._username = self._client.username
            elif self._client and hasattr(self._client, "user") and self._client.user:
                self._username = getattr(self._client.user, "username", "Unknown")

            logger.info(f"Logged in as: {_mask_username(self._username) or 'Unknown'}")
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

    def reconnect(self) -> bool:
        """Attempt to restore the Steam connection using the least intrusive path."""
        if not self._client:
            return False

        try:
            if hasattr(self._client, "relogin"):
                result = self._client.relogin()
                logger.debug(f"Steam relogin() returned: {result}")

                # Give the client event loop a moment to process reconnect state.
                for _ in range(5):
                    if self.is_connected():
                        self._update_user_info()
                        return True
                    self.sleep(1.0)

            # Fall back to a regular login if relogin is unavailable or failed.
            return self.login(auth_code_provider=self.auth_code_provider)

        except Exception as exc:
            logger.warning(f"Steam reconnect attempt failed: {exc}")
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

    def get_web_session(
        self,
        username: str | None = None,
        password: str | None = None,
        cookies: dict[str, str] | list[dict[str, Any]] | None = None,
    ) -> Any | None:
        """Return an authenticated requests session for Steam web pages when available.

        Tries explicitly supplied cookies first, then built-in retries, then cookies
        returned by the logged-in Steam client.
        """
        if cookies:
            logger.info("Building authenticated web session from configured browser cookies")
            return self._build_web_session_from_cookies(cookies)

        # Try the built-in method with retries (it may need event loop processing)
        if self._client:
            try:
                if hasattr(self._client, "get_web_session"):
                    for attempt in range(6):
                        session = self._client.get_web_session()
                        if session:
                            logger.debug(f"get_web_session succeeded on attempt {attempt + 1}")
                            return session
                        logger.debug(f"get_web_session returned None, attempt {attempt + 1}")
                        self.sleep(2.0)
            except Exception as exc:
                logger.debug(f"get_web_session failed: {exc}")

            try:
                if hasattr(self._client, "get_web_session_cookies"):
                    for attempt in range(10):
                        cookies = self._client.get_web_session_cookies()
                        if cookies:
                            logger.debug(
                                "Building authenticated web session from Steam cookies on attempt %s",
                                attempt + 1,
                            )
                            return self._build_web_session_from_cookies(cookies)
                        logger.debug(
                            "get_web_session_cookies returned None, attempt %s",
                            attempt + 1,
                        )
                        self.sleep(2.0)
            except Exception as exc:
                logger.debug(f"get_web_session_cookies failed: {exc}")

        logger.warning("Could not create authenticated Steam web session from Steam cookies")
        return None

    @staticmethod
    def _build_web_session_from_cookies(cookies: dict[str, str] | list[dict[str, Any]], language: str = "english") -> requests.Session:
        """Build a requests session from Steam authentication cookies.

        Supports either:
        - dict[name -> value]
        - list of browser-exported cookie entries with name/value/domain/path/secure
        """
        session = requests.Session()
        if isinstance(cookies, list):
            for item in cookies:
                name = item.get("name")
                value = item.get("value")
                if not name or value is None:
                    continue
                session.cookies.set(
                    str(name),
                    str(value),
                    domain=str(item.get("domain", "steamcommunity.com")),
                    path=str(item.get("path", "/")),
                    secure=bool(item.get("secure", False)),
                )

            return session

        session_id = cookies.get("sessionid") or secrets.token_hex(16)

        for domain in [
            "store.steampowered.com",
            "help.steampowered.com",
            "steamcommunity.com",
        ]:
            for name, value in cookies.items():
                secure = name == "steamLoginSecure"
                session.cookies.set(name, value, domain=domain, secure=secure)

            session.cookies.set("Steam_Language", language, domain=domain)
            session.cookies.set("birthtime", "-3333", domain=domain)
            session.cookies.set("sessionid", session_id, domain=domain)

        return session

    def _prompt_for_2fa_code(self) -> str:
        """Prompt for 2FA code (same as Steam client)."""
        return self._prompt_for_auth_code(is_2fa=True, code_mismatch=False) or ""

    def _prompt_for_email_code(self) -> str:
        """Prompt for email code."""
        return self._prompt_for_auth_code(is_2fa=False, code_mismatch=False) or ""

    def get_web_session_cookies_debug(self) -> dict | None:
        """Get web session cookies with detailed debug logging."""
        if not self._client:
            return None

        client = self._client
        logger.debug(f"_client.logged_on = {getattr(client, 'logged_on', 'MISSING')}")
        logger.debug(f"_client.steam_id = {getattr(client, 'steam_id', 'MISSING')}")

        if not getattr(client, "logged_on", False):
            logger.warning("Cannot get cookies: client is not logged on")
            return None

        try:
            if hasattr(client, "get_web_session_cookies"):
                result = client.get_web_session_cookies()
                logger.debug(f"get_web_session_cookies returned: {result}")
                return result
            else:
                logger.warning("Client has no get_web_session_cookies method")
                return None
        except Exception as exc:
            logger.warning(f"get_web_session_cookies raised: {exc}", exc_info=True)
            return None

    @property
    def steam_id(self) -> str | None:
        """Get the Steam ID of the logged in user."""
        return self._steam_id

    @property
    def username(self) -> str | None:
        """Get the username of the logged in user."""
        return self._username

    @property
    def client(self) -> Any | None:
        """Get the underlying Steam client."""
        return self._client
