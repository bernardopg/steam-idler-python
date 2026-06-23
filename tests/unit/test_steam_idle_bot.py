"""Integration-flavoured tests for SteamIdleBot orchestration."""

from __future__ import annotations

import time
from collections import deque
from typing import Any, cast

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.main import SteamIdleBot
from steam_idle_bot.steam.client import SteamClientWrapper
from steam_idle_bot.steam.games import GameManager


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "username": "user",
        "password": "pass",
        "steam_api_key": "key",
        "use_owned_games": False,
        "max_games_to_idle": 2,
        "enable_card_cache": False,
        "filter_trading_cards": True,
        "filter_completed_card_drops": True,
    }
    base.update(overrides)
    return Settings(**base)


class FakeClient:
    def __init__(self, steam_id: str = "123") -> None:
        self.steam_id = steam_id
        self.initialize_calls = 0
        self.login_calls = 0
        self.start_calls: list[list[int]] = []
        self.refresh_calls: list[list[int]] = []
        self.sleep_calls: list[float] = []
        self.stop_called = False
        self.logout_called = False
        self.should_remain_connected = True

    def get_web_session(self, username=None, password=None, cookies=None):
        return None

    def reconnect(self) -> bool:
        return self.should_remain_connected

    def initialize(self) -> bool:
        self.initialize_calls += 1
        return True

    def login(self) -> bool:
        self.login_calls += 1
        return True

    def start_idling(self, games: list[int]) -> bool:
        self.start_calls.append(list(games))
        return True

    def refresh_games(self, games: list[int]) -> None:
        self.refresh_calls.append(list(games))

    def is_connected(self) -> bool:
        return self.should_remain_connected

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)

    def stop_idling(self) -> None:
        self.stop_called = True

    def logout(self) -> None:
        self.logout_called = True


class FakeGameManager:
    def __init__(self, results: deque[list[int]] | None, fallback_steam_id: str | None = None) -> None:
        self.results = results or deque()
        self.calls: list[str | None] = []
        self.fallback_steam_id = fallback_steam_id
        self.game_names: dict[int, str] = {}

    def get_games_to_idle(self, steam_id: str | None) -> list[int]:
        self.calls.append(steam_id)
        if not self.results:
            return []
        return self.results.popleft()

    def clear_cache(self) -> None:
        pass

    def resolve_active_steam_id(self) -> str | None:
        return self.fallback_steam_id


def test_run_normal_mode_starts_idling_and_enters_main_loop(monkeypatch):
    settings = make_settings()
    bot = SteamIdleBot(settings)

    client = FakeClient()
    games_sequence = deque([[220, 333]])
    manager = FakeGameManager(games_sequence)

    bot.client = cast(SteamClientWrapper, client)
    bot.game_manager = cast(GameManager, manager)

    captured_games: list[list[int]] = []

    def fake_main_loop(games: list[int], steam_id: str | None = None) -> None:
        del steam_id
        captured_games.append(list(games))

    monkeypatch.setattr(bot, "_main_loop", fake_main_loop)

    bot._run_normal_mode()

    assert client.initialize_calls == 1
    assert client.login_calls == 1
    assert client.start_calls == [[220, 333]]
    assert captured_games == [[220, 333]]
    assert manager.calls == [client.steam_id]


def test_run_normal_mode_uses_fallback_steam_id_when_client_missing(monkeypatch):
    settings = make_settings()
    bot = SteamIdleBot(settings)

    client = FakeClient(steam_id="")
    games_sequence = deque([[220]])
    manager = FakeGameManager(games_sequence, fallback_steam_id="76561198000000000")

    bot.client = cast(SteamClientWrapper, client)
    bot.game_manager = cast(GameManager, manager)

    captured_games: list[list[int]] = []
    monkeypatch.setattr(
        bot,
        "_main_loop",
        lambda games, steam_id=None: captured_games.append(list(games)),
    )

    bot._run_normal_mode()

    assert manager.calls == ["76561198000000000"]
    assert captured_games == [[220]]


def test_main_loop_handles_keyboard_interrupt(monkeypatch):
    settings = make_settings()
    bot = SteamIdleBot(settings, console_output=False)

    client = FakeClient()
    bot.client = cast(SteamClientWrapper, client)
    bot.game_manager = cast(FakeGameManager, FakeGameManager(deque()))

    def raising_sleep(seconds: float) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(client, "sleep", raising_sleep)
    monkeypatch.setattr(time, "time", lambda: 0.0)

    bot._stop_event.clear()
    # Should not raise
    bot._main_loop([1])


def test_main_loop_recovers_from_generic_error(monkeypatch):
    settings = make_settings()
    bot = SteamIdleBot(settings, console_output=False)

    client = FakeClient()
    bot.client = cast(SteamClientWrapper, client)
    bot.game_manager = cast(FakeGameManager, FakeGameManager(deque()))

    call_count = {"n": 0}

    def error_then_stop(seconds: float) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient error")
        bot._stop_event.set()

    monkeypatch.setattr(client, "sleep", error_then_stop)
    monkeypatch.setattr(time, "time", lambda: 0.0)

    bot._stop_event.clear()
    bot._main_loop([1])

    assert call_count["n"] == 2  # first raises, second stops


def test_stop_sets_event_and_stops_idling():
    settings = make_settings()
    bot = SteamIdleBot(settings, console_output=False)

    client = FakeClient()
    bot.client = cast(SteamClientWrapper, client)

    bot._stop_event.clear()
    assert not bot._stop_event.is_set()

    bot.stop()

    assert bot._stop_event.is_set()
    assert client.stop_called


def test_stop_is_idempotent():
    settings = make_settings()
    bot = SteamIdleBot(settings, console_output=False)

    client = FakeClient()
    bot.client = cast(SteamClientWrapper, client)

    bot._stop_event.set()
    bot.stop()  # should not raise or re-call stop_idling


def test_cleanup_sets_stop_event():
    settings = make_settings()
    bot = SteamIdleBot(settings, console_output=False)

    client = FakeClient()
    bot.client = cast(SteamClientWrapper, client)

    bot._stop_event.clear()
    bot._cleanup()

    assert bot._stop_event.is_set()
    assert client.stop_called
    assert client.logout_called


def test_game_name_map_returns_empty_when_no_names():
    settings = make_settings()
    bot = SteamIdleBot(settings, console_output=False)
    assert bot._game_name_map() == {}


def test_game_name_map_returns_manager_names():
    settings = make_settings()
    bot = SteamIdleBot(settings, console_output=False)
    manager = FakeGameManager(deque())
    manager.game_names = {10: "Game A", 20: "Game B"}
    bot.game_manager = cast(GameManager, manager)
    assert bot._game_name_map() == {10: "Game A", 20: "Game B"}
