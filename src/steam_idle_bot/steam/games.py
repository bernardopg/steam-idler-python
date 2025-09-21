# isort: skip_file
"""Game library management and filtering."""

import logging
from typing import Optional

import requests

from ..config.settings import Settings
from ..utils.detailed_logger import DetailedLogger
from ..utils.exceptions import (
    BadgeServiceError,
    GameLibraryError,
    SteamAPITimeoutError,
)
from .card_drops import CardDropChecker
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
        self.card_drop_checker = CardDropChecker(settings)
        self.detailed_logger = DetailedLogger(settings)
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
                games = self._get_owned_games_via_api(steam_id)
            else:
                logger.warning(
                    "Steam API key not available, using configured game list"
                )
                games = self.settings.game_app_ids

            # Log the games retrieved
            self.detailed_logger.log_api_results(
                "owned_games",
                games,
                {
                    "source": (
                        "api" if self.settings.steam_api_key and steam_id else "config"
                    )
                },
            )
            return games

        except Exception as e:
            logger.error(f"Error getting owned games: {e}")
            games = self.settings.game_app_ids
            self.detailed_logger.log_api_results(
                "owned_games", games, {"source": "config_fallback", "error": str(e)}
            )
            return games

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
        # Get all games
        if self.settings.use_owned_games:
            logger.info("Getting owned games from Steam library...")
            all_games = self.get_owned_games(steam_id)
            logger.info(f"Found {len(all_games)} owned games")
        else:
            logger.info("Using manually specified game list...")
            all_games = self.settings.game_app_ids

        # Filter trading cards
        games_with_cards = all_games
        if self.settings.filter_trading_cards:
            padded_target = self.settings.max_games_to_idle
            if self.settings.filter_completed_card_drops:
                padded_target += max(5, self.settings.max_games_to_idle // 2)
                padded_target = min(padded_target, len(all_games))

            logger.info("Filtering games with trading cards...")
            games_with_cards = (
                self.trading_card_detector.filter_games_with_trading_cards(
                    all_games,
                    max_games=padded_target,
                    max_checks=self.settings.max_checks,
                    skip_failures=self.settings.skip_failures,
                )
            )
            logger.info(f"Found {len(games_with_cards)} games with trading cards")

            self.detailed_logger.log_api_results(
                "trading_cards", games_with_cards, {"total_checked": len(all_games)}
            )

        # Filter completed card drops
        games_with_drops = games_with_cards
        if self.settings.filter_completed_card_drops and steam_id:
            logger.info("Filtering completed card drops...")
            games_with_drops = self._filter_completed_card_drops(
                games_with_cards, steam_id
            )
            logger.info(
                f"After filtering drops: {len(games_with_drops)} games remaining"
            )

        # Remove user-specified exclusions
        excluded_games = []
        if self.settings.exclude_app_ids:
            before = len(games_with_drops)
            games_with_drops = [
                gid
                for gid in games_with_drops
                if gid not in self.settings.exclude_app_ids
            ]
            excluded_games = [
                gid for gid in all_games if gid in self.settings.exclude_app_ids
            ]
            removed = before - len(games_with_drops)
            if removed:
                logger.info("Excluded %s games via configuration overrides", removed)

        # Final selection
        final_games = games_with_drops[: self.settings.max_games_to_idle]

        # Log the complete process
        scraping_results = {}
        if self.settings.filter_completed_card_drops and steam_id:
            # Get scraping results if available
            from contextlib import suppress

            with suppress(Exception):
                scraping_results = {
                    app_id: self.card_drop_checker.has_remaining_drops(app_id, steam_id)
                    for app_id in games_with_cards
                }

        self.detailed_logger.log_filtering_process(
            steam_id or "manual",
            all_games,
            games_with_cards,
            games_with_drops,
            final_games,
            excluded_games,
            scraping_results,
        )

        if not final_games:
            logger.warning("No games found to idle after filtering")
            if self.settings.filter_completed_card_drops and len(
                games_with_drops
            ) == len(games_with_cards):
                # If filtering completed drops but no games remain and we couldn't actually filter,
                # try with a more lenient approach assuming games have drops
                # if status couldn't be determined
                logger.info(
                    "Attempting fallback: including games that couldn't be checked"
                )
                # Return a subset of games with cards, assuming they have drops
                # when status can't be determined
                fallback_games = games_with_cards[: self.settings.max_games_to_idle]
                if fallback_games:
                    logger.info(f"Using fallback games: {fallback_games}")
                    return fallback_games
            # If filtering successfully determined no games have remaining drops, return empty
            if len(games_with_drops) == 0:
                return []
            return self.settings.game_app_ids[: self.settings.max_games_to_idle]

        logger.info(f"Final games to idle: {final_games}")
        return final_games

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

        if not steam_id:
            return games

        # Prefer badge service over web scraping for authoritative data
        if self.badge_service and self.settings.steam_api_key:
            try:
                logger.info("Consulting badge service for authoritative data...")
                badge_filtered = self.badge_service.filter_games_with_remaining_cards(
                    games, steam_id
                )
                logger.info(
                    "Badge service completed: %s/%s games have remaining drops",
                    len(badge_filtered),
                    len(games),
                )
                if not badge_filtered:
                    logger.info(
                        "All candidate games have already dropped their trading cards"
                    )
                return badge_filtered
            except SteamAPITimeoutError as err:
                logger.warning(f"Badge progress request timed out: {err}")
            except BadgeServiceError as err:
                logger.warning(f"Failed to retrieve badge progress: {err}")

        # Fall back to web scraping if badge service is not available or failed
        try:
            logger.info("Checking card drops via web scraping...")
            scraping_filtered = self.card_drop_checker.filter_games_with_drops(
                games, steam_id
            )
            logger.info(
                "Web scraping completed: %s/%s games have drops",
                len(scraping_filtered),
                len(games),
            )

            if not scraping_filtered:
                logger.info(
                    "All candidate games have already dropped their trading cards"
                )
            return scraping_filtered

        except Exception as err:
            logger.warning(f"Web scraping failed: {err}")

        # If both badge service and web scraping failed, include all games as fallback
        logger.warning(
            "Could not check card drop status, including all games as fallback"
        )
        return games
