"""How main.SteamIdleBot wires the native backend (selection, fallback, web session refresh)."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

from test_main_extra import DummyGameManager, make_bot, make_settings

from steam_idle_bot.main import build_steam_client
from steam_idle_bot.steam.native import NativeSteamClient

main_module = importlib.import_module("steam_idle_bot.main")


def test_build_steam_client_selects_native(tmp_path):
    settings = make_settings(idling_backend="native", native_session_path=str(tmp_path / "s.json"))
    client = build_steam_client(settings)
    assert isinstance(client, NativeSteamClient)
    assert client._store.path == tmp_path / "s.json"


def test_native_settings_round_trip_through_env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_settings(idling_backend="native", native_session_path="custom/session.json").save_to_env_file(tmp_path / ".env")
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "IDLING_BACKEND=native" in text and "NATIVE_SESSION_PATH=custom/session.json" in text

    from steam_idle_bot.config.settings import Settings

    reloaded = Settings()
    assert reloaded.idling_backend == "native" and reloaded.native_session_path == "custom/session.json"


def test_native_backend_falls_back_to_steam_utility(tmp_path):
    settings = make_settings(idling_backend="native", native_session_path=str(tmp_path / "s.json"))
    bot = make_bot(settings=settings, client=NativeSteamClient(settings))
    fallback = MagicMock()
    fallback.initialize.return_value = True
    fallback.login.return_value = True
    fallback.start_idling.return_value = True
    with patch("steam_idle_bot.main.build_steam_client", return_value=fallback):
        assert bot._switch_to_steam_utility("native login failure", games=[570]) is True
    assert bot.client is fallback


def test_refresh_web_session_swaps_in_a_fresh_session(monkeypatch):
    bot = make_bot()
    fresh = object()
    bot.client.refresh_web_session_if_stale = MagicMock(return_value=fresh)
    readers = []
    monkeypatch.setattr(main_module, "SteamTradingCardInventory", lambda settings, session: readers.append(session) or "reader")

    bot._refresh_web_session_if_stale()

    assert bot.game_manager._web_session is fresh
    assert readers == [fresh] and bot._inventory_reader == "reader"


def test_refresh_web_session_is_a_noop_when_not_stale_unsupported_or_failing():
    bot = make_bot()
    bot.game_manager = DummyGameManager()
    bot._refresh_web_session_if_stale()  # DummyClient has no refresh method
    assert bot.game_manager._web_session is None

    bot.client.refresh_web_session_if_stale = MagicMock(return_value=None)
    bot._refresh_web_session_if_stale()
    assert bot.game_manager._web_session is None

    bot.client.refresh_web_session_if_stale = MagicMock(side_effect=RuntimeError("boom"))
    bot._refresh_web_session_if_stale()  # logged, not raised
    assert bot.game_manager._web_session is None


def test_main_loop_refresh_tick_refreshes_web_session(monkeypatch):
    bot = make_bot(games=[570])
    bot.settings.refresh_interval_seconds = 10
    calls = []
    monkeypatch.setattr(bot, "_refresh_web_session_if_stale", lambda: calls.append("refresh"))
    monkeypatch.setattr(bot, "_capture_inventory_progress", lambda: None)
    monkeypatch.setattr(bot, "_print_status_panel", lambda games: None)

    clock = iter([0.0, 0.0, 11.0, 11.0, 11.0])
    monkeypatch.setattr(main_module.time, "time", lambda: next(clock, 11.0))

    def sleep(_seconds):
        if calls:
            bot._stop_event.set()

    bot.client.sleep = sleep
    bot._main_loop([570], steam_id="123")
    assert calls == ["refresh"]
