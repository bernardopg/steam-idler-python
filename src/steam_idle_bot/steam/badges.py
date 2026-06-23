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
            total=5,
            backoff_factor=2.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        retry.backoff_max = 30.0
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def clear_cache(self) -> None:  # pragma: no cover - no caching yet
        """Clear cached badge data (placeholder for future use)."""

    def get_trading_card_badge_game_ids(self, steam_id: str) -> set[int]:
        """Return app IDs that appear in the user's trading-card badge catalog."""
        badges = self._fetch_badges(steam_id)
        app_ids: set[int] = set()

        for badge in badges:
            app_id = badge.get("appid")
            if not app_id:
                continue

            try:
                app_id_int = int(app_id)
            except (TypeError, ValueError):
                continue

            if badge.get("border_color", 0) != 0:
                continue

            app_ids.add(app_id_int)

        return app_ids

    def partition_games_by_remaining_cards(
        self,
        game_ids: Iterable[int],
        steam_id: str,
    ) -> tuple[list[int], list[int]]:
        """Return (confirmed_remaining, unknown_status) for the supplied games.

        The Steam badge API only contains apps for which badge/card-drop progress is
        available. When a candidate game is missing from the API response we should not
        automatically assume it still has drops remaining; instead, callers can decide
        whether to confirm those games through a secondary mechanism such as scraping.
        """
        cards_remaining = self._fetch_cards_remaining(steam_id)
        confirmed_remaining: list[int] = []
        unknown_status: list[int] = []
        skipped = 0

        for app_id in game_ids:
            remaining = cards_remaining.get(app_id)
            if remaining is None:
                unknown_status.append(app_id)
            elif remaining > 0:
                confirmed_remaining.append(app_id)
            else:
                skipped += 1
                logger.debug(f"Filtered out game {app_id} - 0 cards remaining")

        if skipped:
            logger.info("Filtered out %s games with no trading-card drops remaining", skipped)
        if unknown_status:
            logger.info(
                "Badge API returned no card-drop data for %s candidate games",
                len(unknown_status),
            )

        return confirmed_remaining, unknown_status

    def filter_games_with_remaining_cards(self, game_ids: Iterable[int], steam_id: str) -> list[int]:
        """Return IDs with confirmed remaining trading-card drops."""
        filtered, _unknown = self.partition_games_by_remaining_cards(game_ids, steam_id)
        return filtered

    def get_cards_remaining(self, steam_id: str) -> dict[int, int]:
        """Public API: return a map of app_id -> cards_remaining for the given user."""
        return self._fetch_cards_remaining(steam_id)

    def _fetch_cards_remaining(self, steam_id: str) -> dict[int, int]:
        badges = self._fetch_badges(steam_id)
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

            if "cards_remaining" not in badge:
                continue

            remaining = badge.get("cards_remaining")
            if remaining is None:
                continue

            try:
                remaining_int = int(remaining)
            except (TypeError, ValueError):
                continue

            cards_remaining[app_id_int] = remaining_int

        return cards_remaining

    def _fetch_badges(self, steam_id: str) -> list[dict[str, Any]]:
        if not self.settings.steam_api_key:
            raise BadgeServiceError("Steam API key required to check trading-card drop progress")

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
        if not isinstance(badges, list):
            raise BadgeServiceError("Invalid badge list in badge API response")

        return badges
