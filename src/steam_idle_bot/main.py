"""Main entry point for Steam Idle Bot."""

import argparse
import contextlib
import signal
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .config.settings import Settings
from .steam.badges import BadgeService
from .steam.client import SteamClientWrapper
from .steam.games import GameManager
from .steam.steam_utility import SteamUtilityIdleClient
from .steam.trading_cards import TradingCardDetector
from .utils.idle_tracker import IdleTracker
from .utils.logger import setup_logging
from .utils.preflight import preflight_warnings


class SteamIdleBot:
    """Main Steam Idle Bot application."""

    def __init__(self, settings: Settings, *, console_output: bool = True):
        self.settings = settings
        self._console_output = console_output
        self.logger = setup_logging(
            level=settings.log_level,
            log_file=settings.log_file,
            console_output=console_output,
        )
        self.client = build_steam_client(settings)
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
        self._steam_id: str | None = None
        self._stop_event = threading.Event()
        self._last_report = ""
        self.report_callback: Callable[[str], None] | None = None

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
        self.logger.info(f"  - Skip Completed Card Drops: {self.settings.filter_completed_card_drops}")
        self.logger.info(f"  - Use Owned Games: {self.settings.use_owned_games}")
        self.logger.info(f"  - Max Games to Idle: {self.settings.max_games_to_idle}")
        self.logger.info(f"  - Steam API Key: {'Set' if self.settings.steam_api_key else 'Not set'}")
        self.logger.info(f"  - Games to idle: {len(games)} games")
        self.logger.info(f"  - Game IDs: {games}")

    def _run_normal_mode(self) -> None:
        """Run in normal mode with Steam connection."""
        self.logger.info("Starting Steam Idle Bot...")

        for warning in preflight_warnings(self.settings.idling_backend):
            self.logger.warning(warning)

        if not self._ensure_client_ready():
            sys.exit(1)

        self._configure_authenticated_web_session()
        steam_id = self._resolve_active_steam_id()

        # Confirm the scraping session is genuinely authenticated (a built session
        # object can still be a logged-out store-only token, which silently breaks
        # drop detection). This logs a clear warning when it is not.
        if steam_id and self.settings.filter_completed_card_drops and hasattr(self.game_manager, "verify_web_session"):
            authenticated = self.game_manager.verify_web_session(steam_id)
            if not authenticated and self.settings.auto_browser_cookies and self._recover_session_via_browser(steam_id):
                self.game_manager.verify_web_session(steam_id)

        self._steam_id = steam_id

        # Get games to idle
        games = self.game_manager.get_games_to_idle(steam_id)

        if not games:
            self.logger.error("No games to idle")
            return

        # Store games list for report
        self._games_to_idle = games

        # Record initial card counts if badge service is available
        self._capture_initial_cards()

        # Start idling tracker (with resolved game names when available)
        self._idle_tracker.start_session(games, self._game_name_map())

        # Start idling
        if not self.client.start_idling(games):
            if not self._switch_to_steam_utility(
                "failed to start idling with python backend",
                games=games,
            ):
                self.logger.error("Failed to start idling")
                return
            steam_id = self._resolve_active_steam_id()

        self._stop_event.clear()
        self._print_status_panel(games)
        self._main_loop(games, steam_id=steam_id)

    def _main_loop(self, games: list[int], steam_id: str | None = None) -> None:
        """Main idle loop."""
        self.logger.info("Entering main idle loop...")
        self.logger.info("Press Ctrl+C to stop")

        refresh_interval = self.settings.refresh_interval_seconds
        last_refresh = time.time()
        loop_sleep_seconds = 1
        reconnect_cooldown_seconds = 10
        next_reconnect_attempt = 0.0

        while not self._stop_event.is_set():
            try:
                self.client.sleep(loop_sleep_seconds)  # Keep the loop responsive for GUI stop.
                if self._stop_event.is_set():
                    break

                # Refresh games every 10 minutes
                if time.time() - last_refresh >= refresh_interval:
                    self.logger.info("Refreshing game status...")

                    # Get fresh games list
                    refreshed_steam_id = self.client.steam_id or steam_id
                    if not refreshed_steam_id:
                        refreshed_steam_id = self.game_manager.resolve_active_steam_id()

                    new_games = self.game_manager.get_games_to_idle(refreshed_steam_id)

                    if new_games != games:
                        self.logger.info(f"Updating games from {len(games)} to {len(new_games)}")
                        games = new_games
                        self.client.refresh_games(games)
                        self._idle_tracker.game_names.update(self._game_name_map())

                    self._print_status_panel(games)
                    last_refresh = time.time()

                # Check connection
                if not self.client.is_connected():
                    now = time.time()
                    if now < next_reconnect_attempt:
                        continue

                    self.logger.warning("Lost connection to Steam, attempting to reconnect...")
                    if self.client.reconnect():
                        self.logger.info("Reconnected to Steam")
                        if games:
                            if self.client.start_idling(games):
                                self.logger.info(
                                    "Resumed idling %s games after reconnect",
                                    len(games),
                                )
                            else:
                                self.logger.warning("Reconnected but failed to resume idling")
                                if self._switch_to_steam_utility(
                                    "failed to resume idling after reconnect",
                                    games=games,
                                ):
                                    steam_id = self._resolve_active_steam_id()
                    else:
                        if self._switch_to_steam_utility(
                            "reconnect failure on python backend",
                            games=games,
                        ):
                            steam_id = self._resolve_active_steam_id()
                        else:
                            self.logger.warning("Reconnect attempt failed; retrying shortly")
                            next_reconnect_attempt = now + reconnect_cooldown_seconds

            except KeyboardInterrupt:
                self.logger.info("Received interrupt signal")
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                self.client.sleep(30)

    def stop(self) -> None:
        """Request the bot to stop at the next loop iteration."""
        if self._stop_event.is_set():
            return

        self.logger.info("Stop requested")
        self._stop_event.set()
        with contextlib.suppress(Exception):
            self.client.stop_idling()

    def signal_stop(self, signum: int | None = None) -> None:
        """Signal-handler-safe stop.

        Only sets the stop event so the main loop unwinds normally and the
        ``finally`` in :meth:`run` still emits the session report and runs
        cleanup. Network teardown (``stop_idling``/``logout``) is deferred to
        that cleanup instead of running inside the async signal handler.
        Critically, this lets ``SIGTERM`` (which Python does *not* turn into a
        ``KeyboardInterrupt``) shut the bot down gracefully — e.g. when
        ``run.sh`` is terminated — rather than killing it before the report.
        """
        self._stop_event.set()

    def _game_name_map(self) -> dict[int, str]:
        """Best-effort map of app_id -> name from the game manager."""
        names = getattr(self.game_manager, "game_names", None)
        return dict(names) if isinstance(names, dict) else {}

    def _print_status_panel(self, games: list[int]) -> None:
        """Render a concise terminal panel of what is currently being idled."""
        if not self._console_output:
            return

        try:
            from rich.box import ROUNDED
            from rich.console import Console
            from rich.table import Table
        except Exception:  # pragma: no cover - rich always present in deps
            return

        names = self._game_name_map()
        tracker = self._idle_tracker

        # Cards remaining per game, when the badge service can provide it.
        cards_remaining: dict[int, int] = {}
        for app_id in games:
            info = tracker.games.get(app_id)
            if info is not None and info.cards_before is not None:
                cards_remaining[app_id] = info.cards_before
        total_cards = sum(cards_remaining.values())

        table = Table(
            title="🎮 Steam Idle Bot — em idle agora",
            box=ROUNDED,
            title_style="bold cyan",
            header_style="bold",
            expand=False,
        )
        table.add_column("#", justify="right", style="dim", width=3)
        table.add_column("App ID", justify="right", style="cyan")
        table.add_column("Jogo", style="white", max_width=42, overflow="ellipsis")
        table.add_column("Cartas restantes", justify="right", style="yellow")
        table.add_column("Tempo idle", justify="right", style="green")

        for index, app_id in enumerate(games, start=1):
            info = tracker.games.get(app_id)
            name = names.get(app_id) or (info.name if info and info.name else f"App {app_id}")
            cards = str(cards_remaining[app_id]) if app_id in cards_remaining else "?"
            minutes = info.idle_minutes if info else 0.0
            table.add_row(str(index), str(app_id), name, cards, f"{minutes:.0f} min")

        cards_label = str(total_cards) if cards_remaining else "desconhecido (badge API sem dados)"
        summary = (
            f"[bold]{len(games)}[/bold] jogos em idle  •  "
            f"cartas restantes conhecidas: [bold]{cards_label}[/bold]  •  "
            f"sessão: [bold]{tracker.session_minutes:.0f} min[/bold]"
        )

        console = Console()
        console.print()
        console.print(table)
        console.print(summary)
        refresh_minutes = self.settings.refresh_interval_seconds / 60.0
        console.print(f"[dim]Atualiza a cada {refresh_minutes:.0f} min • Ctrl+C para parar e ver o relatório[/dim]")
        console.print()

    def _capture_initial_cards(self) -> None:
        """Capture the current number of cards remaining for each game."""
        try:
            badge_service = self.game_manager.badge_service
            if badge_service and hasattr(badge_service, "get_cards_remaining"):
                steam_id = self.client.steam_id
                if steam_id:
                    cards = badge_service.get_cards_remaining(steam_id)
                    for app_id, count in cards.items():
                        self._idle_tracker.set_cards_before(app_id, count)
                    self.logger.info(f"Captured initial card counts for {len(cards)} games")

            # Fallback/augment: counts parsed by the scraper during filtering. This
            # populates the panel/report when the badge API has no card data.
            if hasattr(self.game_manager, "get_drop_counts"):
                for app_id, count in self.game_manager.get_drop_counts().items():
                    if self._idle_tracker.has_pending_card_before(app_id) is False and (
                        app_id not in self._idle_tracker.games or self._idle_tracker.games[app_id].cards_before is None
                    ):
                        self._idle_tracker.set_cards_before(app_id, count)
        except Exception as e:
            self.logger.warning(f"Could not capture initial card counts: {e}")

    def _capture_final_cards(self) -> None:
        """Capture the final number of cards remaining for each game."""
        # Tracks whether at least one authenticated source returned data. When it
        # did, any idled game that started with known cards but is now absent from
        # the response has had its badge drained, so its final count is 0.
        authenticated_read = False
        try:
            badge_service = self.game_manager.badge_service
            if badge_service and hasattr(badge_service, "get_cards_remaining"):
                steam_id = self.client.steam_id
                if steam_id:
                    cards = badge_service.get_cards_remaining(steam_id)
                    if cards is not None:
                        authenticated_read = True
                        for app_id, count in cards.items():
                            self._idle_tracker.set_cards_after(app_id, count)
                        self.logger.info(f"Captured final card counts for {len(cards)} games")

            # Fallback/augment: re-scrape idled games to read current counts so the
            # session report can show how many cards dropped while idling.
            if self._games_to_idle and self._steam_id and hasattr(self.game_manager, "fetch_drop_counts"):
                counts = self.game_manager.fetch_drop_counts(self._games_to_idle, self._steam_id)
                if counts is not None:
                    authenticated_read = True
                    for app_id, count in counts.items():
                        game = self._idle_tracker.games.get(app_id)
                        if game is None or game.cards_after is None:
                            self._idle_tracker.set_cards_after(app_id, count)
        except Exception as e:
            self.logger.warning(f"Could not capture final card counts: {e}")

        if authenticated_read:
            self._backfill_drained_final_counts()

    def _backfill_drained_final_counts(self) -> None:
        """Set ``cards_after = 0`` for idled games drained during this session.

        A game that started with a known card count but is no longer reported by
        the authenticated badge/scraper read has no remaining drops, so the
        session report can show a confident before/after instead of ``?``.
        """
        for app_id in self._games_to_idle:
            game = self._idle_tracker.games.get(app_id)
            if game is not None and game.cards_before is not None and game.cards_after is None:
                self._idle_tracker.set_cards_after(app_id, 0)

    def _show_session_report(self) -> None:
        """Show the session report when bot stops."""
        self._idle_tracker.end_session()

        # Capture final card counts before showing report
        with contextlib.suppress(Exception):
            self._capture_final_cards()

        # Print report to console
        report = self._idle_tracker.format_report()
        self._last_report = report
        if self.report_callback:
            self.report_callback(report)
        else:
            print(report)

        # Save report to file
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        report_path = logs_dir / f"idle_report_{timestamp}.txt"
        self._idle_tracker.save_report(str(report_path))

    @property
    def last_report(self) -> str:
        """Return the most recent session report."""
        return self._last_report

    def _cleanup(self) -> None:
        """Clean up resources."""
        self.logger.info("Cleaning up...")

        if self.client:
            self.client.stop_idling()
            self.client.logout()

        self._stop_event.set()
        self.logger.info("Steam Idle Bot stopped")

    def _get_authenticated_web_session(self):
        """Build an authenticated Steam web session with backward compatibility."""
        client_get_web_session = getattr(self.client, "get_web_session", None)
        if not callable(client_get_web_session):
            return None

        kwargs = {
            "username": self.settings.username,
            "password": self.settings.password,
        }

        cookies = self.settings.steam_web_cookies or None
        if cookies is not None:
            kwargs["cookies"] = cookies

        try:
            return client_get_web_session(**kwargs)
        except TypeError:
            # Older test doubles or client shims may not accept the newer cookies
            # parameter yet. Retry with the legacy signature instead of failing.
            return client_get_web_session(
                username=self.settings.username,
                password=self.settings.password,
            )

    def _ensure_client_ready(self) -> bool:
        """Initialize and login the active backend, switching if needed."""
        if not self.client.initialize():
            self.logger.error("Failed to initialize Steam client")
            return self._switch_to_steam_utility("python client initialization failure")

        if not self.client.login():
            self.logger.error("Failed to login to Steam")
            return self._switch_to_steam_utility("python client login failure")

        return True

    def _recover_session_via_browser(self, steam_id: str) -> bool:
        """Rebuild the scraping session from cookies in a locally logged-in browser."""
        try:
            from .steam.browser_cookies import load_community_cookies

            cookies = load_community_cookies(steam_id, self.settings.browser_cookies_browser)
            if not cookies:
                self.logger.warning(
                    "Could not recover community cookies from a local browser. "
                    "Card-drop filtering stays conservative (drained games excluded). "
                    "Log into Steam in your browser, or set IDLING_BACKEND=python."
                )
                return False

            session = SteamClientWrapper._build_web_session_from_cookies(cookies)
            self.game_manager.set_web_session(session)
            self.logger.info("Recovered authenticated steamcommunity session from local browser cookies")
            return True
        except Exception as err:  # noqa: BLE001 - recovery is best-effort
            self.logger.debug(f"Browser cookie recovery failed: {err}")
            return False

    def _configure_authenticated_web_session(self) -> None:
        """Configure the scraping layer with any authenticated web session available."""
        web_session = self._get_authenticated_web_session()
        if web_session:
            self.game_manager.set_web_session(web_session)
            self.logger.info("Authenticated Steam web session enabled for card-drop checks")
        else:
            self.logger.warning("Could not obtain authenticated Steam web session")

    def _resolve_active_steam_id(self) -> str | None:
        """Resolve the best available active SteamID."""
        steam_id = self.client.steam_id
        if steam_id:
            return steam_id

        steam_id = self.game_manager.resolve_active_steam_id()
        if steam_id:
            self.logger.info(f"Resolved active Steam ID via steam-utility fallback: {steam_id}")
            return steam_id

        self.logger.warning("Active Steam ID unavailable; completed-drop filtering may be skipped")
        return None

    def _switch_to_steam_utility(
        self,
        reason: str,
        *,
        games: list[int] | None = None,
    ) -> bool:
        """Switch from the python backend to steam-utility when available."""
        if self.settings.idling_backend != "python":
            return False

        if not isinstance(self.client, SteamClientWrapper):
            return False

        if isinstance(self.client, SteamUtilityIdleClient):
            return False

        self.logger.warning(f"Switching idling backend from python to steam_utility: {reason}")

        with contextlib.suppress(Exception):
            self.client.stop_idling()
        with contextlib.suppress(Exception):
            self.client.logout()

        fallback_client = build_steam_client(self.settings, backend="steam_utility")
        if not fallback_client.initialize():
            self.logger.error("steam_utility fallback failed to initialize")
            return False
        if not fallback_client.login():
            self.logger.error("steam_utility fallback failed to connect")
            return False

        self.client = fallback_client
        self._configure_authenticated_web_session()

        if games and not self.client.start_idling(games):
            self.logger.error("steam_utility fallback failed to start idling")
            return False

        return True


def build_steam_client(settings: Settings, backend: str | None = None):
    """Create the configured Steam backend."""
    selected_backend = backend or settings.idling_backend
    if selected_backend == "steam_utility":
        return SteamUtilityIdleClient(settings)
    return SteamClientWrapper(settings)


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

    parser.add_argument(
        "--refresh-interval-seconds",
        type=int,
        help="Seconds between re-running the game-selection pipeline while idling (default 600)",
    )

    parser.add_argument("--config", type=str, help="Path to configuration file")

    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the desktop GUI instead of the terminal workflow",
    )

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


def _install_signal_handlers(bot: SteamIdleBot) -> None:
    """Route SIGINT/SIGTERM to a graceful stop so the session report still runs.

    Signal handlers can only be installed from the main thread; the GUI path
    runs the bot on a worker thread and never reaches here, so failures to set a
    handler are suppressed rather than fatal.
    """

    def _handler(signum: int, _frame: object) -> None:
        bot.logger.info("Received signal %s, stopping gracefully...", signum)
        bot.signal_stop(signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError, OSError, AttributeError):
            signal.signal(sig, _handler)


def main() -> None:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    try:
        if args.gui:
            from .gui import launch_gui

            launch_gui(config_path=args.config)
            return

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

        if args.refresh_interval_seconds is not None:
            settings.refresh_interval_seconds = args.refresh_interval_seconds

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
        _install_signal_handlers(bot)
        bot.run(dry_run=args.dry_run)

    except KeyboardInterrupt:
        print("\nBot interrupted by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
