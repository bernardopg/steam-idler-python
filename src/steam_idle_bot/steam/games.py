# isort: skip_file
"""Game library management and filtering."""

import logging
from typing import Optional

import requests

from ..config.settings import Settings
from ..utils.exceptions import BadgeServiceError, GameLibraryError, SteamAPITimeoutError
from .trading_cards import TradingCardDetector


logger = logging.getLogger(__name__)


class GameManager:
    """Manages Steam game library and filtering."""

    def __init__(
        self,
        settings: Settings,
        trading_card_detector: TradingCardDetector,
        badge_service=None,
    ):
        self.settings = settings
        self.trading_card_detector = trading_card_detector
        self.badge_service = badge_service
        self._owned_games_cache: Optional[list[int]] = None

    def get_owned_games(self, steam_id: Optional[str] = None) -> list[int]:
        """
        Get the list of owned games from Steam library.

        Args:
            steam_id: Steam ID (optional, will try to get from client if None)

        Returns:
            List of owned game app IDs

        Raises:
            GameLibraryError: If unable to retrieve game library
        """
        if self._owned_games_cache is not None:
            return self._owned_games_cache

        try:
            if self.settings.steam_api_key and steam_id:
                return self._get_owned_games_via_api(steam_id)
            else:
                logger.warning(
                    "Steam API key not available, using configured game list"
                )
                return self.settings.game_app_ids

        except Exception as e:
            logger.error(f"Error getting owned games: {e}")
            return self.settings.game_app_ids

    def _get_owned_games_via_api(self, steam_id: str) -> list[int]:
        """Get owned games using Steam Web API."""
        try:
            url = "http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
            params = {
                "key": self.settings.steam_api_key,
                "steamid": steam_id,
                "format": "json",
                "include_appinfo": 1,
            }

            response = requests.get(
                url,
                params=params,
                timeout=self.settings.api_timeout,
                headers={"User-Agent": "Steam-Idle-Bot/1.0"},
            )
            response.raise_for_status()

            data = response.json()

            if "response" in data and "games" in data["response"]:
                games = [game["appid"] for game in data["response"]["games"]]
                self._owned_games_cache = games
                logger.info(f"Retrieved {len(games)} owned games via API")
                return games

            raise GameLibraryError("Invalid response from Steam API")

        except requests.exceptions.Timeout as err:
            raise SteamAPITimeoutError("Timeout retrieving owned games") from err
        except requests.exceptions.RequestException as err:
            raise GameLibraryError(
                f"Network error retrieving owned games: {err}"
            ) from err

    def get_games_to_idle(self, steam_id: Optional[str] = None) -> list[int]:
        """
        Get the final list of games to idle based on configuration.

        Args:
            steam_id: Steam ID for API calls

        Returns:
            List of game IDs to idle
        """
        if self.settings.use_owned_games:
            logger.info("Getting owned games from Steam library...")
            games = self.get_owned_games(steam_id)
            logger.info(f"Found {len(games)} owned games")
        else:
            logger.info("Using manually specified game list...")
            games = self.settings.game_app_ids

        if self.settings.filter_trading_cards:
            padded_target = self.settings.max_games_to_idle
            if self.settings.filter_completed_card_drops:
                padded_target += max(5, self.settings.max_games_to_idle // 2)
                padded_target = min(padded_target, len(games))

            logger.info("Filtering games with trading cards...")
            games = self.trading_card_detector.filter_games_with_trading_cards(
                games,
                max_games=padded_target,
                max_checks=self.settings.max_checks,
                skip_failures=self.settings.skip_failures,
            )
            logger.info(f"Found {len(games)} games with trading cards")
        else:
            games = games[: self.settings.max_games_to_idle]
            logger.info(
                f"Using first {len(games)} games (trading card filtering disabled)"
            )

        games = self._filter_completed_card_drops(games, steam_id)

        games = games[: self.settings.max_games_to_idle]

        if not games:
            logger.warning("No games found to idle after filtering")
            if self.settings.filter_completed_card_drops:
                return []
            return self.settings.game_app_ids[: self.settings.max_games_to_idle]

        return games

    def clear_cache(self) -> None:
        """Clear all caches."""
        self._owned_games_cache = None
        self.trading_card_detector.clear_cache()
        if self.badge_service:
            self.badge_service.clear_cache()

    def _filter_completed_card_drops(
        self, games: list[int], steam_id: Optional[str]
    ) -> list[int]:
        if not games:
            return games

        if not (
            self.settings.filter_completed_card_drops
            and self.badge_service
            and self.settings.steam_api_key
            and steam_id
        ):
            if self.settings.filter_completed_card_drops and not self.settings.steam_api_key:
                logger.debug(
                    "Skipping card-drop progress filter: Steam API key not configured"
                )
            return games

        try:
            filtered_games = self.badge_service.filter_games_with_remaining_cards(
                games, steam_id
            )
            if not filtered_games:
                logger.info(
                    "All candidate games have already dropped their trading cards"
                )
            return filtered_games
        except SteamAPITimeoutError as err:
            logger.warning(f"Badge progress request timed out: {err}")
        except BadgeServiceError as err:
            logger.warning(f"Failed to retrieve badge progress: {err}")

        return games
