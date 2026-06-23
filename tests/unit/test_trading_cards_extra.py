"""Additional branch coverage for TradingCardDetector filtering and cache errors."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from steam_idle_bot.steam.trading_cards import TradingCardDetector
from steam_idle_bot.utils.exceptions import (
    RateLimitError,
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


def test_has_trading_cards_retry_error_is_rate_limit():
    detector = TradingCardDetector(cache_enabled=False)
    detector._http = Mock(get=Mock(side_effect=requests.exceptions.RetryError("429")))

    with pytest.raises(RateLimitError):
        detector.has_trading_cards(10)


def test_has_trading_cards_http_429_is_rate_limit():
    response = Mock(status_code=429)
    err = requests.exceptions.HTTPError("too many", response=response)
    detector = TradingCardDetector(cache_enabled=False)
    detector._http = Mock(get=Mock(side_effect=err))

    with pytest.raises(RateLimitError):
        detector.has_trading_cards(10)


def test_has_trading_cards_http_500_is_detection_error():
    response = Mock(status_code=500)
    err = requests.exceptions.HTTPError("boom", response=response)
    detector = TradingCardDetector(cache_enabled=False)
    detector._http = Mock(get=Mock(side_effect=err))

    with pytest.raises(TradingCardDetectionError):
        detector.has_trading_cards(10)


def test_filter_backs_off_on_rate_limit(monkeypatch):
    """A 429 mid-batch must not abort the run; the loop backs off and continues."""
    detector = TradingCardDetector(rate_limit_delay=0.5, cache_enabled=False)

    seq = [True, RateLimitError("429"), True]

    def fake_has_cards(app_id):
        value = seq.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    slept: list[float] = []
    detector.has_trading_cards = fake_has_cards
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))

    out = detector.filter_games_with_trading_cards([1, 2, 3], max_games=10)

    assert out == [1, 3]
    # Back-off widened the delay beyond the configured base after the 429.
    assert max(slept) > 0.5
