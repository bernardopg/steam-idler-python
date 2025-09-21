"""Tests for settings configuration."""

import pytest

from steam_idle_bot.config.settings import Settings


class TestSettings:
    """Test cases for Settings class."""

    def test_default_settings(self):
        """Test default settings values."""
        settings = Settings(username="test_user", password="test_pass")

        assert settings.filter_trading_cards is True
        assert settings.use_owned_games is True
        assert settings.filter_completed_card_drops is True
        assert settings.exclude_app_ids == []
        assert settings.max_games_to_idle == 30
        assert settings.game_app_ids == [570, 730]
        assert settings.log_level == "INFO"

    def test_invalid_credentials(self):
        """Test validation of placeholder credentials."""
        with pytest.raises(ValueError, match="placeholder values"):
            Settings(username="your_steam_username", password="test_pass")

        with pytest.raises(ValueError, match="placeholder values"):
            Settings(username="test_user", password="your_steam_password")

    def test_invalid_game_ids(self):
        """Test validation of game IDs."""
        with pytest.raises(ValueError, match="positive integers"):
            Settings(
                username="test_user",
                password="test_pass",
                game_app_ids=[-1, 0],
            )

    def test_max_games_validation(self):
        """Test validation of max games."""
        with pytest.raises(ValueError):
            Settings(username="test_user", password="test_pass", max_games_to_idle=0)

        with pytest.raises(ValueError):
            Settings(username="test_user", password="test_pass", max_games_to_idle=33)

    def test_log_level_validation(self):
        """Test validation of log level."""
        with pytest.raises(ValueError):
            Settings(username="test_user", password="test_pass", log_level="INVALID")

    def test_rate_limit_validation(self):
        """Test validation of rate limit delay."""
        with pytest.raises(ValueError):
            Settings(username="test_user", password="test_pass", rate_limit_delay=0.0)

        with pytest.raises(ValueError):
            Settings(username="test_user", password="test_pass", rate_limit_delay=6.0)
