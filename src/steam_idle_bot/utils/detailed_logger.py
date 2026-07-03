"""Detailed logging for game filtering process."""

__all__ = ["DetailedLogger"]

import contextlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config.settings import Settings

# Retention caps: a 24/7 idler appends to these files on every refresh, so both
# the append-style JSON arrays and the per-run filtering snapshots are trimmed
# to keep logs/ bounded.
_MAX_APPEND_ENTRIES = 500
_MAX_FILTERING_SNAPSHOTS = 50


class DetailedLogger:
    """Provides detailed logging for game filtering and card drop checking."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.log_dir = Path("logs")
        self._ensure_log_dir()

    def _ensure_log_dir(self) -> None:
        """Ensure the logs directory exists."""
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _get_log_filename(self) -> Path:
        """Get the log filename with timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.log_dir / f"game_filtering_{timestamp}.json"

    def log_filtering_process(
        self,
        steam_id: str,
        all_games: list[int],
        games_with_cards: list[int],
        games_with_drops: list[int],
        final_games: list[int],
        excluded_games: list[int],
        scraping_results: dict[int, bool],
        drop_filter_source: str = "unknown",
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
            "drop_filter_source": drop_filter_source,
            "details": {
                "all_games": all_games,
                "games_with_cards": games_with_cards,
                "games_with_drops": games_with_drops,
                "final_games": final_games,
                "excluded_games": excluded_games,
                "scraping_results": scraping_results,
                "drop_filter_source": drop_filter_source,
            },
        }

        filename = self._get_log_filename()
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)

        self._prune_filtering_snapshots()
        logging.getLogger(__name__).info(f"Detailed filtering log saved to: {filename}")

    def _prune_filtering_snapshots(self) -> None:
        """Drop the oldest game_filtering_*.json files beyond the retention cap."""
        snapshots = sorted(self.log_dir.glob("game_filtering_*.json"))
        for stale in snapshots[:-_MAX_FILTERING_SNAPSHOTS]:
            with contextlib.suppress(OSError):
                stale.unlink()

    def log_scraping_result(self, app_id: int, steam_id: str, has_drops: bool, content_preview: str = "") -> None:
        """Log individual scraping results."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "app_id": app_id,
            "steam_id": steam_id,
            "has_drops": has_drops,
            "content_preview": content_preview[:200] + "..." if content_preview else "",
        }

        filename = self.log_dir / "scraping_results.json"

        # Append to existing file or create new one
        if filename.exists():
            with open(filename, encoding="utf-8") as f:
                try:
                    existing_data = json.load(f)
                except json.JSONDecodeError:
                    existing_data = []
        else:
            existing_data = []

        existing_data.append(log_entry)
        existing_data = existing_data[-_MAX_APPEND_ENTRIES:]

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2, ensure_ascii=False)

    def log_api_results(
        self,
        api_name: str,
        games: list[int],
        results: dict[int | str, Any],
    ) -> None:
        """Log API results for debugging."""
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "api_name": api_name,
            "games_count": len(games),
            "games": games,
            "results": results,
        }

        filename = self.log_dir / f"{api_name}_results.json"

        # Append to existing file or create new one
        if filename.exists():
            with open(filename, encoding="utf-8") as f:
                try:
                    existing_data = json.load(f)
                except json.JSONDecodeError:
                    existing_data = []
        else:
            existing_data = []

        existing_data.append(log_data)
        existing_data = existing_data[-_MAX_APPEND_ENTRIES:]

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2, ensure_ascii=False)
