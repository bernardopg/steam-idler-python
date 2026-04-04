"""Additional tests for CardDropChecker parsing and fallbacks."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.card_drops import CardDropChecker, CardDropCheckError
from steam_idle_bot.utils.exceptions import SteamAPITimeoutError


def make_settings() -> Settings:
    return Settings(username="user", password="pass")


class Resp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class Sess:
    def __init__(self, text="", exc=None):
        self.text = text
        self.exc = exc

    def get(self, *args, **kwargs):
        if self.exc:
            raise self.exc
        return Resp(self.text)


def make_checker(text="", exc=None):
    with patch(
        "steam_idle_bot.steam.card_drops.CardDropChecker._build_session",
        return_value=Sess(text, exc),
    ):
        checker = CardDropChecker(make_settings())
    checker.detailed_logger.log_scraping_result = Mock()
    checker.detailed_logger.log_api_results = Mock()
    return checker


@pytest.mark.parametrize(
    "steam_id,expected",
    [
        (
            "profiles/76561198000000000",
            "https://steamcommunity.com/profiles/76561198000000000/gamecards/10/",
        ),
        ("id/myname", "https://steamcommunity.com/id/myname/gamecards/10/"),
        (
            "https://steamcommunity.com/id/custom/",
            "https://steamcommunity.com/id/custom/gamecards/10/",
        ),
    ],
)
def test_build_gamecards_url_variants(steam_id, expected):
    assert CardDropChecker._build_gamecards_url(steam_id, 10) == expected


def test_build_gamecards_url_empty_errors():
    with pytest.raises(ValueError):
        CardDropChecker._build_gamecards_url("   ", 10)
    assert CardDropChecker._build_gamecards_url("profiles/", 10).endswith("/id/profiles/gamecards/10/")


@pytest.mark.parametrize(
    "html,expected",
    [
        ("não dará mais cartas", False),
        ("pode dar mais cartas", True),
        ("no card drops remaining", False),
        ("can drop more", True),
        ('<span class="progress_info_bold">não dará mais</span>', False),
        ('<span class="progress_info_bold">drops remaining</span>', True),
        ('<span class="progress_info_bold">3/5</span>', True),
        ('<span class="progress_info_bold">2</span>', True),
        ('<span class="progress_info_bold">unknown words</span>', True),
        ("trading cards available", True),
        ("completely unknown page", True),
        ("0 card drops remaining", False),
        ("2 card drops remaining", True),
    ],
)
def test_has_remaining_drops_patterns(html, expected):
    checker = make_checker(text=html)
    assert checker.has_remaining_drops(10, "123") is expected


def test_has_remaining_drops_timeout_and_network_errors():
    checker_timeout = make_checker(exc=requests.exceptions.Timeout())
    with pytest.raises(SteamAPITimeoutError):
        checker_timeout.has_remaining_drops(10, "123")

    checker_network = make_checker(exc=requests.exceptions.RequestException("boom"))
    with pytest.raises(CardDropCheckError):
        checker_network.has_remaining_drops(10, "123")


def test_has_remaining_drops_unexpected_error_wrapped(monkeypatch):
    checker = make_checker(text="pode dar mais")
    monkeypatch.setattr(
        checker,
        "_build_gamecards_url",
        lambda steam_id, app_id: (_ for _ in ()).throw(RuntimeError("bad")),
    )

    with pytest.raises(CardDropCheckError):
        checker.has_remaining_drops(10, "123")


def test_filter_games_with_drops_includes_on_errors():
    checker = make_checker(text="")
    checker.has_remaining_drops = Mock(side_effect=[True, False, RuntimeError("x")])

    result = checker.filter_games_with_drops([1, 2, 3], "123")

    assert result == [1, 3]
    checker.detailed_logger.log_api_results.assert_called_once()
