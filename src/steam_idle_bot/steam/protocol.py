"""Protocol defining the interface for Steam idling backends."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

AuthCodeProvider = Callable[[bool, bool], str | None]


@runtime_checkable
class IdleBackend(Protocol):
    """Interface that all idling backends must implement.

    Both SteamClientWrapper (python backend) and SteamUtilityIdleClient
    (steam_utility backend) conform to this protocol.
    """

    def initialize(self) -> bool:
        """Prepare the backend for use (connect, resolve paths, etc.)."""
        ...

    def login(self, auth_code_provider: AuthCodeProvider | None = None) -> bool:
        """Authenticate with Steam. Returns True on success."""
        ...

    def start_idling(self, game_ids: list[int]) -> bool:
        """Begin idling the given games. Returns True on success."""
        ...

    def stop_idling(self) -> bool:
        """Stop idling all games."""
        ...

    def is_connected(self) -> bool:
        """Return True if the backend is currently connected to Steam."""
        ...

    def reconnect(self) -> bool:
        """Attempt to restore a dropped connection."""
        ...

    def refresh_games(self, game_ids: list[int]) -> bool:
        """Update the set of games being idled."""
        ...

    def sleep(self, seconds: float) -> None:
        """Yield control for *seconds* while keeping the event loop alive."""
        ...

    def logout(self) -> bool:
        """Disconnect and release resources."""
        ...

    def get_web_session(
        self,
        username: str | None = None,
        password: str | None = None,
        cookies: dict[str, str] | list[dict[str, Any]] | None = None,
    ) -> Any | None:
        """Return an authenticated requests.Session for Steam web pages, or None."""
        ...

    @property
    def steam_id(self) -> str | None:
        """The 64-bit Steam ID of the logged-in account, if known."""
        ...

    @property
    def username(self) -> str | None:
        """The account name of the logged-in user, if known."""
        ...

    @property
    def client(self) -> Any | None:
        """The underlying low-level client object (may be None for some backends)."""
        ...
