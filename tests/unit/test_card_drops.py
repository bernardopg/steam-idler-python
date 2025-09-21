"""Tests for the Steam card drop web scraper."""

from unittest.mock import Mock, patch

import pytest

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.card_drops import CardDropChecker


@pytest.fixture
def settings() -> Settings:
    """Provide minimal settings required for the checker."""
    return Settings(username="user", password="pass")


def _make_session(response_text: str) -> Mock:
    response = Mock()
    response.raise_for_status = Mock()
    response.text = response_text

    session = Mock()
    session.get.return_value = response
    return session


def _invoke_checker(settings: Settings, session: Mock, steam_id: str) -> bool:
    with patch("steam_idle_bot.steam.card_drops.CardDropChecker._build_session", return_value=session), patch(
        "steam_idle_bot.steam.card_drops.DetailedLogger.log_scraping_result"
    ):
        checker = CardDropChecker(settings)
        return checker.has_remaining_drops(123, steam_id)


def test_has_remaining_drops_uses_profiles_path_for_numeric_steam_id(settings: Settings) -> None:
    session = _make_session("pode dar mais cartas colecionáveis")

    result = _invoke_checker(settings, session, "76561198000000000")

    assert result is True
    called_url = session.get.call_args.args[0]
    assert "/profiles/76561198000000000/" in called_url
    assert called_url.endswith("/gamecards/123/")


def test_has_remaining_drops_uses_id_path_for_vanity_steam_id(settings: Settings) -> None:
    session = _make_session("pode dar mais cartas")

    result = _invoke_checker(settings, session, "mycustomid")

    assert result is True
    called_url = session.get.call_args.args[0]
    assert "/id/mycustomid/" in called_url
    assert called_url.endswith("/gamecards/123/")


def test_has_remaining_drops_handles_embedded_steam64_in_string(settings: Settings) -> None:
    session = _make_session("pode dar mais cartas")

    embedded = "SteamID(id=76561198000000000, type=0, universe=1, instance=1)"
    result = _invoke_checker(settings, session, embedded)

    assert result is True
    called_url = session.get.call_args.args[0]
    assert "/profiles/76561198000000000/" in called_url
    assert called_url.endswith("/gamecards/123/")
