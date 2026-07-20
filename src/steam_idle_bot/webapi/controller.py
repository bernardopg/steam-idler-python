"""UI-agnostic bot lifecycle controller for the web API.

Runs the bot on a worker thread:
daemon thread, log records and lifecycle events are buffered in a sequenced
ring buffer that WebSocket clients drain with a cursor, and Steam Guard
requests block the worker on an Event until the API delivers a code.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config.settings import Settings

APP_LOGGER_NAME = "steam_idle_bot"
_EVENT_BUFFER_SIZE = 4000
_LOG_BACKLOG_SIZE = 1000


@dataclass
class AuthCodeRequest:
    """A pending Steam Guard / 2FA code request from the bot worker."""

    is_2fa: bool
    code_mismatch: bool
    event: threading.Event = field(default_factory=threading.Event)
    code: str | None = None


class _EventLogHandler(logging.Handler):
    """Forwards bot log records to the controller's event buffer."""

    def __init__(self, controller: BotController) -> None:
        super().__init__()
        self._controller = controller

    def emit(self, record: logging.LogRecord) -> None:
        with suppress(Exception):
            self._controller._emit(
                {
                    "type": "log",
                    "level": record.levelname,
                    "line": self.format(record),
                }
            )


class BotController:
    """Owns the bot worker thread and exposes state safe to read from asyncio."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: deque[tuple[int, dict[str, Any]]] = deque(maxlen=_EVENT_BUFFER_SIZE)
        self._log_backlog: deque[dict[str, Any]] = deque(maxlen=_LOG_BACKLOG_SIZE)
        self._seq = 0
        self._worker: threading.Thread | None = None
        self._bot: Any | None = None
        self.status = "stopped"
        self.dry_run = False
        self.last_error: str | None = None
        self.last_report = ""
        self.pending_auth: AuthCodeRequest | None = None

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _emit(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            self._events.append((self._seq, event))
            if event.get("type") == "log":
                self._log_backlog.append(event)

    def events_since(self, cursor: int) -> tuple[list[dict[str, Any]], int]:
        """Return events newer than *cursor* and the new cursor position."""
        with self._lock:
            fresh = [event for seq, event in self._events if seq > cursor]
            return fresh, self._seq

    def log_backlog(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._log_backlog)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    def start(self, settings: Settings, dry_run: bool = False) -> None:
        """Start the bot on a worker thread. Raises RuntimeError if running."""
        if self.is_running:
            raise RuntimeError("Bot is already running")

        self.last_error = None
        self.dry_run = dry_run
        self._set_status("starting")
        worker = threading.Thread(
            target=self._run_worker,
            args=(settings, dry_run),
            daemon=True,
            name="steam-idle-bot-web-worker",
        )
        self._worker = worker
        worker.start()

    def stop(self) -> None:
        bot = self._bot
        if bot is None:
            return
        self._set_status("stopping")
        with suppress(Exception):
            bot.stop()

    def provide_auth_code(self, code: str) -> bool:
        """Deliver a Steam Guard code to the blocked worker."""
        request = self.pending_auth
        if request is None:
            return False
        request.code = code.strip() or None
        self.pending_auth = None
        request.event.set()
        return True

    def _set_status(self, status: str) -> None:
        self.status = status
        self._emit({"type": "status", "state": status})

    def _request_auth_code(self, is_2fa: bool, code_mismatch: bool) -> str | None:
        request = AuthCodeRequest(is_2fa=is_2fa, code_mismatch=code_mismatch)
        self.pending_auth = request
        self._emit({"type": "auth_request", "is_2fa": is_2fa, "code_mismatch": code_mismatch})
        request.event.wait()
        return request.code

    def _run_worker(self, settings: Settings, dry_run: bool) -> None:
        from ..main import SteamIdleBot  # deferred: heavy steam imports

        bot = SteamIdleBot(settings, console_output=False)
        if hasattr(bot.client, "auth_code_provider"):
            bot.client.auth_code_provider = self._request_auth_code

        runs_dir = Path("logs") / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_log_path = runs_dir / f"run_{time.strftime('%Y%m%d_%H%M%SZ', time.gmtime())}.log"
        self._emit({"type": "log", "level": "INFO", "line": f"Run log: {run_log_path}"})

        def emit_report(report: str) -> None:
            self.last_report = report
            self._emit({"type": "report", "text": report})
            with suppress(Exception), run_log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\n{report}\n")

        bot.report_callback = emit_report

        event_handler = _EventLogHandler(self)
        event_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S"))
        file_handler = logging.FileHandler(run_log_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
        logger = logging.getLogger(APP_LOGGER_NAME)
        logger.addHandler(event_handler)
        logger.addHandler(file_handler)

        self._bot = bot
        self._set_status("running")
        try:
            bot.run(dry_run=dry_run)
        except Exception as exc:
            self.last_error = str(exc)
            self._emit({"type": "error", "message": str(exc)})
        finally:
            logger.removeHandler(event_handler)
            logger.removeHandler(file_handler)
            file_handler.close()
            self._bot = None
            self.pending_auth = None
            if bot.last_report:
                self.last_report = bot.last_report
            self._set_status("error" if self.last_error else "stopped")
            self._emit({"type": "finished", "report": self.last_report})

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Current account/session stats, safe to serialize as JSON."""
        bot = self._bot
        games: list[dict[str, Any]] = []
        session_minutes = 0.0
        total_drops = 0
        cards_known: int | None = None
        account: str | None = None

        if bot is not None:
            with suppress(Exception):
                account = getattr(bot.client, "username", None)
            tracker = getattr(bot, "_idle_tracker", None)
            if tracker is not None:
                with suppress(Exception):
                    session_minutes = tracker.session_minutes
                    known: list[int] = []
                    for app_id, info in tracker.games.items():
                        drops = info.cards_dropped
                        total_drops += drops
                        remaining = max(info.cards_before - drops, 0) if info.cards_before is not None else None
                        if remaining is not None:
                            known.append(remaining)
                        games.append(
                            {
                                "app_id": app_id,
                                "name": info.name or f"App {app_id}",
                                "cards_remaining": remaining,
                                "drops": drops,
                                "idle_minutes": round(info.idle_minutes, 1),
                            }
                        )
                    if known:
                        cards_known = sum(known)

        return {
            "status": self.status,
            "running": self.is_running,
            "dry_run": self.dry_run,
            "account": account,
            "session_minutes": round(session_minutes, 1),
            "games": games,
            "games_count": len(games),
            "cards_remaining_known": cards_known,
            "session_drops": total_drops,
            "auth_pending": self.pending_auth is not None,
            "last_error": self.last_error,
        }
