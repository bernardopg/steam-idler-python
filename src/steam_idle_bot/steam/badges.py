"""Helpers for querying Steam badge progress and card drop availability."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config.settings import Settings
from ..utils.exceptions import BadgeServiceError, SteamAPITimeoutError

logger = logging.getLogger(__name__)


class BadgeService:
    """Fetches badge progress to determine remaining trading-card drops."""

    BADGE_API_URL = "https://api.steampowered.com/IPlayerService/GetBadges/v1/"

    def __init__(
        self,
        settings: Settings,
        session: Any | None = None,
        *,
        timeout: int | None = None,
    ) -> None:
        self.settings = settings
        self.timeout = timeout or settings.api_timeout
        self._http = session or self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def clear_cache(self) -> None:  # pragma: no cover - no caching yet
        """Clear cached badge data (placeholder for future use)."""

    def filter_games_with_remaining_cards(
        self, game_ids: Iterable[int], steam_id: str
    ) -> list[int]:
        """Return IDs that still have trading cards available to drop."""
        cards_remaining = self._fetch_cards_remaining(steam_id)
        filtered: list[int] = []
        skipped = 0

        for app_id in game_ids:
            remaining = cards_remaining.get(app_id)
            if remaining is None:
                # Game not in badges list - probably still has drops
                filtered.append(app_id)
            elif remaining > 0:
                # Game has remaining drops
                filtered.append(app_id)
            else:
                # Game has 0 remaining drops
                skipped += 1
                logger.debug(f"Filtered out game {app_id} - 0 cards remaining")

        if skipped:
            logger.info(
                "Filtered out %s games with no trading-card drops remaining", skipped
            )

        return filtered

    def _fetch_cards_remaining(self, steam_id: str) -> dict[int, int]:
        if not self.settings.steam_api_key:
            raise BadgeServiceError(
                "Steam API key required to check trading-card drop progress"
            )

        params = {
            "key": self.settings.steam_api_key,
            "steamid": steam_id,
            "format": "json",
        }

        try:
            response = self._http.get(
                self.BADGE_API_URL,
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": "Steam-Idle-Bot/1.0"},
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as err:
            raise SteamAPITimeoutError("Timeout retrieving badge data") from err
        except requests.exceptions.RequestException as err:
            raise BadgeServiceError(f"Network error retrieving badge data: {err}") from err

        try:
            data = response.json()
        except ValueError as err:
            raise BadgeServiceError("Invalid JSON response from badge API") from err

        badges = data.get("response", {}).get("badges", [])
        cards_remaining: dict[int, int] = {}

        for badge in badges:
            app_id = badge.get("appid")
            if not app_id:
                continue

            try:
                app_id_int = int(app_id)
            except (TypeError, ValueError):
                continue

            # Check if this is a trading card badge
            border_color = badge.get("border_color", 0)
            if border_color != 0:
                # Not a trading card badge, skip
                continue

            remaining = badge.get("cards_remaining", 0)

            try:
                remaining_int = int(remaining)
            except (TypeError, ValueError):
                continue

            cards_remaining[app_id_int] = remaining_int

        return cards_remaining
