"""Tests for trading card detection."""

import time
from unittest.mock import Mock, patch

import pytest

from steam_idle_bot.steam.trading_cards import TradingCardDetector
from steam_idle_bot.utils.exceptions import (
    SteamAPITimeoutError,
    TradingCardDetectionError,
)


class TestTradingCardDetector:
    """Test cases for TradingCardDetector."""

    def test_init(self):
        """Test initialization."""
        detector = TradingCardDetector(timeout=5, rate_limit_delay=0.1, cache_enabled=False)
        assert detector.timeout == 5
        assert detector.rate_limit_delay == 0.1
        assert detector._cache == {}

    def test_has_trading_cards_with_cache(self):
        """Test cache functionality."""
        detector = TradingCardDetector()
        detector._cache[123] = True

        result = detector.has_trading_cards(123)
        assert result is True

    @patch("steam_idle_bot.steam.trading_cards.requests.get")
    def test_has_trading_cards_success(self, mock_get):
        """Test successful trading card detection."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "123": {
                "success": True,
                "data": {"categories": [{"id": 29, "description": "Steam Trading Cards"}]},
            }
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        detector = TradingCardDetector()
        result = detector.has_trading_cards(123)

        assert result is True
        assert 123 in detector._cache
        assert detector._cache[123] is True

    @patch("steam_idle_bot.steam.trading_cards.requests.get")
    def test_has_trading_cards_no_cards(self, mock_get):
        """Test game without trading cards."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "123": {
                "success": True,
                "data": {"categories": [{"id": 1, "description": "Multi-player"}]},
            }
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        detector = TradingCardDetector()
        result = detector.has_trading_cards(123)

        assert result is False
        assert detector._cache[123] is False

    @patch("steam_idle_bot.steam.trading_cards.requests.get")
    def test_has_trading_cards_api_failure_is_cached_as_false(self, mock_get):
        """Steam appdetails misses should be treated as a cached no-card result."""
        mock_response = Mock()
        mock_response.json.return_value = {"123": {"success": False}}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        detector = TradingCardDetector()
        assert detector.has_trading_cards(123) is False
        assert detector._cache[123] is False

    @patch("steam_idle_bot.steam.trading_cards.requests.get")
    def test_has_trading_cards_timeout(self, mock_get):
        """Test timeout handling."""
        mock_get.side_effect = TimeoutError()

        detector = TradingCardDetector()

        with pytest.raises(SteamAPITimeoutError):
            detector.has_trading_cards(123)

    @patch("steam_idle_bot.steam.trading_cards.requests.get")
    def test_has_trading_cards_network_error(self, mock_get):
        """Test network error handling."""
        mock_get.side_effect = Exception("Network error")

        detector = TradingCardDetector()

        with pytest.raises(TradingCardDetectionError):
            detector.has_trading_cards(123)

    @patch("steam_idle_bot.steam.trading_cards.TradingCardDetector.has_trading_cards")
    def test_filter_games_with_trading_cards(self, mock_has_cards):
        """Test filtering games with trading cards."""
        mock_has_cards.side_effect = [True, False, True]

        detector = TradingCardDetector(rate_limit_delay=0)
        games = [1, 2, 3]
        result = detector.filter_games_with_trading_cards(games, max_games=2)

        assert result == [1, 3]

    def test_filter_games_with_trading_cards_skips_sleep_for_cached_results(self):
        """Cached trading-card checks should not incur rate-limit delay."""
        detector = TradingCardDetector(rate_limit_delay=0.5, cache_enabled=False)
        detector._cache = {1: True, 2: False, 3: True}

        with patch.object(time, "sleep") as mock_sleep:
            result = detector.filter_games_with_trading_cards([1, 2, 3], max_games=3)

        assert result == [1, 3]
        mock_sleep.assert_not_called()

    def test_clear_cache(self):
        """Test cache clearing."""
        detector = TradingCardDetector()
        detector._cache = {1: True, 2: False}

        detector.clear_cache()
        assert detector._cache == {}

    def test_get_cache_stats(self):
        """Test cache statistics."""
        detector = TradingCardDetector()
        detector._cache = {1: True, 2: False, 3: True}

        stats = detector.get_cache_stats()

        assert stats["cached_games"] == 3
        assert stats["games_with_cards"] == 2
        assert stats["games_without_cards"] == 1
