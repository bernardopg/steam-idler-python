"""Tests for the CardDropChecker persistent no-drop cache."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.card_drops import CardDropChecker


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = {
        "username": "user",
        "password": "pass",
        "drop_cache_path": str(tmp_path / "no_drop.json"),
    }
    base.update(overrides)
    return Settings(**base)


class Resp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class Sess:
    def __init__(self, text: str = ""):
        self.text = text
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return Resp(self.text)


def make_checker(settings: Settings, session: Sess, *, authenticated: bool = False) -> CardDropChecker:
    with patch(
        "steam_idle_bot.steam.card_drops.CardDropChecker._build_session",
        return_value=session,
    ):
        checker = CardDropChecker(settings, authenticated_session=authenticated)
    checker.detailed_logger.log_scraping_result = Mock()
    checker.detailed_logger.log_api_results = Mock()
    if authenticated:
        checker._auth_verified = True  # bypass live session probe in unit tests
    return checker


def test_confirmed_no_drop_is_cached_and_skipped_next_run(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    steam_id = "76561198000000000"

    # Explicit "no drops" verdict (confident negative) -> should be persisted.
    sess1 = Sess("no card drops remaining")
    checker1 = make_checker(settings, sess1)
    assert checker1.filter_games_with_drops([10], steam_id) == []
    assert sess1.calls == 1
    assert Path(settings.drop_cache_path).exists()

    # Fresh checker loads the cache and skips the network call entirely.
    sess2 = Sess("no card drops remaining")
    checker2 = make_checker(settings, sess2)
    assert checker2.filter_games_with_drops([10], steam_id) == []
    assert sess2.calls == 0


def test_games_with_drops_are_not_cached(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    steam_id = "76561198000000000"

    sess = Sess("2 card drops remaining")
    checker = make_checker(settings, sess)
    assert checker.filter_games_with_drops([10], steam_id) == [10]

    # A positive verdict must always be re-checked (drops decrease while idling).
    sess2 = Sess("2 card drops remaining")
    checker2 = make_checker(settings, sess2)
    assert checker2.filter_games_with_drops([10], steam_id) == [10]
    assert sess2.calls == 1


def test_weak_negative_rechecked_when_authenticated(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    steam_id = "76561198000000000"

    # Unauthenticated guess ("sign in" page) is a weak negative.
    sess = Sess("please sign in to continue")
    checker = make_checker(settings, sess, authenticated=False)
    assert checker.filter_games_with_drops([10], steam_id) == []

    # An authenticated run must NOT trust the weak negative and re-checks it.
    sess2 = Sess("pode dar mais cartas")
    checker2 = make_checker(settings, sess2, authenticated=True)
    assert checker2.filter_games_with_drops([10], steam_id) == [10]
    assert sess2.calls == 1


def test_no_drop_cache_respects_ttl(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, drop_cache_ttl_days=1)
    steam_id = "76561198000000000"

    sess = Sess("no card drops remaining")
    checker = make_checker(settings, sess)
    checker.filter_games_with_drops([10], steam_id)

    # Age the entry past the TTL.
    checker2 = make_checker(settings, Sess("no card drops remaining"))
    key = checker2._normalize_steam_id(steam_id)
    checker2._no_drop_cache[key][10]["ts"] = time.time() - 2 * 86400
    assert checker2._cached_no_drop_ids(steam_id) == set()


class RouteSess:
    """Session that returns different bodies for the /badges/ probe vs gamecards."""

    def __init__(self, badges_text: str, gamecards_text: str):
        self.badges_text = badges_text
        self.gamecards_text = gamecards_text

    def get(self, url, *args, **kwargs):
        return Resp(self.badges_text if url.rstrip("/").endswith("/badges") else self.gamecards_text)


def test_unauthenticated_session_is_downgraded_and_excludes(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    steam_id = "76561198000000000"

    # Probe returns a logged-out page (no g_steamID/account_pulldown); the gamecards
    # page is an ambiguous badge page that would be INCLUDED if we trusted auth.
    sess = RouteSess(
        badges_text='<html>g_steamID = false;</html>',
        gamecards_text='<div class="badge_gamecard_page"><div class="badge_title_stats_drops"></div></div>',
    )
    with patch(
        "steam_idle_bot.steam.card_drops.CardDropChecker._build_session",
        return_value=sess,
    ):
        checker = CardDropChecker(settings, authenticated_session=True)
    checker.detailed_logger.log_scraping_result = Mock()
    checker.detailed_logger.log_api_results = Mock()

    # Ambiguous page + downgraded (unauthenticated) session -> excluded, not idled.
    assert checker.filter_games_with_drops([10], steam_id) == []
    assert checker.has_authenticated_session is False


def test_authenticated_session_verified_and_includes_ambiguous(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    steam_id = "76561198000000000"

    sess = RouteSess(
        badges_text='<html>g_steamID = "76561198000000000";</html>',
        gamecards_text='<div class="badge_gamecard_page"><div class="badge_title_stats_drops"></div></div>',
    )
    with patch(
        "steam_idle_bot.steam.card_drops.CardDropChecker._build_session",
        return_value=sess,
    ):
        checker = CardDropChecker(settings, authenticated_session=True)
    checker.detailed_logger.log_scraping_result = Mock()
    checker.detailed_logger.log_api_results = Mock()

    # Verified auth -> ambiguous badge page is included.
    assert checker.filter_games_with_drops([10], steam_id) == [10]
    assert checker.has_authenticated_session is True


@pytest.mark.parametrize(
    "html,expected",
    [
        ("Jogo pode dar mais 3 cartas", 3),
        ("Jogo pode dar mais 1 carta", 1),
        ("Jogo não dará mais cartas", 0),
        ("2 card drops remaining", 2),
        ("0 card drops remaining", 0),
        ("can drop 4 more", 4),
        ("no card drops remaining", 0),
        ("totally unrelated text", None),
    ],
)
def test_extract_drops_remaining(html, expected) -> None:
    assert CardDropChecker._extract_drops_remaining(html) == expected


def test_drop_counts_populated_during_scrape(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    checker = make_checker(settings, Sess("Jogo pode dar mais 3 cartas"), authenticated=True)
    checker.filter_games_with_drops([391540], "76561198000000000")
    assert checker.drop_counts.get(391540) == 3


def test_cache_disabled_does_not_persist(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, enable_card_cache=False)
    steam_id = "76561198000000000"

    sess = Sess("no card drops remaining")
    checker = make_checker(settings, sess)
    checker.filter_games_with_drops([10], steam_id)
    assert not Path(settings.drop_cache_path).exists()
