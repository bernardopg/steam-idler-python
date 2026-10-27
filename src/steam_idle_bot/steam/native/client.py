"""``IDLING_BACKEND=native``: a self-contained Steam client for idling.

Implements the same duck-typed interface as ``SteamClientWrapper`` and
``SteamUtilityIdleClient`` without the unmaintained ``steam`` library, gevent
or protobuf 3:

- login with Steam's current ``IAuthenticationService`` flow, then a refresh
  token stored in ``NATIVE_SESSION_PATH`` (0600), so Steam Guard is asked
  once, not on every run or reconnect;
- idling via ``ClientGamesPlayedWithDataBlob`` over a TLS WebSocket CM;
- ``steamLoginSecure`` web cookies minted from the session
  (``GenerateAccessTokenForApp``), so card-drop scraping does not depend on
  browser cookies, and are re-minted before they expire;
- respects another session that is playing a game on the account (Steam
  blocks playtime for us meanwhile) instead of kicking it, and resumes when
  it ends.
"""

from __future__ import annotations

__all__ = ["NativeSteamClient"]

import builtins
import logging
import platform
import secrets
import threading
import time
from collections.abc import Callable
from functools import partial
from typing import Any
from urllib.parse import quote

from ...config.settings import Settings
from ...utils.exceptions import ConfigurationError, SteamAuthenticationError, SteamConnectionError
from ...utils.redaction import mask_username
from .auth import AuthCodeProvider, authenticate_with_credentials, explain_login_failure
from .cm import CMConnection
from .messages import (
    AUTH_GENERATE_TOKEN_REQUEST,
    AUTH_GENERATE_TOKEN_RESPONSE,
    CLIENT_GAMES_PLAYED,
    CLIENT_LOGGED_OFF,
    CLIENT_LOGON,
    CLIENT_LOGON_RESPONSE,
    OS_TYPE_LINUX_UNKNOWN,
    OS_TYPE_MACOS_UNKNOWN,
    OS_TYPE_WIN11,
    PLAYING_SESSION_STATE,
    PROTOCOL_VERSION,
    TOKEN_RENEWAL_ALLOW,
    EMsg,
    EResult,
    Packet,
    individual_steam_id,
    machine_id_for,
)
from .protobuf import ProtobufDecodeError, decode
from .session_store import NativeSessionStore, StoredSession, refresh_token_problem

logger = logging.getLogger(__name__)

MAX_GAMES_PLAYED = 32
_LOGON_TIMEOUT_SECONDS = 20.0
_CONNECT_ATTEMPTS = 3
# Logon results that mean "this refresh token is dead; log in with the password again".
_TOKEN_REJECTED = frozenset({EResult.AccessDenied, EResult.Expired, EResult.Revoked, EResult.InvalidPassword, EResult.InvalidSignature, EResult.NotLoggedOn})
# Logon results worth retrying on another CM.
_RETRY_OTHER_CM = frozenset({EResult.TryAnotherCM, EResult.ServiceUnavailable, EResult.Busy, EResult.Timeout, EResult.Fail, EResult.NoConnection})
# Renew the refresh token once it has less than this left (Steam issues ~200 days).
_RENEW_REFRESH_TOKEN_BEFORE_SECONDS = 30 * 86400
# steamLoginSecure access tokens live ~24h; re-mint well before that.
WEB_SESSION_MAX_AGE_SECONDS = 6 * 3600


def _local_os_type() -> int:
    system = platform.system()
    if system == "Windows":
        return OS_TYPE_WIN11
    if system == "Darwin":
        return OS_TYPE_MACOS_UNKNOWN
    return OS_TYPE_LINUX_UNKNOWN


class _LogonRejected(Exception):
    def __init__(self, eresult: int) -> None:
        super().__init__(EResult.describe(eresult))
        self.eresult = eresult


class NativeSteamClient:
    """Idling backend that speaks the Steam CM protocol directly."""

    def __init__(
        self,
        settings: Settings,
        *,
        connection_factory: Callable[[], CMConnection] | None = None,
        session_store: NativeSessionStore | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self._connection_factory = connection_factory or (lambda: CMConnection(timeout=float(settings.api_timeout)))
        self._store = session_store or NativeSessionStore(settings.native_session_path)
        self._sleep = sleep_fn
        self._connection: CMConnection | None = None
        self._session: StoredSession | None = None
        self._steam_id: int | None = None
        self._games: list[int] = []
        self._games_lock = threading.Lock()
        self._playing_blocked = False
        self._blocking_app: int | None = None
        self._web_session_minted_at: float | None = None
        self._os_type = _local_os_type()
        self.auth_code_provider: AuthCodeProvider | None = None

    # ------------------------------------------------------------------
    # Client interface
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        try:
            import websockets.sync.client  # noqa: F401 - availability check only
        except ImportError as exc:
            logger.error("The native backend needs the 'websockets' package: %s", exc)
            return False
        logger.info("Native Steam client ready (session file: %s)", self._store.path)
        return True

    def login(self, auth_code_provider: AuthCodeProvider | None = None) -> bool:
        """Log on with the stored refresh token, or the password + Steam Guard."""
        if not self.settings.username or not self.settings.password:
            raise ConfigurationError("Steam credentials not configured. Please check your configuration.")
        if auth_code_provider is not None:
            self.auth_code_provider = auth_code_provider
        logger.info("Logging in to Steam (native backend) as %s", mask_username(self.settings.username))
        try:
            self._connect_and_logon(allow_password=True)
        except KeyboardInterrupt:
            logger.info("Login interrupted by user")
            return False
        except SteamAuthenticationError:
            raise
        except SteamConnectionError as exc:
            logger.error("Steam login failed: %s", exc)
            return False
        logger.info("✅ Logged in to Steam as %s", mask_username(self.username))
        return True

    def start_idling(self, game_ids: list[int]) -> bool:
        if not self.is_connected():
            raise SteamConnectionError("Not connected to Steam")
        games = list(dict.fromkeys(int(game_id) for game_id in game_ids))[:MAX_GAMES_PLAYED]
        with self._games_lock:
            self._games = games
        if not self._send_games_played(games):
            return False
        if games:
            logger.info("Idling %d games: %s", len(games), games)
        if self._playing_blocked:
            logger.warning(self._blocked_message())
        return True

    def stop_idling(self) -> bool:
        with self._games_lock:
            self._games = []
        if not self.is_connected():
            return False
        if self._send_games_played([]):
            logger.info("Stopped idling all games")
            return True
        return False

    def refresh_games(self, game_ids: list[int]) -> bool:
        return self.start_idling(game_ids)

    def is_connected(self) -> bool:
        connection = self._connection
        return bool(connection is not None and connection.connected and connection.logged_on)

    def reconnect(self) -> bool:
        """Open a new CM session; idling is resumed by the caller (main loop)."""
        self._close_connection()
        try:
            self._connect_and_logon(allow_password=True)
        except (SteamConnectionError, SteamAuthenticationError) as exc:
            logger.warning("Steam reconnect failed: %s", exc)
            return False
        return True

    def logout(self) -> bool:
        connection = self._connection
        if connection is not None and connection.connected:
            connection.send_logoff()
        self._close_connection()
        logger.info("Logged out from Steam")
        return True

    def sleep(self, seconds: float) -> None:
        self._sleep(seconds)

    def get_web_session(
        self,
        username: str | None = None,
        password: str | None = None,
        cookies: dict[str, str] | list[dict[str, Any]] | None = None,
    ) -> Any | None:
        """Web session for steamcommunity.com scraping.

        Mints ``steamLoginSecure`` from the logged-on session (always fresh and
        community-valid); falls back to configured ``STEAM_WEB_COOKIES``.
        """
        del username, password
        from ..client import SteamClientWrapper

        minted = self._mint_web_cookies()
        if minted:
            logger.info("Authenticated Steam web session minted from the native login")
            return SteamClientWrapper._build_web_session_from_cookies(minted)
        if cookies:
            logger.info("Building authenticated web session from configured browser cookies")
            return SteamClientWrapper._build_web_session_from_cookies(cookies)
        logger.warning("Could not create an authenticated Steam web session")
        return None

    def refresh_web_session_if_stale(self, max_age_seconds: float = WEB_SESSION_MAX_AGE_SECONDS) -> Any | None:
        """Return a newly minted web session once the current one is old, else None."""
        minted_at = self._web_session_minted_at
        if minted_at is None or time.time() - minted_at < max_age_seconds:
            return None
        from ..client import SteamClientWrapper

        cookies = self._mint_web_cookies()
        return SteamClientWrapper._build_web_session_from_cookies(cookies) if cookies else None

    @property
    def steam_id(self) -> str | None:
        return str(self._steam_id) if self._steam_id else None

    @property
    def username(self) -> str | None:
        return self.settings.username or (self._session.account_name if self._session else None)

    @property
    def playing_blocked(self) -> bool:
        return self._playing_blocked

    @property
    def client(self) -> CMConnection | None:
        return self._connection

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def _code_provider(self) -> AuthCodeProvider:
        return self.auth_code_provider or self._prompt_for_auth_code

    @staticmethod
    def _prompt_for_auth_code(is_2fa: bool, code_mismatch: bool) -> str | None:
        code_type = "Steam Mobile (2FA)" if is_2fa else "e-mail Steam Guard"
        prompt = f"Incorrect code. Enter a new {code_type} code: " if code_mismatch else f"Enter the {code_type} code: "
        return builtins.input(prompt)

    def _connect_and_logon(self, *, allow_password: bool) -> None:
        account = self.settings.username
        last_error: Exception | None = None
        password_used = False
        for _attempt in range(_CONNECT_ATTEMPTS):
            connection = self._connection_factory()
            try:
                connection.connect()
                session = self._usable_stored_session(account)
                if session is None:
                    if not allow_password or password_used:
                        raise SteamAuthenticationError("No valid Steam session; a password login is required")
                    session = self._password_login(connection, account)
                    password_used = True
                self._logon(connection, session)
                self._session = session
                self._connection = connection
                self._renew_refresh_token_if_needed()
                return
            except _LogonRejected as exc:
                connection.close()
                last_error = exc
                if exc.eresult in _TOKEN_REJECTED:
                    logger.warning("Saved Steam session was rejected (%s); a password login is needed", EResult.describe(exc.eresult))
                    self._store.forget_token(account)
                    continue
                if exc.eresult in _RETRY_OTHER_CM:
                    logger.info("Steam asked to try another server (%s)", EResult.describe(exc.eresult))
                    continue
                raise SteamAuthenticationError(explain_login_failure(exc.eresult)) from exc
            except SteamConnectionError as exc:
                connection.close()
                last_error = exc
                logger.debug("Steam connection attempt failed: %s", exc)
            except BaseException:
                connection.close()
                raise
        raise SteamConnectionError(f"Could not log in to Steam after {_CONNECT_ATTEMPTS} attempts ({last_error})")

    def _usable_stored_session(self, account: str) -> StoredSession | None:
        session = self._store.get(account)
        if session is None:
            return None
        problem = refresh_token_problem(session.refresh_token)
        if problem:
            logger.info("Saved Steam session not usable (%s); a password login is needed", problem)
            self._store.forget_token(account)
            return None
        return session

    def _password_login(self, connection: CMConnection, account: str) -> StoredSession:
        logger.info("=" * 60)
        logger.info("🔐 STEAM LOGIN — Steam Guard may ask for a code or an in-app approval")
        logger.info("=" * 60)
        result = authenticate_with_credentials(
            connection,
            account,
            self.settings.password,
            code_provider=self._code_provider(),
            guard_data=self._store.get_guard_data(account),
            sleep=self._sleep,
        )
        self._store.save(account, result.steam_id, result.refresh_token, result.guard_data)
        logger.info("Steam session saved to %s (Steam Guard will not be asked again on this machine)", self._store.path)
        return StoredSession(account.strip().lower(), result.steam_id, result.refresh_token, result.guard_data)

    def _logon(self, connection: CMConnection, session: StoredSession) -> None:
        connection.on(EMsg.ClientLoggedOff, self._on_logged_off)
        connection.on(EMsg.ClientPlayingSessionState, self._on_playing_state)

        steam_id = individual_steam_id(session.steam_id)
        logon_request = partial(
            connection.send,
            EMsg.ClientLogon,
            CLIENT_LOGON,
            {
                "protocol_version": PROTOCOL_VERSION,
                "client_os_type": self._os_type,
                "client_language": "english",
                "should_remember_password": True,
                "machine_id": machine_id_for(session.account_name),
                "machine_name": "steam-idle-bot",
                "chat_mode": 2,
                "supports_rate_limit_response": True,
                "access_token": session.refresh_token,
            },
            {"steamid": steam_id, "client_sessionid": 0},
        )
        packet = connection.wait_for(EMsg.ClientLogOnResponse, _LOGON_TIMEOUT_SECONDS, after_register=logon_request)
        if packet is None:
            raise SteamConnectionError("Steam did not answer the logon request")
        try:
            response = decode(CLIENT_LOGON_RESPONSE, packet.body)
        except ProtobufDecodeError as exc:
            raise SteamConnectionError(f"Malformed logon response: {exc}") from exc

        eresult = int(response.get("eresult", EResult.Fail))
        if eresult != EResult.OK:
            raise _LogonRejected(eresult)

        connection.steam_id = int(packet.header.get("steamid") or steam_id)
        connection.session_id = int(packet.header.get("client_sessionid", 0))
        connection.logged_on = True
        connection.on_disconnect = self._on_disconnect
        connection.start_heartbeat(float(response.get("heartbeat_seconds") or 9))
        self._steam_id = connection.steam_id
        logger.debug("Logged on via CM %s", connection.endpoint)

    def _renew_refresh_token_if_needed(self) -> None:
        session = self._session
        if session is None or session.expires_at is None:
            return
        if session.expires_at - time.time() > _RENEW_REFRESH_TOKEN_BEFORE_SECONDS:
            return
        response = self._generate_access_token(renew=True)
        if response and response.get("refresh_token"):
            new_token = str(response["refresh_token"])
            self._store.save(session.account_name, session.steam_id, new_token, session.guard_data)
            self._session = StoredSession(session.account_name, session.steam_id, new_token, session.guard_data)
            logger.info("Renewed the saved Steam session (it was close to expiring)")

    # ------------------------------------------------------------------
    # Web session
    # ------------------------------------------------------------------

    def _generate_access_token(self, *, renew: bool = False) -> dict[str, Any] | None:
        connection = self._connection
        session = self._session
        if connection is None or session is None or not self.is_connected():
            return None
        try:
            response = connection.call_service(
                "Authentication.GenerateAccessTokenForApp#1",
                AUTH_GENERATE_TOKEN_REQUEST,
                {"refresh_token": session.refresh_token, "steamid": connection.steam_id, "renewal_type": TOKEN_RENEWAL_ALLOW if renew else 0},
                AUTH_GENERATE_TOKEN_RESPONSE,
                authed=True,
            )
        except SteamConnectionError as exc:
            logger.debug("GenerateAccessTokenForApp failed: %s", exc)
            return None
        if not response.ok:
            logger.debug("GenerateAccessTokenForApp returned %s", EResult.describe(response.eresult))
            return None
        return response.body

    def _mint_web_cookies(self) -> dict[str, str] | None:
        response = self._generate_access_token()
        token = response.get("access_token") if response else None
        if not token or not self._steam_id:
            return None
        self._web_session_minted_at = time.time()
        return {
            "steamLoginSecure": quote(f"{self._steam_id}||{token}", safe=""),
            "sessionid": secrets.token_hex(12),
        }

    # ------------------------------------------------------------------
    # Idling & events
    # ------------------------------------------------------------------

    def _send_games_played(self, games: list[int]) -> bool:
        connection = self._connection
        if connection is None:
            return False
        try:
            connection.send(
                EMsg.ClientGamesPlayedWithDataBlob,
                CLIENT_GAMES_PLAYED,
                {"games_played": [{"game_id": app_id} for app_id in games], "client_os_type": self._os_type},
            )
        except SteamConnectionError as exc:
            logger.error("Failed to update games played: %s", exc)
            return False
        return True

    def _blocked_message(self) -> str:
        app = f" (app {self._blocking_app})" if self._blocking_app else ""
        return f"Another Steam session is playing a game{app}; Steam pauses playtime for this bot until that game is closed. Idling resumes automatically."

    def _on_playing_state(self, packet: Packet) -> None:
        state = decode(PLAYING_SESSION_STATE, packet.body)
        blocked = bool(state.get("playing_blocked", False))
        self._blocking_app = int(state.get("playing_app") or 0) or None
        was_blocked, self._playing_blocked = self._playing_blocked, blocked
        if blocked and not was_blocked:
            logger.warning(self._blocked_message())
        elif was_blocked and not blocked:
            with self._games_lock:
                games = list(self._games)
            logger.info("The other Steam session stopped playing; resuming idling of %d games", len(games))
            if games:
                self._send_games_played(games)

    def _on_logged_off(self, packet: Packet) -> None:
        eresult = int(decode(CLIENT_LOGGED_OFF, packet.body).get("eresult", EResult.Fail))
        logger.warning("Steam logged this session off: %s", EResult.describe(eresult))
        connection = self._connection
        if connection is not None:
            connection.logged_on = False

    def _on_disconnect(self) -> None:
        logger.warning("Disconnected from Steam CM")

    def _close_connection(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.on_disconnect = None
            connection.close()
