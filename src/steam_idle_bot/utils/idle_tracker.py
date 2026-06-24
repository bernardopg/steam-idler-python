"""Tracks idling session statistics: time per game and card drops."""

from __future__ import annotations

__all__ = ["GameIdleInfo", "IdleTracker"]

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class GameIdleInfo:
    """Information about a single game's idling session."""

    app_id: int
    name: str = ""
    start_time: float | None = None
    end_time: float | None = None
    cards_before: int | None = None
    cards_after: int | None = None

    @property
    def cards_dropped(self) -> int:
        """Number of cards dropped for this game."""
        if self.cards_before is None or self.cards_after is None:
            return 0
        return max(0, self.cards_before - self.cards_after)

    @property
    def drop_status_known(self) -> bool:
        """Whether both before/after card counts are known for this game."""
        return self.cards_before is not None and self.cards_after is not None

    @property
    def idle_seconds(self) -> float:
        """Total seconds spent idling this game.

        While the session is live (``end_time`` not yet set) this reports the
        elapsed time up to now, so terminal panels show a growing duration
        instead of a frozen ``0``.
        """
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time is not None else time.time()
        return max(0.0, end - self.start_time)

    @property
    def idle_minutes(self) -> float:
        """Total minutes spent idling this game."""
        return self.idle_seconds / 60.0


class IdleTracker:
    """Tracks overall idling session statistics."""

    def __init__(self) -> None:
        self.session_start: float | None = None
        self.session_end: float | None = None
        self.games: dict[int, GameIdleInfo] = {}
        self.game_names: dict[int, str] = {}
        self._pending_cards_before: dict[int, int] = {}
        self._pending_cards_after: dict[int, int] = {}
        self.logger = logging.getLogger(__name__)

    def start_session(self, game_ids: list[int], game_names: dict[int, str] | None = None) -> None:
        """Record the start of an idling session."""
        self.session_start = time.time()
        if game_names:
            self.game_names.update(game_names)
        for app_id in game_ids:
            game = GameIdleInfo(
                app_id=app_id,
                name=self.game_names.get(app_id, ""),
                start_time=self.session_start,
            )
            if app_id in self._pending_cards_before:
                game.cards_before = self._pending_cards_before[app_id]
            if app_id in self._pending_cards_after:
                game.cards_after = self._pending_cards_after[app_id]
            self.games[app_id] = game
        self.logger.info(f"Idle tracker started for {len(game_ids)} games")

    def end_session(self) -> None:
        """Record the end of an idling session."""
        self.session_end = time.time()
        for game in self.games.values():
            game.end_time = self.session_end
        self.logger.info(f"Idle tracker stopped, session duration: {self.session_minutes:.1f} minutes")

    def set_cards_before(self, app_id: int, count: int) -> None:
        """Record the number of cards remaining before idling."""
        if app_id in self.games:
            self.games[app_id].cards_before = count
            return
        self._pending_cards_before[app_id] = count

    def has_pending_card_before(self, app_id: int) -> bool:
        """Check if a card count has been recorded but not yet applied to a game."""
        return app_id in self._pending_cards_before

    def set_cards_after(self, app_id: int, count: int) -> None:
        """Record the number of cards remaining after idling."""
        if app_id in self.games:
            self.games[app_id].cards_after = count
            return
        self._pending_cards_after[app_id] = count

    @property
    def session_seconds(self) -> float:
        """Total session duration in seconds.

        Falls back to the current time while the session is still running so the
        live status panel reflects real elapsed time instead of ``0``.
        """
        if self.session_start is None:
            return 0.0
        end = self.session_end if self.session_end is not None else time.time()
        return max(0.0, end - self.session_start)

    @property
    def session_minutes(self) -> float:
        """Total session duration in minutes."""
        return self.session_seconds / 60.0

    @property
    def total_cards_dropped(self) -> int:
        """Total cards dropped across all games."""
        return sum(game.cards_dropped for game in self.games.values())

    @property
    def games_with_drops(self) -> list[GameIdleInfo]:
        """Games that actually dropped cards."""
        return [g for g in self.games.values() if g.drop_status_known and g.cards_dropped > 0]

    @property
    def games_without_drops(self) -> list[GameIdleInfo]:
        """Games that did not drop cards."""
        return [g for g in self.games.values() if g.drop_status_known and g.cards_dropped == 0]

    @property
    def games_with_unknown_drops(self) -> list[GameIdleInfo]:
        """Games whose drop status could not be determined."""
        return [g for g in self.games.values() if not g.drop_status_known]

    def format_report(self) -> str:
        """Format a human-readable report of the idling session."""
        lines = []
        lines.append("")
        lines.append("=" * 70)
        lines.append("📊 STEAM IDLE BOT - SESSION REPORT")
        lines.append("=" * 70)
        lines.append("")

        # Session summary
        lines.append("📋 SESSION SUMMARY")
        lines.append("-" * 40)
        start_str = datetime.fromtimestamp(self.session_start).strftime("%H:%M:%S") if self.session_start else "N/A"
        end_str = datetime.fromtimestamp(self.session_end).strftime("%H:%M:%S") if self.session_end else "N/A"
        lines.append(f"  Start time:     {start_str}")
        lines.append(f"  End time:       {end_str}")
        lines.append(
            f"  Duration:       {self.session_minutes:.1f} minutes ({self.session_seconds:.0f} seconds)"  # noqa: E501
        )
        lines.append(f"  Games idled:    {len(self.games)}")
        total_label = "Total dropped"
        if self.games_with_unknown_drops:
            total_label = "Total dropped (confirmed)"
        lines.append(f"  {total_label}:  {self.total_cards_dropped} card(s)")
        lines.append("")

        # Games with drops
        games_with = self.games_with_drops
        games_without = self.games_without_drops
        games_unknown = self.games_with_unknown_drops

        if games_with:
            lines.append("🎮 GAMES THAT DROPPED CARDS")
            lines.append("-" * 40)
            lines.append(f"  {'Game':<35} {'Cards':>6} {'Time':>12}")
            lines.append(f"  {'':<35} {'':>6} {'(minutes)':>12}")
            lines.append(f"  {'-' * 33}  {'------':>6} {'------------':>12}")
            for game in games_with:
                name = game.name if game.name else f"App {game.app_id}"
                lines.append(f"  {name:<35} {game.cards_dropped:>6} {game.idle_minutes:>12.1f}")
            lines.append("")

        # Games without drops
        if games_without:
            lines.append("🎮 GAMES WITHOUT DROPS")
            lines.append("-" * 40)
            lines.append(f"  {'Game':<35} {'Time':>12}")
            lines.append(f"  {'':<35} {'(minutes)':>12}")
            lines.append(f"  {'-' * 33}  {'------------':>12}")
            for game in games_without:
                name = game.name if game.name else f"App {game.app_id}"
                lines.append(f"  {name:<35} {game.idle_minutes:>12.1f}")
            lines.append("")

        if games_unknown:
            lines.append("🎮 GAMES WITH UNKNOWN DROP STATUS")
            lines.append("-" * 40)
            lines.append(f"  {'Game':<35} {'Time':>12}")
            lines.append(f"  {'':<35} {'(minutes)':>12}")
            lines.append(f"  {'-' * 33}  {'------------':>12}")
            for game in games_unknown:
                name = game.name if game.name else f"App {game.app_id}"
                lines.append(f"  {name:<35} {game.idle_minutes:>12.1f}")
            lines.append("")

        # Per-game detailed breakdown
        lines.append("📝 DETAILED BREAKDOWN (ALL GAMES)")
        lines.append("-" * 40)
        for game in sorted(self.games.values(), key=lambda g: g.app_id):
            name = game.name if game.name else f"App {game.app_id}"
            cards_before = game.cards_before if game.cards_before is not None else "?"
            cards_after = game.cards_after if game.cards_after is not None else "?"
            dropped = game.cards_dropped
            status = "❓ unknown" if not game.drop_status_known else f"✅ +{dropped} drop(s)" if dropped > 0 else "❌ 0 drops"
            lines.append(f"  [{game.app_id}] {name}")
            lines.append(f"    Cards: {cards_before} → {cards_after} ({status})")
            lines.append(f"    Time:  {game.idle_minutes:.1f} minutes")
            lines.append("")

        lines.append("=" * 70)
        lines.append("Bot stopped. Thanks for using Steam Idle Bot!")
        lines.append("=" * 70)
        lines.append("")

        return "\n".join(lines)

    def save_report(self, filepath: str) -> None:
        """Save the report to a file."""
        report = self.format_report()
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        self.logger.info(f"Report saved to: {filepath}")

    def to_dict(self) -> dict:
        """Structured snapshot of the session, suitable for JSON checkpoints."""
        return {
            "session": {
                "start": self.session_start,
                "end": self.session_end,
                "seconds": round(self.session_seconds, 1),
                "minutes": round(self.session_minutes, 2),
            },
            "totals": {
                "games": len(self.games),
                "cards_dropped": self.total_cards_dropped,
                "games_with_drops": len(self.games_with_drops),
                "games_without_drops": len(self.games_without_drops),
                "games_unknown": len(self.games_with_unknown_drops),
            },
            "games": [
                {
                    "app_id": game.app_id,
                    "name": game.name or None,
                    "cards_before": game.cards_before,
                    "cards_after": game.cards_after,
                    "cards_dropped": game.cards_dropped,
                    "drop_status_known": game.drop_status_known,
                    "idle_minutes": round(game.idle_minutes, 2),
                }
                for game in sorted(self.games.values(), key=lambda g: g.app_id)
            ],
        }
