"""Additional tests for GameManager API and fallback paths."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.games import GameManager
from steam_idle_bot.steam.steam_utility import SteamUtilityError
from steam_idle_bot.utils.exceptions import (
    BadgeServiceError,
    GameLibraryError,
    SteamAPITimeoutError,
)


class StubDetector:
    def __init__(self, allowed=None):
        self.allowed = set(allowed or [])

    def filter_games_with_trading_cards(self, game_ids, **kwargs):
        return [g for g in game_ids if not self.allowed or g in self.allowed]

    def clear_cache(self):
        return None


class StubCardDropChecker:
    def __init__(self, result=None, exc=None):
        self.result = result or []
        self.exc = exc
        self.has_authenticated_session = False

    def filter_games_with_drops(self, games, steam_id):
        if self.exc:
            raise self.exc
        return list(self.result)

    def set_session(self, session, *, authenticated_session=False):
        self.has_authenticated_session = authenticated_session


class StubBadge:
    def __init__(self, result=None, exc=None):
        self.result = result or []
        self.exc = exc

    def partition_games_by_remaining_cards(self, games, steam_id):
        if self.exc:
            raise self.exc
        return list(self.result), []

    def filter_games_with_remaining_cards(self, games, steam_id):
        if self.exc:
            raise self.exc
        return list(self.result)

    def clear_cache(self):
        return None


class StubSteamUtilityBridge:
    def __init__(self, apps=None, report=None, exc=None):
        self.apps = apps if apps is not None else [{"AppId": 77}, {"AppId": 88}]
        self.report = report if report is not None else {"activeSteamId": 76561198000000000}
        self.exc = exc

    def run_json_command(self, command):
        assert command == "apps"
        if self.exc:
            raise self.exc
        return self.apps

    def get_state_report(self):
        if self.exc:
            raise self.exc
        return dict(self.report)


def make_settings(**overrides):
    base = {
        "username": "user",
        "password": "pass",
        "steam_api_key": "key",
        "use_owned_games": True,
        "game_app_ids": [1, 2, 3],
        "filter_trading_cards": True,
        "filter_completed_card_drops": True,
        "max_games_to_idle": 2,
        "api_timeout": 5,
    }
    base.update(overrides)
    return Settings(**base)


def make_manager(settings=None, badge=None):
    settings = settings or make_settings()
    manager = GameManager(settings, StubDetector(), badge)
    manager.detailed_logger.log_api_results = Mock()
    manager.detailed_logger.log_filtering_process = Mock()
    return manager


def test_get_owned_games_uses_cache():
    manager = make_manager()
    manager._owned_games_cache = [10, 11]
    assert manager.get_owned_games("123") == [10, 11]


def test_get_owned_games_without_api_uses_config(monkeypatch):
    manager = make_manager(make_settings(steam_api_key=None, use_owned_games=True, game_app_ids=[9]))
    monkeypatch.setattr(
        manager,
        "_get_steam_utility_bridge",
        lambda: (_ for _ in ()).throw(SteamUtilityError("missing")),
    )
    assert manager.get_owned_games("123") == [9]


def test_get_owned_games_without_api_uses_steam_utility_when_available():
    manager = make_manager(make_settings(steam_api_key=None, use_owned_games=True))
    manager._steam_utility_bridge = StubSteamUtilityBridge(apps=[{"AppId": 77}, {"AppId": "88"}, {"AppId": 77}])

    assert manager.get_owned_games("123") == [77, 88]


def test_get_owned_games_steam_utility_invalid_payload_raises():
    manager = make_manager(make_settings(steam_api_key=None, use_owned_games=True))
    manager._steam_utility_bridge = StubSteamUtilityBridge(apps={"bad": True})

    with pytest.raises(GameLibraryError):
        manager._get_owned_games_via_steam_utility()


def test_get_owned_games_handles_errors_with_config_fallback(monkeypatch):
    manager = make_manager()
    monkeypatch.setattr(
        manager,
        "_get_owned_games_via_api",
        lambda steam_id: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert manager.get_owned_games("123") == [1, 2, 3]


def test_get_owned_games_via_api_success_and_errors():
    manager = make_manager()

    ok_response = Mock()
    ok_response.raise_for_status = Mock()
    ok_response.json.return_value = {"response": {"games": [{"appid": 10}, {"appid": 20}]}}

    with patch("steam_idle_bot.steam.games.requests.get", return_value=ok_response):
        assert manager._get_owned_games_via_api("123") == [10, 20]

    bad_response = Mock()
    bad_response.raise_for_status = Mock()
    bad_response.json.return_value = {"response": {}}
    with patch("steam_idle_bot.steam.games.requests.get", return_value=bad_response), pytest.raises(GameLibraryError):
        manager._get_owned_games_via_api("123")

    with (
        patch(
            "steam_idle_bot.steam.games.requests.get",
            side_effect=requests.exceptions.Timeout(),
        ),
        pytest.raises(SteamAPITimeoutError),
    ):
        manager._get_owned_games_via_api("123")

    with (
        patch(
            "steam_idle_bot.steam.games.requests.get",
            side_effect=requests.exceptions.RequestException("x"),
        ),
        pytest.raises(GameLibraryError),
    ):
        manager._get_owned_games_via_api("123")


def test_filter_completed_card_drops_paths():
    manager = make_manager()
    assert manager._filter_completed_card_drops([], "123") == (
        [],
        "skipped_no_candidate_games",
    )
    assert manager._filter_completed_card_drops([1], None) == (
        [1],
        "skipped_missing_steam_id",
    )


def test_filter_completed_card_drops_badge_timeout_uses_scraping():
    badge = StubBadge(exc=SteamAPITimeoutError("t"))
    manager = make_manager(badge=badge)
    manager.card_drop_checker = StubCardDropChecker(result=[2])
    manager.card_drop_checker.has_authenticated_session = True

    games, source = manager._filter_completed_card_drops([1, 2], "123")
    assert games == [2]
    assert source == "web_scraping"


def test_filter_completed_card_drops_full_fallback_include_all():
    badge = StubBadge(exc=BadgeServiceError("bad"))
    manager = make_manager(badge=badge)
    manager.card_drop_checker = StubCardDropChecker(exc=RuntimeError("scrape failed"))

    games, source = manager._filter_completed_card_drops([1, 2], "123")
    assert games == []
    assert source == "fallback_exclude_all"


def test_get_games_to_idle_final_fallbacks():
    manager = make_manager(make_settings(game_app_ids=[1, 2], use_owned_games=False))
    manager.trading_card_detector = StubDetector(allowed=[])
    manager.badge_service = None
    manager.card_drop_checker = StubCardDropChecker(result=[1, 2])

    result = manager.get_games_to_idle("123")
    assert result == [1, 2]

    manager2 = make_manager(make_settings(game_app_ids=[1], use_owned_games=False))
    manager2.trading_card_detector = StubDetector(allowed=[])
    manager2.badge_service = StubBadge(result=[])
    manager2.card_drop_checker = StubCardDropChecker(result=[])

    result2 = manager2.get_games_to_idle("123")
    assert result2 == []


def test_get_games_to_idle_with_owned_games_logs_branch(monkeypatch):
    settings = make_settings(use_owned_games=True, filter_trading_cards=False)
    manager = make_manager(settings)
    monkeypatch.setattr(manager, "get_owned_games", lambda steam_id: [7, 8])
    manager.card_drop_checker = StubCardDropChecker(result=[7, 8])

    result = manager.get_games_to_idle("123")
    assert result == [7, 8][: settings.max_games_to_idle]


def test_get_games_to_idle_empty_games_hits_lenient_block():
    settings = make_settings(use_owned_games=False, game_app_ids=[], filter_trading_cards=True)
    manager = make_manager(settings)
    manager.trading_card_detector = StubDetector(allowed=[])

    assert manager.get_games_to_idle("123") == []


def test_filter_completed_card_drops_logs_empty_scraping_result():
    manager = make_manager(badge=None)
    manager.card_drop_checker = StubCardDropChecker(result=[])
    manager.card_drop_checker.has_authenticated_session = True

    games, source = manager._filter_completed_card_drops([1], "123")
    assert games == []
    assert source == "web_scraping"


def test_set_web_session_marks_scraper_authenticated():
    manager = make_manager()
    scraper = StubCardDropChecker(result=[])
    manager.card_drop_checker = scraper

    manager.set_web_session(object())

    assert scraper.has_authenticated_session is True


def test_resolve_active_steam_id_uses_steam_utility_report():
    manager = make_manager()
    manager._steam_utility_bridge = StubSteamUtilityBridge(report={"ActiveSteamId": 76561198000000000})

    assert manager.resolve_active_steam_id() == "76561198000000000"


def test_resolve_active_steam_id_handles_bridge_errors():
    manager = make_manager()
    manager._steam_utility_bridge = StubSteamUtilityBridge(exc=SteamUtilityError("boom"))

    assert manager.resolve_active_steam_id() is None
