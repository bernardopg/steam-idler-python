"""Additional branch coverage for TradingCardDetector filtering and cache errors."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from steam_idle_bot.steam.trading_cards import TradingCardDetector
from steam_idle_bot.utils.exceptions import (
    SteamAPITimeoutError,
    TradingCardDetectionError,
)


def test_filter_handles_interrupt_and_errors(monkeypatch):
    detector = TradingCardDetector(rate_limit_delay=0, cache_enabled=False)

    seq = [
        True,
        TradingCardDetectionError("bad"),
        SteamAPITimeoutError("slow"),
        RuntimeError("other"),
        KeyboardInterrupt(),
    ]

    def fake_has_cards(app_id):
        value = seq.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    detector.has_trading_cards = fake_has_cards
    monkeypatch.setattr("time.sleep", lambda _: None)

    out = detector.filter_games_with_trading_cards([1, 2, 3, 4, 5], max_games=10)
    assert out == [1]


def test_filter_respects_max_checks(monkeypatch):
    detector = TradingCardDetector(rate_limit_delay=0, cache_enabled=False)
    detector.has_trading_cards = lambda app_id: True
    monkeypatch.setattr("time.sleep", lambda _: None)

    out = detector.filter_games_with_trading_cards([1, 2, 3], max_games=10, max_checks=2)
    assert out == [1, 2]


def test_load_cache_tolerates_invalid_file(tmp_path):
    cache_file = tmp_path / "bad.json"
    cache_file.write_text("{", encoding="utf-8")

    detector = TradingCardDetector(cache_enabled=True, cache_path=str(cache_file))
    assert detector._cache == {}


def test_load_cache_skips_invalid_entries(tmp_path):
    cache_file = tmp_path / "cards.json"
    cache_file.write_text(
        '{"1": {"has_cards": true, "ts": 9999999999}, "x": {"has_cards": true}}',
        encoding="utf-8",
    )

    detector = TradingCardDetector(cache_enabled=True, cache_path=str(cache_file))
    assert detector._cache.get(1) is True
    assert len(detector._cache) == 1


def test_save_cache_tolerates_write_errors(monkeypatch):
    detector = TradingCardDetector(cache_enabled=True, cache_path="/invalid/path/cards.json")
    detector._cache_data = {1: (True, 1.0)}

    monkeypatch.setattr("os.makedirs", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("nope")))
    detector._save_cache()


def test_has_trading_cards_request_exception(monkeypatch):
    detector = TradingCardDetector(cache_enabled=False)
    detector._http = Mock(get=Mock(side_effect=requests.exceptions.RequestException("net")))

    with pytest.raises(TradingCardDetectionError):
        detector.has_trading_cards(10)
