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


# ---------------------------------------------------------------------------
# Coverage push: owned-games API source, steam-utility payload edges, filters
# ---------------------------------------------------------------------------


class StubBadgeCatalog:
    """Badge service exposing the catalog API used by get_games_to_idle()."""

    def __init__(self, catalog=None, exc=None):
        self.catalog = set(catalog or [])
        self.exc = exc
        self.clear_cache_calls = 0

    def get_trading_card_badge_game_ids(self, steam_id):
        if self.exc:
            raise self.exc
        return set(self.catalog)

    def clear_cache(self):
        self.clear_cache_calls += 1


def test_get_owned_games_via_api_source_and_names(monkeypatch):
    """The happy API path through get_owned_games(): result is cached, source
    is 'api', and game names are captured into the manager's name map."""
    manager = make_manager()
    assert manager._owned_games_cache is None

    ok_response = Mock()
    ok_response.raise_for_status = Mock()
    ok_response.json.return_value = {
        "response": {
            "games": [
                {"appid": 10, "name": "Dota 2"},
                {"appid": 20},  # no name -> not captured
            ]
        }
    }

    with patch("steam_idle_bot.steam.games.requests.get", return_value=ok_response):
        assert manager.get_owned_games("123") == [10, 20]

    assert manager._owned_games_cache == [10, 20]
    assert manager.game_names == {10: "Dota 2"}
    assert "name" not in str(manager.game_names.get(20, ""))


def test_get_owned_games_via_steam_utility_payload_edges():
    """Malformed steam-utility payload rows are skipped; an entirely empty
    payload raises GameLibraryError."""
    manager = make_manager(make_settings(steam_api_key=None, use_owned_games=True))
    manager._steam_utility_bridge = StubSteamUtilityBridge(
        apps=[
            "not-a-dict",  # 137: non-dict row
            {"SomethingElse": 1},  # 141: AppId missing
            {"AppId": "not-a-number"},  # 144-145: int() ValueError
            {"AppId": 77},
        ]
    )

    assert manager.get_owned_games("123") == [77]

    empty_manager = make_manager(make_settings(steam_api_key=None, use_owned_games=True))
    empty_manager._steam_utility_bridge = StubSteamUtilityBridge(apps=[{"AppId": "junk"}])

    # All rows filtered out -> GameLibraryError (get_owned_games would swallow
    # it into the config fallback, so assert on the internal call directly).
    with pytest.raises(GameLibraryError, match="did not return any installed"):
        empty_manager._get_owned_games_via_steam_utility()


def test_get_games_to_idle_badge_catalog_error_falls_back_to_store_api():
    """A BadgeServiceError from the badge catalog falls back to the store API
    detector for the trading-card filter (lines 226-228)."""
    settings = make_settings(game_app_ids=[1, 2], use_owned_games=False)
    manager = make_manager(settings)
    manager.trading_card_detector = StubDetector(allowed=[1])
    manager.badge_service = StubBadgeCatalog(exc=BadgeServiceError("catalog down"))
    manager.card_drop_checker = StubCardDropChecker(result=[1])
    manager.settings.filter_completed_card_drops = False

    assert manager.get_games_to_idle("123") == [1]


def test_get_games_to_idle_badge_catalog_unknown_games_confirmed_via_store():
    """Games omitted by the badge catalog are confirmed through the store API
    detector; the union of both sources is returned in original order."""
    settings = make_settings(game_app_ids=[1, 2, 3], use_owned_games=False)
    manager = make_manager(settings)
    manager.trading_card_detector = StubDetector(allowed=[3])  # only unknown game 3 has cards
    manager.badge_service = StubBadgeCatalog(catalog=[1])  # catalog knows game 1 only
    manager.card_drop_checker = StubCardDropChecker(result=[1, 3])
    manager.settings.filter_completed_card_drops = False

    assert manager.get_games_to_idle("123") == [1, 3]


def test_get_games_to_idle_exclusions_that_match_nothing_are_silent():
    """exclude_app_ids / session excludes that remove zero games take the
    removed==0 branches (264->267, 271->275) without logging."""
    settings = make_settings(game_app_ids=[1], use_owned_games=False, exclude_app_ids=[999])
    manager = make_manager(settings)
    manager.trading_card_detector = StubDetector(allowed=[])
    manager.badge_service = None
    manager.card_drop_checker = StubCardDropChecker(result=[1])
    manager.settings.filter_completed_card_drops = False

    assert manager.get_games_to_idle("123", session_exclude_app_ids={888}) == [1]


def test_get_games_to_idle_excludes_configured_and_drained_games():
    settings = make_settings(game_app_ids=[1, 2, 3], use_owned_games=False, exclude_app_ids=[2])
    manager = make_manager(settings)
    manager.trading_card_detector = StubDetector(allowed=[])
    manager.badge_service = None
    manager.card_drop_checker = StubCardDropChecker(result=[1, 2, 3])
    manager.settings.filter_completed_card_drops = False

    # Game 2 excluded via config; game 3 excluded as session-drained.
    assert manager.get_games_to_idle("123", session_exclude_app_ids={3}) == [1]


def test_clear_cache_branches():
    """clear_cache tolerates a checker without clear_cache and no badge service."""
    manager = make_manager()
    detector_clears = []
    manager.trading_card_detector = type("Det", (), {"clear_cache": staticmethod(lambda: detector_clears.append(1))})()
    manager.card_drop_checker = object()  # no clear_cache attr
    manager.badge_service = None
    manager._owned_games_cache = [1]

    manager.clear_cache()

    assert manager._owned_games_cache is None
    assert detector_clears == [1]

    badge = StubBadgeCatalog()
    manager.badge_service = badge
    manager.clear_cache()
    assert badge.clear_cache_calls == 1


def test_get_drop_counts_defaults_to_empty_without_attribute():
    manager = make_manager()
    manager.card_drop_checker = object()  # no drop_counts attr

    assert manager.get_drop_counts() == {}


def test_fetch_drop_counts_guards_and_stop_paths():
    manager = make_manager()
    manager.card_drop_checker = StubCardDropChecker(result=[])

    # No steam id -> {} without touching the scraper.
    assert manager.fetch_drop_counts([1], None) == {}
    # No app ids -> {} without touching the scraper.
    assert manager.fetch_drop_counts([], "123") == {}

    calls: list[int] = []

    class RecordingChecker(StubCardDropChecker):
        def has_remaining_drops(self, app_id, steam_id):
            calls.append(app_id)
            return True

    checker = RecordingChecker(result=[])
    checker.drop_counts = {5: 2}
    manager.card_drop_checker = checker

    # should_stop fires before the first app -> nothing scraped, counts returned.
    result = manager.fetch_drop_counts([5, 6], "123", should_stop=lambda: True)
    assert calls == []
    assert result == {5: 2}

    # Scraper exceptions are swallowed per game; remaining games still processed.
    class FlakyChecker(StubCardDropChecker):
        def __init__(self):
            super().__init__(result=[])
            self.drop_counts = {7: 1}

        def has_remaining_drops(self, app_id, steam_id):
            calls.append(app_id)
            if app_id == 5:
                raise RuntimeError("scrape failed")
            return True

    flaky = FlakyChecker()
    manager.card_drop_checker = flaky
    assert manager.fetch_drop_counts([5, 7], "123") == {7: 1}
    assert calls == [5, 7]


def test_verify_web_session_branches():
    manager = make_manager()

    # No steam id -> False without probing.
    assert manager.verify_web_session(None) is False

    # Checker without _ensure_session_verified -> False.
    manager.card_drop_checker = object()
    assert manager.verify_web_session("123") is False

    class VerifiedChecker:
        has_authenticated_session = False
        probes: list[tuple[str, bool]] = []

        def _ensure_session_verified(self, steam_id, *, quiet=False):
            type(self).probes.append((steam_id, quiet))
            return None

    checker = VerifiedChecker()
    manager.card_drop_checker = checker
    assert manager.verify_web_session("123") is False  # authenticated flag False
    assert checker.probes == [("123", False)]

    checker.has_authenticated_session = True
    assert manager.verify_web_session("123", quiet=True) is True
    assert checker.probes[-1] == ("123", True)


def test_resolve_active_steam_id_without_steam_utility(monkeypatch):
    manager = make_manager()
    monkeypatch.setattr(
        manager,
        "_get_steam_utility_bridge",
        lambda: (_ for _ in ()).throw(SteamUtilityError("unavailable")),
    )
    assert manager.resolve_active_steam_id() is None


def test_resolve_active_steam_id_report_without_active_id():
    manager = make_manager()
    manager._steam_utility_bridge = StubSteamUtilityBridge(report={"something": "else"})

    assert manager.resolve_active_steam_id() is None


def test_get_steam_utility_bridge_is_lazy_and_cached():
    """The real bridge is constructed once, on first use, and reused after."""
    settings = make_settings(steam_api_key=None)
    manager = GameManager(settings, StubDetector(), None)
    assert manager._steam_utility_bridge is None

    bridge = manager._get_steam_utility_bridge()
    assert manager._steam_utility_bridge is bridge
    assert manager._get_steam_utility_bridge() is bridge


def test_filter_completed_card_drops_legacy_badge_api():
    """A badge service exposing only the legacy filter method (no partition)
    exercises the else branch at 395-396."""
    badge = type("LegacyBadge", (), {"filter_games_with_remaining_cards": staticmethod(lambda games, steam_id: [2])})()
    manager = make_manager(badge=badge)
    manager.card_drop_checker = StubCardDropChecker(result=[])

    games, source = manager._filter_completed_card_drops([1, 2], "123")
    assert games == [2]
    assert source == "badge_service"


def test_filter_completed_card_drops_unknown_via_scraping_empty_combined():
    """Badge + scraping agreeing that nothing has drops hits the empty-combined
    log line (426) and still returns the combined (empty) list."""
    badge = type(
        "PartitionBadge",
        (),
        {"partition_games_by_remaining_cards": staticmethod(lambda games, steam_id: ([], [1, 2]))},
    )()
    manager = make_manager(badge=badge)
    manager.card_drop_checker = StubCardDropChecker(result=[])
    manager.card_drop_checker.has_authenticated_session = True

    games, source = manager._filter_completed_card_drops([1, 2], "123")
    assert games == []
    assert source == "badge_service+web_scraping"


def test_filter_completed_card_drops_unknown_excluded_without_session():
    """Unknown-status games are excluded (with a warning) when no authenticated
    web session is available."""
    badge = type(
        "PartitionBadge",
        (),
        {"partition_games_by_remaining_cards": staticmethod(lambda games, steam_id: ([1], [2]))},
    )()
    manager = make_manager(badge=badge)
    manager.card_drop_checker = StubCardDropChecker(result=[])
    manager.card_drop_checker.has_authenticated_session = False

    games, source = manager._filter_completed_card_drops([1, 2], "123")
    assert games == [1]
    assert source == "badge_service+unknown_excluded"


def test_filter_completed_card_drops_unknown_via_scraping_combined():
    """Badge-confirmed + scraper-confirmed games are combined in input order."""
    badge = type(
        "PartitionBadge",
        (),
        {"partition_games_by_remaining_cards": staticmethod(lambda games, steam_id: ([1], [3]))},
    )()
    manager = make_manager(badge=badge)
    manager.card_drop_checker = StubCardDropChecker(result=[3])
    manager.card_drop_checker.has_authenticated_session = True

    games, source = manager._filter_completed_card_drops([1, 2, 3], "123")
    assert games == [1, 3]
    assert source == "badge_service+web_scraping"


def test_filter_completed_card_drops_all_badge_drained_logs(caplog):
    badge = type(
        "PartitionBadge",
        (),
        {"partition_games_by_remaining_cards": staticmethod(lambda games, steam_id: ([], []))},
    )()
    manager = make_manager(badge=badge)
    manager.card_drop_checker = StubCardDropChecker(result=[])

    games, source = manager._filter_completed_card_drops([1], "123")
    assert games == []
    assert source == "badge_service"


def test_set_web_session_without_set_session_method_is_noop():
    manager = make_manager()
    manager.card_drop_checker = object()  # no set_session attr

    manager.set_web_session(object())  # must not raise
