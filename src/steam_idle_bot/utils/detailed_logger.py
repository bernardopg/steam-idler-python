"""Detailed logging for game filtering process."""

import json
import logging
import os
from datetime import datetime
from typing import Any

from ..config.settings import Settings


class DetailedLogger:
    """Provides detailed logging for game filtering and card drop checking."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.log_dir = "logs"
        self._ensure_log_dir()

    def _ensure_log_dir(self) -> None:
        """Ensure the logs directory exists."""
        os.makedirs(self.log_dir, exist_ok=True)

    def _get_log_filename(self) -> str:
        """Get the log filename with timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(self.log_dir, f"game_filtering_{timestamp}.json")

    def log_filtering_process(
        self,
        steam_id: str,
        all_games: list[int],
        games_with_cards: list[int],
        games_with_drops: list[int],
        final_games: list[int],
        excluded_games: list[int],
        scraping_results: dict[int, bool],
    ) -> None:
        """
        Log the complete filtering process.

        Args:
            steam_id: Steam ID being processed
            all_games: All owned games
            games_with_cards: Games that have trading cards
            games_with_drops: Games that have remaining drops
            final_games: Final list of games to idle
            excluded_games: Games excluded via configuration
            scraping_results: Results from web scraping
        """
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "steam_id": steam_id,
            "total_games": len(all_games),
            "games_with_cards": len(games_with_cards),
            "games_with_drops": len(games_with_drops),
            "final_games": len(final_games),
            "excluded_games": len(excluded_games),
            "details": {
                "all_games": all_games,
                "games_with_cards": games_with_cards,
                "games_with_drops": games_with_drops,
                "final_games": final_games,
                "excluded_games": excluded_games,
                "scraping_results": scraping_results,
            },
        }

        filename = self._get_log_filename()
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)

        logging.getLogger(__name__).info(f"Detailed filtering log saved to: {filename}")

    def log_scraping_result(
        self, app_id: int, steam_id: str, has_drops: bool, content_preview: str = ""
    ) -> None:
        """Log individual scraping results."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "app_id": app_id,
            "steam_id": steam_id,
            "has_drops": has_drops,
            "content_preview": content_preview[:200] + "..." if content_preview else "",
        }

        filename = os.path.join(self.log_dir, "scraping_results.json")

        # Append to existing file or create new one
        if os.path.exists(filename):
            with open(filename, encoding="utf-8") as f:
                try:
                    existing_data = json.load(f)
                except json.JSONDecodeError:
                    existing_data = []
        else:
            existing_data = []

        existing_data.append(log_entry)

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2, ensure_ascii=False)

    def log_api_results(
        self,
        api_name: str,
        games: list[int],
        results: dict[str, Any],
    ) -> None:
        """Log API results for debugging."""
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "api_name": api_name,
            "games_count": len(games),
            "games": games,
            "results": results,
        }

        filename = os.path.join(self.log_dir, f"{api_name}_results.json")

        # Append to existing file or create new one
        if os.path.exists(filename):
            with open(filename, encoding="utf-8") as f:
                try:
                    existing_data = json.load(f)
                except json.JSONDecodeError:
                    existing_data = []
        else:
            existing_data = []

        existing_data.append(log_data)

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2, ensure_ascii=False)
