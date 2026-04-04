"""Tests for GameManager trading-card and badge filtering."""

from typing import cast
from unittest.mock import Mock

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.games import GameManager
from steam_idle_bot.steam.trading_cards import TradingCardDetector
from steam_idle_bot.utils.exceptions import BadgeServiceError


class StubTradingCardDetector:
    def __init__(self, allowed):
        self.allowed = set(allowed)
        self.calls = []

    def filter_games_with_trading_cards(
        self,
        game_ids,
        *,
        max_games,
        max_checks=None,
        skip_failures=False,
    ):
        self.calls.append((tuple(game_ids), max_games, max_checks, skip_failures))
        return [app for app in game_ids if app in self.allowed][:max_games]

    def clear_cache(self):
        self.calls.append("clear_cache")


class StubBadgeService:
    def __init__(self, keep=None, exc=None):
        self.keep = set(keep or [])
        self.exc = exc
        self.calls = []
        self.cleared = False

    def filter_games_with_remaining_cards(self, games, steam_id):
        self.calls.append((tuple(games), steam_id))
        if self.exc:
            raise self.exc
        return [app for app in games if app in self.keep]

    def clear_cache(self):
        self.cleared = True


def make_settings(**overrides):
    base = {
        "username": "user",
        "password": "pass",
        "steam_api_key": "key",
        "use_owned_games": False,
        "filter_trading_cards": True,
        "game_app_ids": [220, 300, 333],
        "max_games_to_idle": 2,
    }
    base.update(overrides)
    return Settings(**base)


def test_get_games_to_idle_filters_completed_drops():
    detector = StubTradingCardDetector({220, 300, 333})
    badge_service = StubBadgeService({220, 333})
    settings = make_settings()
    manager = GameManager(settings, cast(TradingCardDetector, detector), badge_service)

    games = manager.get_games_to_idle("123")

    assert games == [220, 333]
    assert badge_service.calls


def test_get_games_to_idle_does_not_scrape_after_badge_success():
    detector = StubTradingCardDetector({220, 300, 333})
    badge_service = StubBadgeService({220, 333})
    settings = make_settings()
    manager = GameManager(settings, cast(TradingCardDetector, detector), badge_service)

    class _FailOnScrape:
        def has_remaining_drops(self, app_id, steam_id):
            raise AssertionError(
                f"unexpected scraping call for app {app_id} and steam_id {steam_id}"
            )

    manager.card_drop_checker = _FailOnScrape()

    games = manager.get_games_to_idle("123")

    assert games == [220, 333]
    assert badge_service.calls


def test_get_games_to_idle_logs_drop_filter_source_badge_service():
    detector = StubTradingCardDetector({220, 300, 333})
    badge_service = StubBadgeService({220, 333})
    settings = make_settings()
    manager = GameManager(settings, cast(TradingCardDetector, detector), badge_service)
    manager.detailed_logger.log_filtering_process = Mock()

    games = manager.get_games_to_idle("123")

    assert games == [220, 333]
    assert (
        manager.detailed_logger.log_filtering_process.call_args.kwargs["drop_filter_source"]
        == "badge_service"
    )


def test_get_games_to_idle_logs_drop_filter_source_missing_steam_id():
    detector = StubTradingCardDetector({220, 300, 333})
    badge_service = StubBadgeService({220, 333})
    settings = make_settings()
    manager = GameManager(settings, cast(TradingCardDetector, detector), badge_service)
    manager.detailed_logger.log_filtering_process = Mock()

    games = manager.get_games_to_idle(None)

    assert games == [220, 300]
    assert (
        manager.detailed_logger.log_filtering_process.call_args.kwargs["drop_filter_source"]
        == "skipped_missing_steam_id"
    )


def test_get_games_to_idle_skips_badge_filter_without_api_key():
    detector = StubTradingCardDetector({220, 300, 333})
    badge_service = StubBadgeService(exc=AssertionError("should not call"))
    settings = make_settings(steam_api_key=None)
    manager = GameManager(settings, cast(TradingCardDetector, detector), badge_service)

    games = manager.get_games_to_idle("123")

    assert games == [220, 300]
    assert not badge_service.calls


def test_get_games_to_idle_returns_empty_when_all_completed():
    detector = StubTradingCardDetector({220, 300})
    badge_service = StubBadgeService(set())
    settings = make_settings(game_app_ids=[220, 300])
    manager = GameManager(settings, cast(TradingCardDetector, detector), badge_service)

    games = manager.get_games_to_idle("123")

    assert games == []


def test_exclude_app_ids_removes_games():
    detector = StubTradingCardDetector({220, 300, 333})
    badge_service = StubBadgeService({220, 333})
    settings = make_settings(exclude_app_ids=[333])
    manager = GameManager(settings, cast(TradingCardDetector, detector), badge_service)

    games = manager.get_games_to_idle("123")

    assert games == [220]


def test_clear_cache_propagates_to_services():
    detector = StubTradingCardDetector({220})
    badge_service = StubBadgeService({220})
    settings = make_settings()
    manager = GameManager(settings, cast(TradingCardDetector, detector), badge_service)

    manager.clear_cache()

    assert "clear_cache" in detector.calls
    assert badge_service.cleared


def test_badge_errors_fall_back_to_trading_card_list():
    detector = StubTradingCardDetector({220, 300})
    badge_service = StubBadgeService(exc=BadgeServiceError("nope"))
    settings = make_settings(game_app_ids=[220, 300])
    manager = GameManager(settings, cast(TradingCardDetector, detector), badge_service)

    games = manager.get_games_to_idle("123")

    assert games == [220, 300]
    assert badge_service.calls
