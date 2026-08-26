"""Additional branch coverage for settings loading and validators."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from steam_idle_bot.config.settings import Settings, _parse_int_list


def test_validate_game_ids_non_iterable():
    with pytest.raises(ValueError, match="positive integers"):
        Settings(username="u", password="p", game_app_ids=123)


def test_load_from_file_missing_path_without_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="Missing credentials"):
        Settings.load_from_file(Path("missing.py"))


def test_load_from_file_reraises_non_missing_validation_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("USERNAME=u\nPASSWORD=p\nMAX_GAMES_TO_IDLE=0\n", encoding="utf-8")

    with pytest.raises(Exception):  # noqa: B017
        Settings.load_from_file()


def test_load_from_file_when_spec_is_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "config.py"
    cfg.write_text("USERNAME='u'\nPASSWORD='p'\n", encoding="utf-8")

    with patch("importlib.util.spec_from_file_location", return_value=None):  # noqa: SIM117
        with pytest.raises(ValueError, match="Missing credentials"):
            Settings.load_from_file(cfg)


def test_parse_int_list_with_only_commas():
    assert _parse_int_list(",,,") == []


def test_parse_cookie_map_tolerates_invalid_and_partial_export_records() -> None:
    from steam_idle_bot.config.settings import _parse_cookie_map

    assert _parse_cookie_map("{invalid") == "{invalid"
    assert _parse_cookie_map("[invalid") == "[invalid"
    # Browser exports can include unrelated/incomplete records; only complete
    # cookie entries are retained.
    assert _parse_cookie_map('[null,{"value":"missing-name"},{"name":"missing-value"},{"name":"ok","value":7}]') == [{"name": "ok", "value": "7", "domain": "steamcommunity.com", "path": "/", "secure": False}]
    assert _parse_cookie_map("sessionid=abc; ; steamLoginSecure=token") == {
        "sessionid": "abc",
        "steamLoginSecure": "token",
    }
    assert _parse_cookie_map("missing-separator") == "missing-separator"
    assert _parse_cookie_map("=missing-key") == "=missing-key"


def test_save_to_env_serializes_browser_cookie_export(tmp_path) -> None:
    settings = Settings(
        username="user",
        password="pass",
        steam_web_cookies=[{"name": "sessionid", "value": "abc"}],
    )

    target = settings.save_to_env_file(tmp_path / ".env")

    assert 'STEAM_WEB_COOKIES=[{"name":"sessionid","value":"abc"}]' in target.read_text(encoding="utf-8")
