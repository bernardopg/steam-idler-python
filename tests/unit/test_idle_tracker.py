"""Tests for idle tracker session reporting."""

from __future__ import annotations

from steam_idle_bot.utils.idle_tracker import GameIdleInfo, IdleTracker


def test_game_idle_info_properties() -> None:
    info = GameIdleInfo(app_id=10, start_time=100.0, end_time=220.0, cards_before=5, cards_after=3)
    assert info.cards_dropped == 2
    assert info.idle_seconds == 120.0
    assert info.idle_minutes == 2.0


def test_game_idle_info_counts_inventory_drops_when_remaining_count_lags() -> None:
    info = GameIdleInfo(app_id=10, cards_before=3, cards_after=3, inventory_drops=2)
    assert info.cards_dropped == 2
    assert info.drop_status_known is True


def test_game_idle_info_handles_missing_data() -> None:
    info = GameIdleInfo(app_id=10)
    assert info.cards_dropped == 0
    assert info.idle_seconds == 0.0
    assert info.idle_minutes == 0.0


def test_idle_tracker_full_report_and_save(tmp_path, monkeypatch) -> None:
    tracker = IdleTracker()

    times = iter([100.0, 220.0])
    monkeypatch.setattr("time.time", lambda: next(times))

    tracker.start_session([10, 20], game_names={10: "Alpha"})
    tracker.set_cards_before(10, 5)
    tracker.set_cards_after(10, 2)
    tracker.set_cards_before(20, 1)
    tracker.set_cards_after(20, 1)
    tracker.end_session()

    assert tracker.session_seconds == 120.0
    assert tracker.session_minutes == 2.0
    assert tracker.total_cards_dropped == 3
    assert [g.app_id for g in tracker.games_with_drops] == [10]
    assert [g.app_id for g in tracker.games_without_drops] == [20]

    report = tracker.format_report()
    assert "SESSION REPORT" in report
    assert "Alpha" in report
    assert "App 20" in report

    out_file = tmp_path / "reports" / "idle.txt"
    tracker.save_report(str(out_file))
    assert out_file.exists()
    saved = out_file.read_text(encoding="utf-8")
    assert "Bot stopped" in saved


def test_idle_tracker_ignores_unknown_game_card_updates() -> None:
    tracker = IdleTracker()
    tracker.start_session([1])

    tracker.set_cards_before(999, 3)
    tracker.set_cards_after(999, 1)

    assert 999 not in tracker.games
    assert tracker._pending_cards_before[999] == 3
    assert tracker._pending_cards_after[999] == 1


def test_idle_tracker_applies_pending_card_updates_when_session_starts() -> None:
    tracker = IdleTracker()

    tracker.set_cards_before(10, 5)
    tracker.set_cards_after(10, 2)
    tracker.set_inventory_drops(10, 1)
    tracker.start_session([10])

    assert tracker.games[10].cards_before == 5
    assert tracker.games[10].cards_after == 2
    assert tracker.games[10].inventory_drops == 1


def test_idle_tracker_report_shows_inventory_drops_even_when_counts_do_not_change(monkeypatch) -> None:
    tracker = IdleTracker()
    times = iter([100.0, 160.0])
    monkeypatch.setattr("steam_idle_bot.utils.idle_tracker.time.time", lambda: next(times))

    tracker.start_session([10], game_names={10: "Laggy Badge Page"})
    tracker.set_cards_before(10, 3)
    tracker.set_cards_after(10, 3)
    tracker.set_inventory_drops(10, 1)
    tracker.end_session()

    assert tracker.total_cards_dropped == 1
    assert [g.app_id for g in tracker.games_with_drops] == [10]
    report = tracker.format_report()
    assert "Laggy Badge Page" in report
    assert "Cards: 3 → 3 (✅ +1 drop(s))" in report
    assert "Inventory drops: +1" in report


def test_idle_tracker_update_games_stops_removed_games(monkeypatch) -> None:
    tracker = IdleTracker()

    times = iter([100.0, 160.0, 220.0])
    monkeypatch.setattr("steam_idle_bot.utils.idle_tracker.time.time", lambda: next(times))

    tracker.start_session([10, 20], game_names={10: "Active", 20: "Drained"})
    tracker.update_games([10])
    tracker.end_session()

    assert tracker.games[10].idle_seconds == 120.0
    assert tracker.games[20].idle_seconds == 60.0


def test_idle_tracker_reports_unknown_drop_status_separately(tmp_path, monkeypatch) -> None:
    tracker = IdleTracker()

    times = iter([100.0, 160.0])
    monkeypatch.setattr("time.time", lambda: next(times))

    tracker.start_session([10, 20], game_names={10: "Known", 20: "Unknown"})
    tracker.set_cards_before(10, 4)
    tracker.set_cards_after(10, 4)
    tracker.set_cards_before(20, 3)
    tracker.end_session()

    assert [g.app_id for g in tracker.games_without_drops] == [10]
    assert [g.app_id for g in tracker.games_with_unknown_drops] == [20]

    report = tracker.format_report()
    assert "GAMES WITH UNKNOWN DROP STATUS" in report
    assert "Total dropped (confirmed)" in report
    assert "Cards: 3 → ? (❓ unknown)" in report

    out_file = tmp_path / "reports" / "unknown.txt"
    tracker.save_report(str(out_file))
    assert out_file.exists()


def test_idle_seconds_live_until_end_set(monkeypatch) -> None:
    """While a session is live (end not set) duration must grow, not read 0."""
    info = GameIdleInfo(app_id=10, start_time=100.0)
    monkeypatch.setattr("steam_idle_bot.utils.idle_tracker.time.time", lambda: 700.0)
    assert info.idle_seconds == 600.0
    assert info.idle_minutes == 10.0
    # Once end_time is recorded it freezes to the recorded span.
    info.end_time = 400.0
    assert info.idle_seconds == 300.0


def test_session_seconds_live_until_end_set(monkeypatch) -> None:
    tracker = IdleTracker()
    monkeypatch.setattr("steam_idle_bot.utils.idle_tracker.time.time", lambda: 100.0)
    tracker.start_session([10])
    monkeypatch.setattr("steam_idle_bot.utils.idle_tracker.time.time", lambda: 760.0)
    assert tracker.session_seconds == 660.0
    assert tracker.session_minutes == 11.0


def test_to_dict_structured_snapshot(monkeypatch):
    tracker = IdleTracker()
    times = iter([100.0, 400.0])
    monkeypatch.setattr("steam_idle_bot.utils.idle_tracker.time.time", lambda: next(times))
    tracker.start_session([10, 20], game_names={10: "Alpha"})
    tracker.set_cards_before(10, 5)
    tracker.set_cards_after(10, 2)
    tracker.set_cards_before(20, 1)
    tracker.end_session()

    snap = tracker.to_dict()
    assert snap["session"]["seconds"] == 300.0
    assert snap["totals"]["games"] == 2
    assert snap["totals"]["cards_dropped"] == 3
    assert snap["totals"]["games_unknown"] == 1
    alpha = next(g for g in snap["games"] if g["app_id"] == 10)
    assert alpha == {
        "app_id": 10,
        "name": "Alpha",
        "cards_before": 5,
        "cards_after": 2,
        "inventory_drops": 0,
        "cards_dropped": 3,
        "drop_status_known": True,
        "idle_minutes": 5.0,
    }
