"""Additional coverage for badge service edge cases."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.badges import BadgeService
from steam_idle_bot.utils.exceptions import BadgeServiceError, SteamAPITimeoutError


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "username": "user",
        "password": "pass",
        "steam_api_key": "key",
        "api_timeout": 5,
    }
    base.update(overrides)
    return Settings(**base)


class DummyResponse:
    def __init__(self, data=None, json_exc=None):
        self._data = data
        self._json_exc = json_exc

    def raise_for_status(self):
        return None

    def json(self):
        if self._json_exc:
            raise self._json_exc
        return self._data


class DummySession:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc

    def get(self, *args, **kwargs):
        if self.exc:
            raise self.exc
        return self.response


def test_build_session_configured():
    service = BadgeService(make_settings())
    assert service._http is not None


def test_fetch_requires_api_key():
    service = BadgeService(make_settings(steam_api_key=None), session=DummySession())
    with pytest.raises(BadgeServiceError):
        service._fetch_cards_remaining("123")


def test_fetch_timeout_and_network_errors():
    timeout_service = BadgeService(
        make_settings(),
        session=DummySession(exc=requests.exceptions.Timeout()),
    )
    with pytest.raises(SteamAPITimeoutError):
        timeout_service._fetch_cards_remaining("123")

    net_service = BadgeService(
        make_settings(),
        session=DummySession(exc=requests.exceptions.RequestException("boom")),
    )
    with pytest.raises(BadgeServiceError):
        net_service._fetch_cards_remaining("123")


def test_fetch_invalid_json_response():
    service = BadgeService(
        make_settings(),
        session=DummySession(response=DummyResponse(json_exc=ValueError("bad json"))),
    )
    with pytest.raises(BadgeServiceError, match="Invalid JSON"):
        service._fetch_cards_remaining("123")


def test_fetch_cards_remaining_parsing_rules():
    payload = {
        "response": {
            "badges": [
                {"appid": None, "cards_remaining": 2},
                {"appid": "bad", "cards_remaining": 2},
                {"appid": 100, "border_color": 1, "cards_remaining": 4},
                {"appid": 200, "border_color": 0, "cards_remaining": "x"},
                {"appid": 300, "border_color": 0, "cards_remaining": 0},
                {"appid": 400, "border_color": 0, "cards_remaining": 3},
            ]
        }
    }
    service = BadgeService(
        make_settings(),
        session=DummySession(response=DummyResponse(data=payload)),
    )

    cards = service._fetch_cards_remaining("123")

    assert cards == {300: 0, 400: 3}


def test_get_trading_card_badge_game_ids_parsing_rules():
    payload = {
        "response": {
            "badges": [
                {"appid": None, "border_color": 0},
                {"appid": "bad", "border_color": 0},
                {"appid": 100, "border_color": 1, "cards_remaining": 4},
                {"appid": 300, "border_color": 0, "cards_remaining": 0},
                {"appid": 400, "border_color": 0},
            ]
        }
    }
    service = BadgeService(
        make_settings(),
        session=DummySession(response=DummyResponse(data=payload)),
    )

    app_ids = service.get_trading_card_badge_game_ids("123")

    assert app_ids == {300, 400}


def test_filter_logs_skipped_games(caplog):
    service = BadgeService(
        make_settings(),
        session=DummySession(response=DummyResponse(data={"response": {"badges": []}})),
    )

    result = service.filter_games_with_remaining_cards([1, 2], "123")
    assert result == []

    service2 = BadgeService(
        make_settings(),
        session=DummySession(response=DummyResponse(data={"response": {"badges": [{"appid": 1, "border_color": 0, "cards_remaining": 0}]}})),
    )
    assert service2.filter_games_with_remaining_cards([1], "123") == []
