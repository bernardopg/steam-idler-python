"""Main entry point for Steam Idle Bot."""

import argparse
import contextlib
import json
import random
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
from .steam.inventory import InventoryCardDrop, SteamTradingCardInventory
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
        self._inventory_reader: SteamTradingCardInventory | None = None
        self._inventory_before: dict[str, InventoryCardDrop] = {}
        self._session_drained_app_ids: set[int] = set()
        self._stop_event = threading.Event()
        self._force_stop_event = threading.Event()
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

        # Snapshot inventory before idling. Badge pages can lag behind actual item
        # drops; inventory asset ids are the direct source of newly acquired cards.
        self._capture_initial_inventory()

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
        self._force_stop_event.clear()
        self._print_status_panel(games)
        self._main_loop(games, steam_id=steam_id)

    def _main_loop(self, games: list[int], steam_id: str | None = None) -> None:
        """Main idle loop."""
        self.logger.info("Entering main idle loop...")
        self.logger.info("Press Ctrl+C to stop")

        refresh_interval = self.settings.refresh_interval_seconds
        loop_sleep_seconds = 1
        # Exponential backoff with jitter so a Steam outage doesn't turn into a
        # tight reconnect storm (10s → 20s → ... capped at 5 min).
        reconnect_backoff_base = 10.0
        reconnect_backoff_max = 300.0
        reconnect_backoff = reconnect_backoff_base
        next_reconnect_attempt = 0.0

        loop_start = time.time()
        last_refresh = loop_start
        checkpoint_interval = self.settings.checkpoint_minutes * 60
        duration_limit = self.settings.duration_minutes * 60
        last_checkpoint = loop_start
        checkpoint_seq = 0

        while not self._stop_event.is_set():
            try:
                self.client.sleep(loop_sleep_seconds)  # Keep the loop responsive for GUI stop.
                if self._stop_event.is_set():
                    break

                now = time.time()

                # Stop after the configured run duration, if any.
                if duration_limit and now - loop_start >= duration_limit:
                    self.logger.info("Reached configured duration of %d min; stopping", self.settings.duration_minutes)
                    self._stop_event.set()
                    break

                # Periodic structured checkpoint.
                if checkpoint_interval and now - last_checkpoint >= checkpoint_interval:
                    checkpoint_seq += 1
                    self._write_checkpoint(checkpoint_seq, games)
                    last_checkpoint = now

                # Refresh games every refresh_interval seconds
                if now - last_refresh >= refresh_interval:
                    self.logger.info("Refreshing game status...")
                    self._capture_inventory_progress()

                    # Get fresh games list
                    refreshed_steam_id = self.client.steam_id or steam_id
                    if not refreshed_steam_id:
                        refreshed_steam_id = self.game_manager.resolve_active_steam_id()

                    new_games = self.game_manager.get_games_to_idle(
                        refreshed_steam_id,
                        quiet=True,
                        session_exclude_app_ids=self._session_drained_app_ids,
                    )

                    if new_games != games:
                        self.logger.info(f"Updating games from {len(games)} to {len(new_games)}")
                        game_names = self._game_name_map()
                        for app_id in new_games:
                            if app_id not in self._games_to_idle:
                                self._games_to_idle.append(app_id)
                        games = new_games
                        self.client.refresh_games(games)
                        self._idle_tracker.update_games(games, game_names)

                    # Reprint even when the list is unchanged so the panel's
                    # idle-time and session columns stay live between changes.
                    self._print_status_panel(games)
                    last_refresh = now

                # Check connection
                if not self.client.is_connected():
                    if now < next_reconnect_attempt:
                        continue

                    self.logger.warning("Lost connection to Steam, attempting to reconnect...")
                    if self.client.reconnect():
                        self.logger.info("Reconnected to Steam")
                        reconnect_backoff = reconnect_backoff_base
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
                            delay = reconnect_backoff + random.uniform(0, reconnect_backoff * 0.25)
                            self.logger.warning("Reconnect attempt failed; retrying in %.0fs", delay)
                            next_reconnect_attempt = now + delay
                            reconnect_backoff = min(reconnect_backoff * 2, reconnect_backoff_max)

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
        if self._stop_event.is_set():
            self._force_stop_event.set()
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
        summary = f"[bold]{len(games)}[/bold] jogos em idle  •  cartas restantes conhecidas: [bold]{cards_label}[/bold]  •  sessão: [bold]{tracker.session_minutes:.0f} min[/bold]"

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
                    self.logger.info(f"Captured initial badge API card counts for {len(cards)} games")

            # Fallback/augment: counts parsed by the scraper during filtering. This
            # populates the panel/report when the badge API has no card data.
            if hasattr(self.game_manager, "get_drop_counts"):
                scraper_count = 0
                active_games = set(self._games_to_idle)
                for app_id, count in self.game_manager.get_drop_counts().items():
                    if active_games and app_id not in active_games:
                        continue
                    if self._idle_tracker.has_pending_card_before(app_id) is False and (app_id not in self._idle_tracker.games or self._idle_tracker.games[app_id].cards_before is None):
                        self._idle_tracker.set_cards_before(app_id, count)
                        scraper_count += 1
                if scraper_count:
                    self.logger.info(f"Captured initial scraped card counts for {scraper_count} games")
        except Exception as e:
            self.logger.warning(f"Could not capture initial card counts: {e}")

    def _capture_initial_inventory(self) -> None:
        """Snapshot trading-card inventory assets before idling starts."""
        if not self._inventory_reader or not self._steam_id:
            return
        try:
            self._inventory_before = self._inventory_reader.snapshot(self._steam_id)
            self.logger.info("Captured initial trading-card inventory snapshot with %d cards", len(self._inventory_before))
        except Exception as e:
            self._inventory_before = {}
            self.logger.warning("Could not capture initial trading-card inventory snapshot: %s", e)

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
                        self.logger.info(f"Captured final badge API card counts for {len(cards)} games")

            # Fallback/augment: re-scrape idled games to read current counts so the
            # session report can show how many cards dropped while idling.
            if not self._force_stop_event.is_set() and self._games_to_idle and self._steam_id and hasattr(self.game_manager, "fetch_drop_counts"):
                counts = self.game_manager.fetch_drop_counts(
                    self._games_to_idle,
                    self._steam_id,
                    should_stop=self._force_stop_event.is_set,
                )
                if counts is not None:
                    authenticated_read = True
                    scraper_count = 0
                    active_games = set(self._games_to_idle)
                    for app_id, count in counts.items():
                        if active_games and app_id not in active_games:
                            continue
                        game = self._idle_tracker.games.get(app_id)
                        if game is None or game.cards_after is None:
                            self._idle_tracker.set_cards_after(app_id, count)
                            scraper_count += 1
                    if scraper_count:
                        self.logger.info(f"Captured final scraped card counts for {scraper_count} games")
        except Exception as e:
            self.logger.warning(f"Could not capture final card counts: {e}")

        if authenticated_read:
            self._backfill_drained_final_counts()

    def _capture_final_inventory(self) -> None:
        """Detect newly acquired trading cards by comparing inventory snapshots."""
        self._capture_inventory_progress(log_result=True)

    def _capture_inventory_progress(self, *, log_result: bool = False) -> None:
        """Update inventory-confirmed drops and mark drained games mid-session.

        Steam badge/drop pages can lag behind the inventory endpoint. During a
        long session, a game may already have dropped all known remaining cards
        while the badge page still says it has drops. Comparing the live
        inventory snapshot to the pre-run snapshot lets the refresh loop rotate
        that game out immediately when ``inventory_drops >= cards_before``.
        """
        if not self._inventory_reader or not self._steam_id or not self._inventory_before:
            return
        try:
            after = self._inventory_reader.snapshot(self._steam_id)
            new_by_app = self._inventory_reader.new_cards_by_app(self._inventory_before, after, self._games_to_idle)
            total = 0
            for app_id, cards in new_by_app.items():
                total += len(cards)
                self._idle_tracker.set_inventory_drops(app_id, len(cards))
                game = self._idle_tracker.games.get(app_id)
                if game is not None and game.cards_before is not None and len(cards) >= game.cards_before:
                    if app_id not in self._session_drained_app_ids:
                        self.logger.info(
                            "Inventory confirms app %s dropped all %s known remaining card(s); excluding it from the next refresh",
                            app_id,
                            game.cards_before,
                        )
                    self._session_drained_app_ids.add(app_id)
            if total and log_result:
                details = "; ".join(f"{app_id}: " + ", ".join(card.name for card in cards) for app_id, cards in sorted(new_by_app.items()))
                self.logger.info("Detected %d new trading-card inventory drop(s): %s", total, details)
            elif log_result:
                self.logger.info("Detected 0 new trading-card inventory drops")
        except Exception as e:
            self.logger.warning("Could not capture trading-card inventory progress: %s", e)

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

    def _write_checkpoint(self, sequence: int, games: list[int]) -> None:
        """Write a structured JSON + Markdown checkpoint of the live session."""
        try:
            snapshot = self._idle_tracker.to_dict()
            snapshot["checkpoint"] = {
                "sequence": sequence,
                "selected_games": list(games),
                "refresh_interval_seconds": self.settings.refresh_interval_seconds,
            }
            checkpoints_dir = Path("logs") / "checkpoints"
            checkpoints_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            base = checkpoints_dir / f"checkpoint_{sequence:03d}_{stamp}"
            base.with_suffix(".json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            base.with_suffix(".md").write_text(self._idle_tracker.format_report(), encoding="utf-8")
            self.logger.info("Wrote checkpoint #%d to %s.{json,md}", sequence, base)
        except Exception as e:
            self.logger.warning(f"Could not write checkpoint #{sequence}: {e}")

    def _show_session_report(self) -> None:
        """Show the session report when bot stops."""
        self._idle_tracker.end_session()

        # Capture final card counts before showing report
        with contextlib.suppress(Exception):
            self._capture_final_cards()
        with contextlib.suppress(Exception):
            self._capture_final_inventory()

        # Optionally re-scrape after a delay: Steam badge pages can lag behind
        # the actual drops at the moment idling stops.
        delay = self.settings.post_run_verify_seconds
        if delay > 0 and self._games_to_idle and not self._force_stop_event.is_set():
            self.logger.info("Re-verifying card counts in %ds (post-run verification)...", delay)
            self.client.sleep(delay)
            with contextlib.suppress(Exception):
                self._capture_final_cards()
            with contextlib.suppress(Exception):
                self._capture_final_inventory()

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
                self.logger.warning("Could not recover community cookies from a local browser. Card-drop filtering stays conservative (drained games excluded). Log into Steam in your browser, or set IDLING_BACKEND=python.")
                return False

            session = SteamClientWrapper._build_web_session_from_cookies(cookies)
            self.game_manager.set_web_session(session)
            self._inventory_reader = SteamTradingCardInventory(self.settings, session)
            self.settings.steam_web_cookies = cookies
            try:
                self._persist_recovered_web_cookies(cookies)
                self.logger.info("Saved recovered steamcommunity cookies to .env for future runs")
            except Exception as err:  # noqa: BLE001 - recovery itself already succeeded
                self.logger.debug("Could not persist recovered browser cookies: %s", err)
            self.logger.info("Recovered authenticated steamcommunity session from local browser cookies")
            return True
        except Exception as err:  # noqa: BLE001 - recovery is best-effort
            self.logger.debug(f"Browser cookie recovery failed: {err}")
            return False

    @staticmethod
    def _persist_recovered_web_cookies(cookies: dict[str, str]) -> None:
        """Persist only STEAM_WEB_COOKIES without rewriting other .env settings.

        Browser recovery often happens during a run with temporary CLI overrides
        such as ``--max-games`` or ``--duration-minutes``. Calling
        ``Settings.save_to_env_file()`` here would serialize those temporary
        overrides back into the user's persistent config, so update just the
        recovered cookie line instead.
        """
        target = Path(".env")
        rendered = "STEAM_WEB_COOKIES=" + json.dumps(cookies, ensure_ascii=False, separators=(",", ":"))
        lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []

        for index, line in enumerate(lines):
            if line.startswith("STEAM_WEB_COOKIES="):
                lines[index] = rendered
                break
        else:
            lines.append(rendered)

        target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _configure_authenticated_web_session(self) -> None:
        """Configure the scraping layer with any authenticated web session available."""
        web_session = self._get_authenticated_web_session()
        if web_session:
            self.game_manager.set_web_session(web_session)
            self._inventory_reader = SteamTradingCardInventory(self.settings, web_session)
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
        "--web",
        action="store_true",
        help="Launch the web UI (FastAPI + React) instead of the terminal workflow",
    )

    parser.add_argument(
        "--web-port",
        type=int,
        default=8765,
        help="Port for the web UI server (default 8765)",
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

    parser.add_argument(
        "--checkpoint-minutes",
        type=int,
        help="Write a JSON/Markdown checkpoint every N minutes while idling (0 disables)",
    )

    parser.add_argument(
        "--duration-minutes",
        type=int,
        help="Stop idling after N minutes (0 runs until interrupted)",
    )

    parser.add_argument(
        "--post-run-verify-seconds",
        type=int,
        help="Re-scrape card counts this many seconds after stopping (0 disables)",
    )

    parser.add_argument(
        "--stop-app-ids",
        type=str,
        help="Stop running steam-utility idles for these App IDs (JSON or CSV) and exit",
    )

    return parser


def _parse_app_id_list(raw: str) -> list[int]:
    """Parse an App ID list given as JSON (``[570,730]``) or CSV (``570,730``)."""
    raw = raw.strip()
    if not raw:
        return []
    with contextlib.suppress(json.JSONDecodeError):
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [int(item) for item in parsed]
    return [int(part) for part in raw.replace(";", ",").split(",") if part.strip()]


def _stop_app_ids(settings: Settings, app_ids: list[int]) -> int:
    """Stop steam-utility idle processes for the given App IDs. Returns count stopped."""
    from .steam.steam_utility import SteamUtilityIdleClient

    client = SteamUtilityIdleClient(settings)
    existing = client.bridge.find_idle_pids()
    stopped = 0
    for app_id in app_ids:
        for pid in existing.get(app_id, []):
            client._stop_pid(pid)
            stopped += 1
    if stopped:
        print(f"Stopped {stopped} steam-utility idle process(es) for {app_ids}")
    else:
        print(f"No running steam-utility idles found for {app_ids}")
    return stopped


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


def _load_settings_from_args(args: argparse.Namespace) -> Settings:
    """Load settings and apply CLI overrides shared by terminal and GUI modes."""
    settings_path = Path(args.config) if args.config else None
    settings = Settings.load_from_file(settings_path)
    _apply_cli_overrides(settings, args)
    return settings


def _apply_cli_overrides(settings: Settings, args: argparse.Namespace) -> None:
    """Apply parser overrides to a Settings instance."""
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

    if args.checkpoint_minutes is not None:
        settings.checkpoint_minutes = args.checkpoint_minutes

    if args.duration_minutes is not None:
        settings.duration_minutes = args.duration_minutes

    if args.post_run_verify_seconds is not None:
        settings.post_run_verify_seconds = args.post_run_verify_seconds


def main() -> None:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    try:
        if getattr(args, "web", False) and not getattr(args, "stop_app_ids", None):
            from .webapi import launch_web

            launch_web(port=getattr(args, "web_port", 8765))
            return

        if args.gui and not getattr(args, "stop_app_ids", None):
            from .gui import launch_gui

            try:
                settings = _load_settings_from_args(args)
            except Exception:
                settings = None
            launch_gui(
                config_path=args.config,
                initial_settings=settings,
                initial_dry_run=args.dry_run,
            )
            return

        settings = _load_settings_from_args(args)

        # Maintenance mode: stop idles for specific App IDs and exit.
        if args.stop_app_ids:
            _stop_app_ids(settings, _parse_app_id_list(args.stop_app_ids))
            return

        if args.gui:
            from .gui import launch_gui

            launch_gui(
                config_path=args.config,
                initial_settings=settings,
                initial_dry_run=args.dry_run,
            )
            return

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
