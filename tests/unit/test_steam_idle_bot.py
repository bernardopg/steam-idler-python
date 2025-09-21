"""Integration-flavoured tests for SteamIdleBot orchestration."""

from __future__ import annotations

import time
from collections import deque
from typing import Optional, cast

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.main import SteamIdleBot
from steam_idle_bot.steam.client import SteamClientWrapper
from steam_idle_bot.steam.games import GameManager


def make_settings(**overrides) -> Settings:
    base = {
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

    def initialize(self) -> bool:  # pragma: no cover - simple setter
        self.initialize_calls += 1
        return True

    def login(self) -> bool:  # pragma: no cover - simple setter
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

    def stop_idling(self) -> None:  # pragma: no cover - simple setter
        self.stop_called = True

    def logout(self) -> None:  # pragma: no cover - simple setter
        self.logout_called = True


class FakeGameManager:
    def __init__(self, results: Optional[deque[list[int]]]) -> None:
        self.results = results or deque()
        self.calls: list[Optional[str]] = []

    def get_games_to_idle(self, steam_id: Optional[str]) -> list[int]:
        self.calls.append(steam_id)
        if not self.results:
            return []
        return self.results.popleft()

    def clear_cache(self) -> None:  # pragma: no cover - compatibility
        pass


def test_run_normal_mode_starts_idling_and_enters_main_loop(monkeypatch):
    settings = make_settings()
    bot = SteamIdleBot(settings)

    client = FakeClient()
    games_sequence = deque([[220, 333]])
    manager = FakeGameManager(games_sequence)

    bot.client = cast(SteamClientWrapper, client)
    bot.game_manager = cast(GameManager, manager)

    captured_games: list[list[int]] = []

    def fake_main_loop(games: list[int]) -> None:
        captured_games.append(list(games))

    monkeypatch.setattr(bot, "_main_loop", fake_main_loop)

    bot._run_normal_mode()

    assert client.initialize_calls == 1
    assert client.login_calls == 1
    assert client.start_calls == [[220, 333]]
    assert captured_games == [[220, 333]]
    assert manager.calls == [client.steam_id]


def test_main_loop_refreshes_games_when_library_changes(monkeypatch):
    settings = make_settings()
    bot = SteamIdleBot(settings)

    client = FakeClient()
    manager = FakeGameManager(deque([[222, 444]]))
    bot.client = cast(SteamClientWrapper, client)
    bot.game_manager = cast(GameManager, manager)

    # Arrange time progression: initial last_refresh=0, then jump beyond interval
    times = iter([0.0, 700.0, 700.0])
    monkeypatch.setattr(time, "time", lambda: next(times))

    refreshed: list[list[int]] = []

    def record_refresh(games: list[int]) -> None:
        refreshed.append(list(games))
        bot._running = False  # stop loop after first refresh

    monkeypatch.setattr(client, "refresh_games", record_refresh)

    def controlled_sleep(seconds: float) -> None:
        client.sleep_calls.append(seconds)
        # allow loop to continue; stop flag handled in refresh callback

    monkeypatch.setattr(client, "sleep", controlled_sleep)

    bot._running = True
    bot._main_loop([111, 222])

    assert refreshed == [[222, 444]]
    assert client.sleep_calls == [60]
    assert manager.calls == [client.steam_id]
