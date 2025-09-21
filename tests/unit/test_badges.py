"""Tests for badge service filtering of trading card drops."""

import pytest
import requests

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.badges import BadgeService
from steam_idle_bot.utils.exceptions import BadgeServiceError, SteamAPITimeoutError


class DummyResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class DummySession:
    def __init__(self, data=None, exc=None):
        self.data = data or {}
        self.exc = exc
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, params))
        if self.exc:
            raise self.exc
        return DummyResponse(self.data)


def make_settings(**overrides):
    base = {
        "username": "user",
        "password": "pass",
        "steam_api_key": "key",
        "game_app_ids": [220, 300],
        "filter_trading_cards": True,
        "filter_completed_card_drops": True,
        "use_owned_games": False,
        "max_games_to_idle": 2,
        "api_timeout": 10,
        "rate_limit_delay": 0.5,
        "enable_card_cache": False,
        "card_cache_ttl_days": 30,
        "max_checks": None,
        "skip_failures": False,
        "enable_encryption": False,
    }
    base.update(overrides)
    return Settings(**base)


def test_filter_games_with_remaining_cards_skips_completed():
    session = DummySession(
        data={
            "response": {
                "badges": [
                    {"appid": 300, "cards_remaining": 0},
                    {"appid": 220, "cards_remaining": 3},
                ]
            }
        }
    )
    service = BadgeService(make_settings(), session=session)

    result = service.filter_games_with_remaining_cards([300, 220, 111], "123")

    # 300 should be dropped, 220 kept, 111 kept because missing info
    assert result == [220, 111]
    assert session.calls  # ensure API was queried


def test_filter_games_with_remaining_cards_handles_missing_field():
    session = DummySession(data={"response": {"badges": [{"appid": 555}]}})
    service = BadgeService(make_settings(), session=session)

    result = service.filter_games_with_remaining_cards([555], "123")

    # Missing cards_remaining indicates drops are exhausted
    assert result == []


def test_fetch_cards_remaining_raises_on_timeout():
    session = DummySession(exc=requests.exceptions.Timeout())
    service = BadgeService(make_settings(), session=session)

    with pytest.raises(SteamAPITimeoutError):
        service.filter_games_with_remaining_cards([1], "123")


def test_fetch_cards_remaining_raises_on_network_error():
    session = DummySession(exc=requests.exceptions.RequestException("boom"))
    service = BadgeService(make_settings(), session=session)

    with pytest.raises(BadgeServiceError):
        service.filter_games_with_remaining_cards([1], "123")
