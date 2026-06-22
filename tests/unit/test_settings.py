"""Tests for settings configuration."""

import json

import pytest

from steam_idle_bot.config.settings import (
    Settings,
    _parse_int_list,
    _prepare_special_field_value,
)


class TestSettings:
    """Test cases for Settings class."""

    def test_default_settings(self, tmp_path, monkeypatch):
        """Test default settings values."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        settings = Settings(username="test_user", password="test_pass")

        assert settings.filter_trading_cards is True
        assert settings.use_owned_games is True
        assert settings.filter_completed_card_drops is True
        assert settings.exclude_app_ids == []
        assert settings.max_games_to_idle == 30
        assert settings.idling_backend == "python"
        assert settings.steam_utility_path is None
        assert settings.game_app_ids == [570, 730]
        assert settings.log_level == "INFO"

    def test_parse_int_list_helper(self):
        """Test tolerant list parsing helper."""
        assert _parse_int_list([1, 2]) == [1, 2]
        assert _parse_int_list(" ") == []
        assert _parse_int_list("1, 2,3") == [1, 2, 3]
        assert _parse_int_list("[10, 20]") == [10, 20]
        assert _parse_int_list("[broken") == "[broken"
        assert _parse_int_list("a,b") == "a,b"

    def test_parse_cookie_map_helper(self):
        """Test tolerant cookie map parsing helper."""
        from steam_idle_bot.config.settings import _parse_cookie_map

        assert _parse_cookie_map({"steamLoginSecure": "token"}) == {"steamLoginSecure": "token"}
        assert _parse_cookie_map("") == {}
        assert _parse_cookie_map('{"steamLoginSecure": "token"}') == {"steamLoginSecure": "token"}
        assert _parse_cookie_map("steamLoginSecure=token; sessionid=abc") == {
            "steamLoginSecure": "token",
            "sessionid": "abc",
        }
        parsed_list = _parse_cookie_map('[{"name":"steamLoginSecure","value":"token","domain":"steamcommunity.com","path":"/","secure":true}]')
        assert isinstance(parsed_list, list)
        assert parsed_list[0]["name"] == "steamLoginSecure"
        assert parsed_list[0]["domain"] == "steamcommunity.com"

    def test_prepare_special_field_value(self):
        """Test special field preparation for env parsing."""
        assert _prepare_special_field_value("game_app_ids", "10,20") == (True, [10, 20])
        assert _prepare_special_field_value("max_checks", "   ") == (True, None)
        assert _prepare_special_field_value("steam_web_cookies", '{"steamLoginSecure": "token"}') == (
            True,
            {"steamLoginSecure": "token"},
        )
        assert _prepare_special_field_value("username", "user") == (False, "user")

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

    def test_load_from_file_reads_dotenv_without_export(self, tmp_path, monkeypatch):
        """Test .env loading without requiring shell-level exported variables."""
        for key in (
            "USERNAME",
            "PASSWORD",
            "STEAM_USERNAME",
            "STEAM_PASSWORD",
            "GAME_APP_IDS",
            "EXCLUDE_APP_IDS",
            "MAX_CHECKS",
            "STEAM_WEB_COOKIES",
        ):
            monkeypatch.delenv(key, raising=False)

        (tmp_path / ".env").write_text(
            "\n".join(
                [
                    "USERNAME=test_user",
                    "PASSWORD=test_pass",
                    "GAME_APP_IDS=570,730",
                    "EXCLUDE_APP_IDS=",
                    "MAX_CHECKS=",
                    'STEAM_WEB_COOKIES={"steamLoginSecure":"token","sessionid":"abc"}',
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)

        settings = Settings.load_from_file()

        assert settings.username == "test_user"
        assert settings.password == "test_pass"
        assert settings.game_app_ids == [570, 730]
        assert settings.exclude_app_ids == []
        assert settings.max_checks is None
        assert settings.steam_web_cookies == {
            "steamLoginSecure": "token",
            "sessionid": "abc",
        }

    def test_load_from_file_requires_credentials(self, tmp_path, monkeypatch):
        """Test clear error when credentials are missing in config.py and .env."""
        for key in (
            "USERNAME",
            "PASSWORD",
            "STEAM_USERNAME",
            "STEAM_PASSWORD",
            "GAME_APP_IDS",
            "EXCLUDE_APP_IDS",
            "MAX_CHECKS",
            "STEAM_WEB_COOKIES",
        ):
            monkeypatch.delenv(key, raising=False)

        (tmp_path / ".env").write_text("GAME_APP_IDS=570,730\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(ValueError, match="Missing credentials"):
            Settings.load_from_file()

    def test_load_from_legacy_config_file(self, tmp_path, monkeypatch):
        """Test loading from legacy config.py mapping."""
        monkeypatch.chdir(tmp_path)
        cfg = tmp_path / "config.py"
        cfg.write_text(
            "\n".join(
                [
                    "USERNAME='legacy_user'",
                    "PASSWORD='legacy_pass'",
                    "GAME_APP_IDS=[10, 20]",
                    "FILTER_TRADING_CARDS=False",
                    "LOG_LEVEL='WARNING'",
                ]
            ),
            encoding="utf-8",
        )

        settings = Settings.load_from_file(cfg)

        assert settings.username == "legacy_user"
        assert settings.password == "legacy_pass"
        assert settings.game_app_ids == [10, 20]
        assert settings.filter_trading_cards is False
        assert settings.log_level == "WARNING"

    def test_save_to_env_file(self, tmp_path, monkeypatch):
        """Test persisting settings in dotenv format for the GUI."""
        monkeypatch.delenv("STEAM_WEB_COOKIES", raising=False)
        monkeypatch.chdir(tmp_path)
        settings = Settings(
            username="gui_user",
            password="gui_pass",
            game_app_ids=[10, 20],
            exclude_app_ids=[30],
            steam_web_cookies={"steamLoginSecure": "token", "sessionid": "abc"},
            log_file="steam_card_idler.log",
            max_checks=None,
        )

        target = settings.save_to_env_file(tmp_path / ".env")

        saved = target.read_text(encoding="utf-8")
        assert "USERNAME=gui_user" in saved
        assert "PASSWORD=gui_pass" in saved
        assert "GAME_APP_IDS=10,20" in saved
        assert "EXCLUDE_APP_IDS=30" in saved
        assert "IDLING_BACKEND=python" in saved
        assert "STEAM_UTILITY_PATH=" in saved
        cookie_line = next(line for line in saved.splitlines() if line.startswith("STEAM_WEB_COOKIES="))
        cookie_json = cookie_line.split("=", 1)[1]
        assert json.loads(cookie_json) == {
            "steamLoginSecure": "token",
            "sessionid": "abc",
        }
        assert "MAX_CHECKS=" in saved
