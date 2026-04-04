"""Main entry point for Steam Idle Bot."""

import argparse
import contextlib
import sys
import time
from pathlib import Path

from .config.settings import Settings
from .steam.badges import BadgeService
from .steam.client import SteamClientWrapper
from .steam.games import GameManager
from .steam.trading_cards import TradingCardDetector
from .utils.idle_tracker import IdleTracker
from .utils.logger import setup_logging


class SteamIdleBot:
    """Main Steam Idle Bot application."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = setup_logging(level=settings.log_level, log_file=settings.log_file)
        self.client = SteamClientWrapper(settings)
        # Build retrying HTTP sessions for resilient HTTP calls
        store_session = TradingCardDetector.build_session()
        self.trading_card_detector = TradingCardDetector(
            timeout=settings.api_timeout,
            rate_limit_delay=settings.rate_limit_delay,
            cache_enabled=settings.enable_card_cache,
            cache_path=settings.card_cache_path,
            cache_ttl_days=settings.card_cache_ttl_days,
            session=store_session,
        )
        badge_service = None
        if settings.filter_completed_card_drops:
            badge_session = TradingCardDetector.build_session()
            badge_service = BadgeService(settings, session=badge_session)

        self.game_manager = GameManager(settings, self.trading_card_detector, badge_service)
        self._idle_tracker = IdleTracker()
        self._games_to_idle: list[int] = []
        self._running = False

    def run(self, dry_run: bool = False) -> None:
        """Run the Steam Idle Bot."""
        try:
            if dry_run:
                self._run_dry_mode()
                return

            self._run_normal_mode()

        except KeyboardInterrupt:
            self.logger.info("Bot interrupted by user")
        except Exception as e:
            self.logger.error(f"Bot error: {e}")
            raise
        finally:
            self._show_session_report()
            self._cleanup()

    def _run_dry_mode(self) -> None:
        """Run in dry-run mode for testing configuration."""
        self.logger.info("Running in dry-run mode...")

        # Get games to idle without network calls
        games = self.settings.game_app_ids[: self.settings.max_games_to_idle]

        self.logger.info("Configuration:")
        self.logger.info(f"  - Filter Trading Cards: {self.settings.filter_trading_cards}")
        self.logger.info(
            f"  - Skip Completed Card Drops: {self.settings.filter_completed_card_drops}"
        )
        self.logger.info(f"  - Use Owned Games: {self.settings.use_owned_games}")
        self.logger.info(f"  - Max Games to Idle: {self.settings.max_games_to_idle}")
        self.logger.info(
            f"  - Steam API Key: {'Set' if self.settings.steam_api_key else 'Not set'}"
        )
        self.logger.info(f"  - Games to idle: {len(games)} games")
        self.logger.info(f"  - Game IDs: {games}")

    def _run_normal_mode(self) -> None:
        """Run in normal mode with Steam connection."""
        self.logger.info("Starting Steam Idle Bot...")

        # Initialize Steam client
        if not self.client.initialize():
            self.logger.error("Failed to initialize Steam client")
            sys.exit(1)

        # Login to Steam
        if not self.client.login():
            self.logger.error("Failed to login to Steam")
            sys.exit(1)

        # Get games to idle
        games = self.game_manager.get_games_to_idle(self.client.steam_id)

        if not games:
            self.logger.error("No games to idle")
            return

        # Store games list for report
        self._games_to_idle = games

        # Record initial card counts if badge service is available
        self._capture_initial_cards()

        # Start idling tracker
        self._idle_tracker.start_session(games)

        # Start idling
        if not self.client.start_idling(games):
            self.logger.error("Failed to start idling")
            return

        self._running = True
        self._main_loop(games)

    def _main_loop(self, games: list[int]) -> None:
        """Main idle loop."""
        self.logger.info("Entering main idle loop...")
        self.logger.info("Press Ctrl+C to stop")

        refresh_interval = 600  # 10 minutes
        last_refresh = time.time()

        while self._running:
            try:
                self.client.sleep(60)  # Allow Steam client event loop to run

                # Refresh games every 10 minutes
                if time.time() - last_refresh >= refresh_interval:
                    self.logger.info("Refreshing game status...")

                    # Get fresh games list
                    new_games = self.game_manager.get_games_to_idle(self.client.steam_id)

                    if new_games != games:
                        self.logger.info(f"Updating games from {len(games)} to {len(new_games)}")
                        games = new_games
                        self.client.refresh_games(games)

                    last_refresh = time.time()

                # Check connection
                if not self.client.is_connected():
                    self.logger.warning("Lost connection to Steam, attempting to reconnect...")
                    # Could add reconnection logic here

            except KeyboardInterrupt:
                self.logger.info("Received interrupt signal")
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                self.client.sleep(30)

    def _capture_initial_cards(self) -> None:
        """Capture the current number of cards remaining for each game."""
        try:
            badge_service = self.game_manager.badge_service
            if badge_service and hasattr(badge_service, "_fetch_cards_remaining"):
                steam_id = self.client.steam_id
                if steam_id:
                    cards = badge_service._fetch_cards_remaining(steam_id)
                    for app_id, count in cards.items():
                        self._idle_tracker.set_cards_before(app_id, count)
                    self.logger.info(f"Captured initial card counts for {len(cards)} games")
            else:
                # No badge service available, set from game_manager if it has data
                if hasattr(self.game_manager, "_card_counts"):
                    for app_id, count in self.game_manager._card_counts.items():
                        self._idle_tracker.set_cards_before(app_id, count)
        except Exception as e:
            self.logger.debug(f"Could not capture initial card counts: {e}")

    def _capture_final_cards(self) -> None:
        """Capture the final number of cards remaining for each game."""
        try:
            badge_service = self.game_manager.badge_service
            if badge_service and hasattr(badge_service, "_fetch_cards_remaining"):
                steam_id = self.client.steam_id
                if steam_id:
                    cards = badge_service._fetch_cards_remaining(steam_id)
                    for app_id, count in cards.items():
                        self._idle_tracker.set_cards_after(app_id, count)
                    self.logger.info(f"Captured final card counts for {len(cards)} games")
            else:
                if hasattr(self.game_manager, "_card_counts"):
                    for app_id, count in self.game_manager._card_counts.items():
                        self._idle_tracker.set_cards_after(app_id, count)
        except Exception as e:
            self.logger.debug(f"Could not capture final card counts: {e}")

    def _show_session_report(self) -> None:
        """Show the session report when bot stops."""
        self._idle_tracker.end_session()

        # Capture final card counts before showing report
        with contextlib.suppress(Exception):
            self._capture_final_cards()

        # Print report to console
        report = self._idle_tracker.format_report()
        print(report)

        # Save report to file
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        report_path = logs_dir / f"idle_report_{timestamp}.txt"
        self._idle_tracker.save_report(str(report_path))

    def _cleanup(self) -> None:
        """Clean up resources."""
        self.logger.info("Cleaning up...")

        if self.client:
            self.client.stop_idling()
            self.client.logout()

        self._running = False
        self.logger.info("Steam Idle Bot stopped")


def create_parser() -> argparse.ArgumentParser:
    """Create command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Steam Idle Bot with Trading Card Support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Run normally
  %(prog)s --dry-run          # Test configuration
  %(prog)s --no-trading-cards # Skip trading card filtering
  %(prog)s --max-games 10     # Limit to 10 games
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not login or contact Steam; print configuration and chosen games then exit",
    )

    parser.add_argument(
        "--no-trading-cards",
        action="store_true",
        help="Skip trading card filtering for faster startup",
    )

    parser.add_argument(
        "--max-games",
        type=int,
        help="Maximum number of games to idle (overrides config)",
    )

    parser.add_argument("--config", type=str, help="Path to configuration file")

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable persistent trading-card cache",
    )

    parser.add_argument(
        "--max-checks",
        type=int,
        help="Cap the number of trading-card checks (performance tuning)",
    )

    parser.add_argument(
        "--skip-failures",
        action="store_true",
        help="Suppress non-timeout errors during trading-card checks",
    )

    parser.add_argument(
        "--keep-completed-drops",
        action="store_true",
        help="Include games even if all trading-card drops are exhausted",
    )

    return parser


def main() -> None:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    try:
        # Load settings
        settings_path = None
        if args.config:
            from pathlib import Path

            settings_path = Path(args.config)
        settings = Settings.load_from_file(settings_path)

        # Override settings from command line
        if args.no_trading_cards:
            settings.filter_trading_cards = False

        if args.max_games:
            settings.max_games_to_idle = args.max_games

        if args.no_cache:
            settings.enable_card_cache = False

        if args.max_checks is not None:
            settings.max_checks = args.max_checks

        if args.skip_failures:
            settings.skip_failures = True

        if args.keep_completed_drops:
            settings.filter_completed_card_drops = False

        # Create and run bot
        bot = SteamIdleBot(settings)
        bot.run(dry_run=args.dry_run)

    except KeyboardInterrupt:
        print("\nBot interrupted by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
