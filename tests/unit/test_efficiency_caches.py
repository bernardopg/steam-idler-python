"""Tests for the efficiency caches: badge session cache, has-drops short-TTL
cache, and quiet-mode logging demotion."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.badges import BadgeService
from steam_idle_bot.steam.card_drops import CardDropChecker
from steam_idle_bot.steam.games import GameManager

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "username": "user",
        "password": "pass",
        "steam_api_key": "key",
        "drop_cache_path": str(tmp_path / "no_drop.json"),
    }
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# A: BadgeService session cache
# ---------------------------------------------------------------------------


class DummyResponse:
    def __init__(self, data: Any):
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._data


class DummyBadgeSession:
    """Counts HTTP calls; returns the same badge payload every time."""

    def __init__(self, data: Any):
        self.data = data
        self.calls = 0

    def get(self, *args: Any, **kwargs: Any) -> DummyResponse:
        self.calls += 1
        return DummyResponse(self.data)


def _badge_payload() -> dict[str, Any]:
    return {
        "response": {
            "badges": [
                {"appid": 100, "border_color": 0, "cards_remaining": 3},
                {"appid": 200, "border_color": 0, "cards_remaining": 0},
            ]
        }
    }


def test_badge_catalog_reuses_cache_within_ttl(tmp_path: Path) -> None:
    """Two catalog calls in the same session must issue only one HTTP request."""
    settings = make_settings(tmp_path)
    sess = DummyBadgeSession(_badge_payload())
    service = BadgeService(settings, session=sess)

    service.get_trading_card_badge_game_ids("123")
    service.get_trading_card_badge_game_ids("123")

    assert sess.calls == 1


def test_badge_cache_survives_partition_then_catalog(tmp_path: Path) -> None:
    """partition and catalog share the same cached badge fetch."""
    settings = make_settings(tmp_path)
    sess = DummyBadgeSession(_badge_payload())
    service = BadgeService(settings, session=sess)

    service.partition_games_by_remaining_cards([100, 200], "123")
    service.get_trading_card_badge_game_ids("123")

    assert sess.calls == 1


def test_get_cards_remaining_bypasses_cache(tmp_path: Path) -> None:
    """get_cards_remaining is for authoritative snapshots and must always fetch."""
    settings = make_settings(tmp_path)
    sess = DummyBadgeSession(_badge_payload())
    service = BadgeService(settings, session=sess)

    service.get_trading_card_badge_game_ids("123")
    assert sess.calls == 1

    cards = service.get_cards_remaining("123")
    assert cards == {100: 3, 200: 0}
    assert sess.calls == 2  # bypassed the cache


def test_clear_cache_forces_refetch(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    sess = DummyBadgeSession(_badge_payload())
    service = BadgeService(settings, session=sess)

    service.get_trading_card_badge_game_ids("123")
    service.clear_cache()
    service.get_trading_card_badge_game_ids("123")

    assert sess.calls == 2


def test_badge_cache_expires(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    sess = DummyBadgeSession(_badge_payload())
    service = BadgeService(settings, session=sess)
    service._badges_cache_ttl = 0.0  # expire instantly

    service.get_trading_card_badge_game_ids("123")
    service.get_trading_card_badge_game_ids("123")

    assert sess.calls == 2


# ---------------------------------------------------------------------------
# B: CardDropChecker has-drops short-TTL cache
# ---------------------------------------------------------------------------


class DropResp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


class DropSess:
    def __init__(self, text: str = ""):
        self.text = text
        self.calls = 0

    def get(self, *args: Any, **kwargs: Any) -> DropResp:
        self.calls += 1
        return DropResp(self.text)


def _make_checker(settings: Settings, session: DropSess, *, authenticated: bool = False) -> CardDropChecker:
    with patch(
        "steam_idle_bot.steam.card_drops.CardDropChecker._build_session",
        return_value=session,
    ):
        checker = CardDropChecker(settings, authenticated_session=authenticated)
    checker.detailed_logger.log_scraping_result = Mock()
    checker.detailed_logger.log_api_results = Mock()
    if authenticated:
        checker._auth_verified = True
    return checker


def test_has_drops_verdict_cached_within_ttl(tmp_path: Path) -> None:
    """A second filter call in the same session must not re-scrape a positive game."""
    settings = make_settings(tmp_path)
    steam_id = "76561198000000000"

    sess = DropSess("2 card drops remaining")
    checker = _make_checker(settings, sess, authenticated=True)

    result1 = checker.filter_games_with_drops([10], steam_id)
    assert result1 == [10]
    assert sess.calls == 1

    # Same instance, within TTL — the positive verdict is reused, no new scrape.
    result2 = checker.filter_games_with_drops([10], steam_id)
    assert result2 == [10]
    assert sess.calls == 1


def test_has_drops_cache_expires_after_ttl(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    steam_id = "76561198000000000"

    sess = DropSess("2 card drops remaining")
    checker = _make_checker(settings, sess, authenticated=True)
    checker._has_drops_cache_ttl = 0.0  # expire instantly

    checker.filter_games_with_drops([10], steam_id)
    checker.filter_games_with_drops([10], steam_id)

    # TTL of 0 means every call must re-scrape.
    assert sess.calls == 2


def test_has_drops_cache_evicts_expired_entries(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    steam_id = "76561198000000000"

    checker = _make_checker(settings, DropSess(), authenticated=True)
    checker._remember_has_drops(steam_id, 10)

    # Expire it.
    key = checker._normalize_steam_id(steam_id)
    checker._has_drops_cache[key][10] = time.time() - 999

    assert checker._cached_has_drops_ids(steam_id) == set()
    # The expired entry should have been evicted.
    assert 10 not in checker._has_drops_cache[key]


def test_clear_cache_drops_has_drops_cache(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    steam_id = "76561198000000000"

    checker = _make_checker(settings, DropSess("2 card drops remaining"), authenticated=True)
    checker._remember_has_drops(steam_id, 10)
    assert checker._cached_has_drops_ids(steam_id) == {10}

    checker.clear_cache()
    assert checker._cached_has_drops_ids(steam_id) == set()


def test_mixed_no_drop_and_has_drops_in_filter(tmp_path: Path) -> None:
    """No-drop games are skipped permanently; has-drops games are cached briefly."""
    settings = make_settings(tmp_path)
    steam_id = "76561198000000000"

    # Game 10 has drops, game 20 has no drops (confident negative).
    texts = iter(["2 card drops remaining", "no card drops remaining"])

    class AlternatingSess:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, *args: Any, **kwargs: Any) -> DropResp:
            self.calls += 1
            return DropResp(next(texts))

    checker = _make_checker(settings, AlternatingSess(), authenticated=True)  # type: ignore[arg-type]
    checker._has_drops_cache_ttl = 0.0

    result = checker.filter_games_with_drops([10, 20], steam_id)
    assert result == [10]


# ---------------------------------------------------------------------------
# D: quiet-mode logging in GameManager
# ---------------------------------------------------------------------------


def _make_game_manager(settings: Settings) -> GameManager:
    """Build a GameManager whose owned-games call is pre-cached to avoid network."""
    detector = Mock(spec=["filter_games_with_trading_cards", "clear_cache"])
    detector.filter_games_with_trading_cards.return_value = []
    gm = GameManager(settings, detector, badge_service=None)  # type: ignore[arg-type]
    gm._owned_games_cache = settings.game_app_ids  # type: ignore[attr-defined]
    gm.detailed_logger.log_api_results = Mock()
    gm.detailed_logger.log_filtering_process = Mock()
    return gm


def test_get_games_to_idle_quiet_demotes_info_to_debug(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    settings = make_settings(tmp_path, game_app_ids=[570], filter_trading_cards=False)
    gm = _make_game_manager(settings)

    with caplog.at_level(logging.DEBUG, logger="steam_idle_bot.steam.games"):
        gm.get_games_to_idle(quiet=True)

    info_msgs = [r for r in caplog.records if r.levelno == logging.INFO]
    debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    # In quiet mode the "Found N owned games" progress line must be DEBUG, not INFO.
    assert not any("owned games" in r.getMessage() for r in info_msgs)
    assert any("owned games" in r.getMessage() for r in debug_msgs)


def test_get_games_to_idle_default_logs_at_info(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    settings = make_settings(tmp_path, game_app_ids=[570], filter_trading_cards=False)
    gm = _make_game_manager(settings)

    with caplog.at_level(logging.INFO, logger="steam_idle_bot.steam.games"):
        gm.get_games_to_idle()

    info_msgs = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("owned games" in r.getMessage() for r in info_msgs)
