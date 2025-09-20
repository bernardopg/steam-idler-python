import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path for imports when running in CI
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_has_trading_cards_handles_network_error(monkeypatch):
    import idle_bot

    class FakeResp:
        def raise_for_status(self):
            raise Exception("boom")

    def fake_get(*args, **kwargs):
        raise Exception("network down")

    monkeypatch.setattr(idle_bot.requests, "get", fake_get)
    assert idle_bot.has_trading_cards(123) is False


def test_filter_games_respects_max(monkeypatch):
    import idle_bot

    monkeypatch.setattr(idle_bot, "FILTER_TRADING_CARDS", True)
    monkeypatch.setattr(idle_bot, "MAX_GAMES_TO_IDLE", 3)
    monkeypatch.setattr(idle_bot, "has_trading_cards", lambda app_id: True)

    result = idle_bot.filter_games_with_trading_cards([1, 2, 3, 4, 5])
    assert result == [1, 2, 3]


def test_ensure_credentials_configured_blocks_placeholders(monkeypatch):
    import idle_bot

    monkeypatch.setattr(idle_bot, "USERNAME", "your_steam_username")
    monkeypatch.setattr(idle_bot, "PASSWORD", "your_steam_password")

    with pytest.raises(SystemExit):
        idle_bot.ensure_credentials_configured()
