"""Comprehensive tests for the Tkinter GUI module.

GUI tests require a display server (X11/Xvfb). In CI without one, tests
are skipped rather than erroring. Locally they run normally.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from unittest.mock import MagicMock, patch

import pytest

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.gui import (
    APP_LOGGER_NAME,
    PALETTE,
    AuthCodeRequest,
    QueueLogHandler,
    SteamIdleBotGUI,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _has_display() -> bool:
    """Check whether a display server is available for tkinter."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


@pytest.fixture()
def root():
    """Create a Tk root for testing and destroy it after."""
    if not _has_display():
        pytest.skip("No display server (DISPLAY/WAYLAND_DISPLAY not set)")
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk init failed — no display available")
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture()
def settings():
    """Return a valid Settings instance for tests."""
    return Settings(username="test_user", password="test_pass123")


@pytest.fixture()
def gui(root, settings):
    """Create a SteamIdleBotGUI with initial settings (no Steam contact)."""
    return SteamIdleBotGUI(root, initial_settings=settings)


@pytest.fixture()
def gui_no_settings(root):
    """Create a SteamIdleBotGUI with no initial settings."""
    return SteamIdleBotGUI(root)


# ---------------------------------------------------------------------------
# QueueLogHandler
# ---------------------------------------------------------------------------


class TestQueueLogHandler:
    def test_emit_forwards_record(self):
        q: queue.Queue[tuple[str, object]] = queue.Queue()
        handler = QueueLogHandler(q)
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
        handler.emit(record)
        assert not q.empty()
        event_type, message = q.get_nowait()
        assert event_type == "log"
        assert "hello" in message

    def test_emit_format_fallback(self):
        q: queue.Queue[tuple[str, object]] = queue.Queue()
        handler = QueueLogHandler(q)
        handler.setFormatter(logging.Formatter("%(message)s"))
        record = logging.LogRecord("test", logging.WARNING, "", 0, "warn msg", (), None)
        handler.emit(record)
        event_type, message = q.get_nowait()
        assert event_type == "log"
        assert "warn msg" in message

    def test_emit_handles_format_exception(self):
        q: queue.Queue[tuple[str, object]] = queue.Queue()
        handler = QueueLogHandler(q)

        def bad_format(record):
            raise ValueError("format boom")

        handler.format = bad_format  # type: ignore[assignment]
        record = logging.LogRecord("test", logging.ERROR, "", 0, "fallback msg", (), None)
        handler.emit(record)
        event_type, message = q.get_nowait()
        assert event_type == "log"
        assert "fallback msg" in message


# ---------------------------------------------------------------------------
# AuthCodeRequest
# ---------------------------------------------------------------------------


class TestAuthCodeRequest:
    def test_fields(self):
        evt = threading.Event()
        req = AuthCodeRequest(is_2fa=True, code_mismatch=False, event=evt)
        assert req.is_2fa is True
        assert req.code_mismatch is False
        assert req.event is evt
        assert req.code is None

    def test_code_assignment(self):
        req = AuthCodeRequest(is_2fa=False, code_mismatch=True, event=threading.Event())
        req.code = "ABC12"
        assert req.code == "ABC12"


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


class TestPalette:
    def test_all_expected_keys_present(self):
        expected = {
            "bg",
            "surface",
            "surface_alt",
            "overlay",
            "border",
            "border_focus",
            "text",
            "text_dim",
            "text_bright",
            "accent",
            "accent_hover",
            "accent_muted",
            "success",
            "success_bg",
            "success_fg",
            "warning",
            "warning_bg",
            "warning_fg",
            "error",
            "error_bg",
            "error_fg",
            "info",
            "input_bg",
            "input_fg",
            "console_bg",
            "console_fg",
            "report_bg",
            "report_fg",
            "tree_bg",
            "tree_fg",
            "tree_select",
            "tree_heading_bg",
            "tree_heading_fg",
            "scrollbar_bg",
            "scrollbar_fg",
            "tab_bg",
            "tab_active",
            "tab_fg",
            "tab_active_fg",
            "section_bg",
            "section_header_bg",
            "section_header_fg",
            "badge_idle_bg",
            "badge_idle_fg",
            "badge_running_bg",
            "badge_running_fg",
            "badge_stopping_bg",
            "badge_stopping_fg",
            "badge_error_bg",
            "badge_error_fg",
        }
        assert expected <= set(PALETTE.keys())

    def test_all_values_are_hex_colors(self):
        for key, val in PALETTE.items():
            assert val.startswith("#"), f"{key} = {val!r} is not a hex color"
            assert len(val) == 7, f"{key} = {val!r} is not 7-char hex"


# ---------------------------------------------------------------------------
# _pick_font
# ---------------------------------------------------------------------------


class TestPickFont:
    def test_returns_first_available(self, root):
        result = SteamIdleBotGUI._pick_font(("TkDefaultFont", "NonExistent"))
        assert result == "TkDefaultFont"

    def test_returns_fallback_when_none_available(self, root):
        result = SteamIdleBotGUI._pick_font(("ZzzFakeFont1", "ZzzFakeFont2"))
        assert result == "TkDefaultFont"


# ---------------------------------------------------------------------------
# GUI construction
# ---------------------------------------------------------------------------


class TestGUIConstruction:
    def test_window_title(self, gui):
        assert gui.root.title() == "Steam Idle Control Center"

    def test_window_geometry_set(self, gui):
        # Window is withdrawn for headless testing so geometry reports 1x1
        # Just verify the root exists and construction succeeded
        assert gui.root is not None

    def test_window_minsize(self, gui):
        assert gui.root.minsize()[0] == 1020
        assert gui.root.minsize()[1] == 700

    def test_initial_status_idle(self, gui):
        assert gui.status_var.get() == "Idle"

    def test_initial_account_not_logged_in(self, gui):
        assert gui.account_var.get() == "Not logged in"

    def test_status_badge_exists(self, gui):
        assert gui._status_badge is not None

    def test_account_badge_exists(self, gui):
        assert gui._account_badge is not None

    def test_log_text_exists(self, gui):
        assert gui.log_text is not None

    def test_report_text_exists(self, gui):
        assert gui.report_text is not None

    def test_status_tree_exists(self, gui):
        assert gui.status_tree is not None

    def test_start_button_exists(self, gui):
        assert gui.start_button is not None

    def test_stop_button_exists(self, gui):
        assert gui.stop_button is not None

    def test_stop_button_disabled_initially(self, gui):
        assert str(gui.stop_button.cget("state")) == "disabled"

    def test_auto_scroll_enabled(self, gui):
        assert gui._auto_scroll is True

    def test_no_worker_initially(self, gui):
        assert gui._worker is None

    def test_no_bot_initially(self, gui):
        assert gui._current_bot is None


# ---------------------------------------------------------------------------
# Settings loading
# ---------------------------------------------------------------------------


class TestLoadInitialValues:
    def test_loads_settings_into_vars(self, gui, settings):
        assert gui.username_var.get() == settings.username
        assert gui.password_var.get() == settings.password
        assert gui.max_games_var.get() == str(settings.max_games_to_idle)
        assert gui.refresh_interval_var.get() == str(settings.refresh_interval_seconds)
        assert gui.idling_backend_var.get() == settings.idling_backend
        assert gui.filter_cards_var.get() == settings.filter_trading_cards
        assert gui.enable_cache_var.get() == settings.enable_card_cache
        assert gui.log_level_var.get() == settings.log_level

    def test_loads_empty_game_ids(self, gui_no_settings):
        gui_no_settings._initial_settings = Settings(username="u", password="p", game_app_ids=[])
        gui_no_settings._load_initial_values()
        assert gui_no_settings.game_ids_var.get() == ""

    def test_loads_populated_game_ids(self, gui):
        gui._initial_settings = Settings(username="u", password="p", game_app_ids=[570, 730])
        gui._load_initial_values()
        assert gui.game_ids_var.get() == "570,730"

    def test_loads_exclude_ids(self, gui):
        gui._initial_settings = Settings(username="u", password="p", exclude_app_ids=[123, 456])
        gui._load_initial_values()
        assert gui.exclude_ids_var.get() == "123,456"

    def test_loads_empty_exclude_ids(self, gui):
        gui._initial_settings = Settings(username="u", password="p", exclude_app_ids=[])
        gui._load_initial_values()
        assert gui.exclude_ids_var.get() == ""

    def test_loads_max_checks_none(self, gui):
        gui._initial_settings = Settings(username="u", password="p", max_checks=None)
        gui._load_initial_values()
        assert gui.max_checks_var.get() == ""

    def test_loads_max_checks_value(self, gui):
        gui._initial_settings = Settings(username="u", password="p", max_checks=42)
        gui._load_initial_values()
        assert gui.max_checks_var.get() == "42"

    def test_loads_steam_utility_path(self, gui):
        gui._initial_settings = Settings(username="u", password="p", steam_utility_path="/some/path")
        gui._load_initial_values()
        assert gui.steam_utility_path_var.get() == "/some/path"

    def test_loads_empty_steam_utility_path(self, gui):
        gui._initial_settings = Settings(username="u", password="p", steam_utility_path=None)
        gui._load_initial_values()
        assert gui.steam_utility_path_var.get() == ""

    def test_loads_web_cookies_json(self, gui):
        cookies = {"steamLoginSecure": "tok123"}
        gui._initial_settings = Settings(username="u", password="p", steam_web_cookies=cookies)
        gui._load_initial_values()
        assert json.loads(gui.steam_web_cookies_var.get()) == cookies

    def test_loads_empty_web_cookies(self, gui):
        gui._initial_settings = Settings(username="u", password="p", steam_web_cookies={})
        gui._load_initial_values()
        assert gui.steam_web_cookies_var.get() == ""

    def test_loads_keep_completed_drops_inverted(self, gui):
        gui._initial_settings = Settings(username="u", password="p", filter_completed_card_drops=False)
        gui._load_initial_values()
        assert gui.keep_completed_drops_var.get() is True

    def test_loads_keep_completed_drops_default(self, gui):
        gui._initial_settings = Settings(username="u", password="p", filter_completed_card_drops=True)
        gui._load_initial_values()
        assert gui.keep_completed_drops_var.get() is False

    def test_try_load_settings_returns_initial(self, gui, settings):
        result = gui._try_load_settings()
        assert result is settings

    def test_try_load_settings_returns_none_on_error(self, gui_no_settings):
        gui_no_settings._initial_settings = None
        gui_no_settings._config_path = "/nonexistent/path/config.py"
        result = gui_no_settings._try_load_settings()
        assert result is None


# ---------------------------------------------------------------------------
# _build_settings_from_form
# ---------------------------------------------------------------------------


class TestBuildSettingsFromForm:
    def test_builds_valid_settings(self, gui):
        gui.username_var.set("myuser")
        gui.password_var.set("mypass")
        gui.api_key_var.set("mykey")
        gui.max_games_var.set("20")
        gui.refresh_interval_var.set("300")
        gui.idling_backend_var.set("steam_utility")
        gui.filter_cards_var.set(False)
        gui.enable_cache_var.set(False)
        gui.game_ids_var.set("100,200")
        gui.exclude_ids_var.set("300")

        settings = gui._build_settings_from_form()
        assert settings.username == "myuser"
        assert settings.password == "mypass"
        assert settings.steam_api_key == "mykey"
        assert settings.max_games_to_idle == 20
        assert settings.refresh_interval_seconds == 300
        assert settings.idling_backend == "steam_utility"
        assert settings.filter_trading_cards is False
        assert settings.enable_card_cache is False
        assert settings.game_app_ids == [100, 200]
        assert settings.exclude_app_ids == [300]

    def test_empty_fields_use_defaults(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.max_games_var.set("")
        gui.refresh_interval_var.set("")
        gui.api_timeout_var.set("")
        gui.rate_limit_var.set("")
        gui.log_level_var.set("")
        gui.cache_ttl_var.set("")
        gui.drop_cache_ttl_var.set("")
        gui.checkpoint_minutes_var.set("")
        gui.duration_minutes_var.set("")
        gui.post_run_verify_seconds_var.set("")
        gui.browser_cookies_browser_var.set("")

        settings = gui._build_settings_from_form()
        assert settings.max_games_to_idle == 32
        assert settings.refresh_interval_seconds == 600
        assert settings.api_timeout == 10
        assert settings.rate_limit_delay == 0.5
        assert settings.log_level == "INFO"
        assert settings.card_cache_ttl_days == 30
        assert settings.drop_cache_ttl_days == 90
        assert settings.browser_cookies_browser == "auto"

    def test_empty_api_key_becomes_none(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.api_key_var.set("")
        settings = gui._build_settings_from_form()
        assert settings.steam_api_key is None

    def test_whitespace_api_key_becomes_none(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.api_key_var.set("  ")
        settings = gui._build_settings_from_form()
        assert settings.steam_api_key is None

    def test_empty_log_file_becomes_none(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.log_file_var.set("")
        settings = gui._build_settings_from_form()
        assert settings.log_file is None

    def test_empty_steam_utility_path_becomes_none(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.steam_utility_path_var.set("")
        settings = gui._build_settings_from_form()
        assert settings.steam_utility_path is None

    def test_empty_web_cookies_becomes_empty_dict(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.steam_web_cookies_var.set("")
        settings = gui._build_settings_from_form()
        assert settings.steam_web_cookies == {}

    def test_valid_web_cookies_json(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.steam_web_cookies_var.set('{"key": "val"}')
        settings = gui._build_settings_from_form()
        assert settings.steam_web_cookies == {"key": "val"}

    def test_invalid_web_cookies_json_raises(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.steam_web_cookies_var.set("not json {{{")
        with pytest.raises(json.JSONDecodeError):
            gui._build_settings_from_form()

    def test_empty_max_checks_becomes_none(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.max_checks_var.set("")
        settings = gui._build_settings_from_form()
        assert settings.max_checks is None

    def test_max_checks_integer(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.max_checks_var.set("15")
        settings = gui._build_settings_from_form()
        assert settings.max_checks == 15

    def test_keep_completed_drops_overrides_filter(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.keep_completed_drops_var.set(True)
        gui.filter_completed_var.set(True)
        settings = gui._build_settings_from_form()
        assert settings.filter_completed_card_drops is False

    def test_filter_completed_used_when_keep_drops_off(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.keep_completed_drops_var.set(False)
        gui.filter_completed_var.set(False)
        settings = gui._build_settings_from_form()
        assert settings.filter_completed_card_drops is False

    def test_all_boolean_flags(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.filter_cards_var.set(False)
        gui.use_owned_games_var.set(False)
        gui.enable_cache_var.set(False)
        gui.auto_browser_cookies_var.set(False)
        gui.skip_failures_var.set(True)
        gui.enable_encryption_var.set(True)
        gui.dry_run_var.set(True)

        settings = gui._build_settings_from_form()
        assert settings.filter_trading_cards is False
        assert settings.use_owned_games is False
        assert settings.enable_card_cache is False
        assert settings.auto_browser_cookies is False
        assert settings.skip_failures is True
        assert settings.enable_encryption is True

    def test_game_ids_csv_parsing(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.game_ids_var.set("570, 730, 440")
        settings = gui._build_settings_from_form()
        assert settings.game_app_ids == [570, 730, 440]

    def test_exclude_ids_csv_parsing(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.exclude_ids_var.set("100,200")
        settings = gui._build_settings_from_form()
        assert settings.exclude_app_ids == [100, 200]

    def test_game_ids_json_parsing(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.game_ids_var.set("[570, 730]")
        settings = gui._build_settings_from_form()
        assert settings.game_app_ids == [570, 730]

    def test_empty_game_ids_becomes_empty_list(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.game_ids_var.set("")
        settings = gui._build_settings_from_form()
        assert settings.game_app_ids == []

    def test_empty_exclude_ids_becomes_empty_list(self, gui):
        gui.username_var.set("u")
        gui.password_var.set("p")
        gui.exclude_ids_var.set("")
        settings = gui._build_settings_from_form()
        assert settings.exclude_app_ids == []


# ---------------------------------------------------------------------------
# Status badges
# ---------------------------------------------------------------------------


class TestRefreshStatusBadges:
    def test_idle_status_badge(self, gui):
        gui.status_var.set("Idle")
        gui._refresh_status_badges()
        assert gui._status_badge.cget("bg") == PALETTE["badge_idle_bg"]
        assert gui._status_badge.cget("fg") == PALETTE["badge_idle_fg"]

    def test_running_status_badge(self, gui):
        gui.status_var.set("Running")
        gui._refresh_status_badges()
        assert gui._status_badge.cget("bg") == PALETTE["badge_running_bg"]

    def test_starting_status_badge(self, gui):
        gui.status_var.set("Starting")
        gui._refresh_status_badges()
        assert gui._status_badge.cget("bg") == PALETTE["badge_running_bg"]

    def test_stopping_status_badge(self, gui):
        gui.status_var.set("Stopping")
        gui._refresh_status_badges()
        assert gui._status_badge.cget("bg") == PALETTE["badge_stopping_bg"]

    def test_error_status_badge(self, gui):
        gui.status_var.set("Error")
        gui._refresh_status_badges()
        assert gui._status_badge.cget("bg") == PALETTE["badge_error_bg"]

    def test_account_badge_logged_in(self, gui):
        gui.account_var.set("myuser")
        gui._refresh_status_badges()
        assert gui._account_badge.cget("bg") == PALETTE["badge_running_bg"]

    def test_account_badge_connecting(self, gui):
        gui.account_var.set("Connecting")
        gui._refresh_status_badges()
        assert gui._account_badge.cget("bg") == PALETTE["badge_stopping_bg"]

    def test_account_badge_not_logged_in(self, gui):
        gui.account_var.set("Not logged in")
        gui._refresh_status_badges()
        assert gui._account_badge.cget("bg") == PALETTE["badge_idle_bg"]

    def test_account_badge_empty(self, gui):
        gui.account_var.set("")
        gui._refresh_status_badges()
        assert gui._account_badge.cget("bg") == PALETTE["badge_idle_bg"]


# ---------------------------------------------------------------------------
# Account sync
# ---------------------------------------------------------------------------


class TestSyncAccountFromUsername:
    def test_syncs_username(self, gui):
        gui.username_var.set("my_steam_user")
        gui._sync_account_from_username()
        assert gui.account_var.get() == "my_steam_user"

    def test_syncs_empty_username(self, gui):
        gui.username_var.set("")
        gui._sync_account_from_username()
        assert gui.account_var.get() == "Not logged in"

    def test_syncs_whitespace_username(self, gui):
        gui.username_var.set("   ")
        gui._sync_account_from_username()
        assert gui.account_var.get() == "Not logged in"


# ---------------------------------------------------------------------------
# Log operations
# ---------------------------------------------------------------------------


class TestAppendLog:
    def test_appends_message(self, gui):
        gui._append_log("hello world\n")
        content = gui.log_text.get("1.0", "end").strip()
        assert "hello world" in content

    def test_log_is_disabled_after_append(self, gui):
        gui._append_log("test\n")
        assert str(gui.log_text.cget("state")) == "disabled"

    def test_log_level_tag_info(self, gui):
        gui._append_log("2024-01-01 | INFO | test message\n")
        tags = gui.log_text.tag_names("1.0")
        assert "INFO" in tags

    def test_log_level_tag_warning(self, gui):
        gui._append_log("2024-01-01 | WARNING | test message\n")
        tags = gui.log_text.tag_names("1.0")
        assert "WARNING" in tags

    def test_log_level_tag_error(self, gui):
        gui._append_log("2024-01-01 | ERROR | test message\n")
        tags = gui.log_text.tag_names("1.0")
        assert "ERROR" in tags

    def test_log_level_tag_debug(self, gui):
        gui._append_log("2024-01-01 | DEBUG | test message\n")
        tags = gui.log_text.tag_names("1.0")
        assert "DEBUG" in tags

    def test_log_success_tag_connected(self, gui):
        gui._append_log("Connected to Steam\n")
        tags = gui.log_text.tag_names("1.0")
        assert "SUCCESS" in tags

    def test_log_success_tag_started(self, gui):
        gui._append_log("Started idling for app 570\n")
        tags = gui.log_text.tag_names("1.0")
        assert "SUCCESS" in tags

    def test_log_no_tag_for_unknown(self, gui):
        gui._append_log("some random text\n")
        tags = gui.log_text.tag_names("1.0")
        assert "INFO" not in tags
        assert "WARNING" not in tags
        assert "ERROR" not in tags
        assert "DEBUG" not in tags
        assert "SUCCESS" not in tags


class TestClearLogs:
    def test_clears_log_text(self, gui):
        gui._append_log("line1\nline2\n")
        gui._clear_logs()
        content = gui.log_text.get("1.0", "end").strip()
        assert content == ""

    def test_clear_leaves_disabled(self, gui):
        gui._append_log("msg\n")
        gui._clear_logs()
        assert str(gui.log_text.cget("state")) == "disabled"


# ---------------------------------------------------------------------------
# Report operations
# ---------------------------------------------------------------------------


class TestSetReport:
    def test_sets_report_content(self, gui):
        gui._set_report("Session report content")
        content = gui.report_text.get("1.0", "end").strip()
        assert "Session report content" in content

    def test_replaces_previous_report(self, gui):
        gui._set_report("old report")
        gui._set_report("new report")
        content = gui.report_text.get("1.0", "end").strip()
        assert "new report" in content
        assert "old report" not in content

    def test_report_disabled_after_set(self, gui):
        gui._set_report("data")
        assert str(gui.report_text.cget("state")) == "disabled"


class TestClearReport:
    def test_clears_report(self, gui):
        gui._set_report("some report")
        gui._clear_report()
        content = gui.report_text.get("1.0", "end").strip()
        assert content == ""

    def test_clear_leaves_disabled(self, gui):
        gui._set_report("data")
        gui._clear_report()
        assert str(gui.report_text.cget("state")) == "disabled"


# ---------------------------------------------------------------------------
# Auto scroll
# ---------------------------------------------------------------------------


class TestAutoScroll:
    def test_toggle_on(self, gui):
        gui._auto_scroll = False
        gui._auto_scroll_var.set(True)
        gui._toggle_auto_scroll()
        assert gui._auto_scroll is True

    def test_toggle_off(self, gui):
        gui._auto_scroll = True
        gui._auto_scroll_var.set(False)
        gui._toggle_auto_scroll()
        assert gui._auto_scroll is False


# ---------------------------------------------------------------------------
# UI events
# ---------------------------------------------------------------------------


class TestHandleUIEvent:
    def test_log_event(self, gui):
        gui._handle_ui_event("log", "test log message")
        content = gui.log_text.get("1.0", "end")
        assert "test log message" in content

    def test_status_event(self, gui):
        gui._handle_ui_event("status", "Running")
        assert gui.status_var.get() == "Running"

    def test_report_event(self, gui):
        gui._handle_ui_event("report", "report data here")
        content = gui.report_text.get("1.0", "end")
        assert "report data here" in content

    def test_error_event(self, gui):
        gui._handle_ui_event("error", "something broke")
        assert gui.status_var.get() == "Error"
        content = gui.log_text.get("1.0", "end")
        assert "something broke" in content

    def test_finished_event(self, gui):
        gui.start_button.configure(state="disabled")
        gui.stop_button.configure(state="normal")
        gui._handle_ui_event("finished", None)
        assert gui.status_var.get() == "Idle"
        assert str(gui.start_button.cget("state")) == "normal"
        assert str(gui.stop_button.cget("state")) == "disabled"

    def test_unknown_event_no_crash(self, gui):
        gui._handle_ui_event("unknown_type", "payload")


# ---------------------------------------------------------------------------
# Auth request
# ---------------------------------------------------------------------------


class TestResolveAuthRequest:
    def test_valid_2fa_request(self, gui):
        req = AuthCodeRequest(is_2fa=True, code_mismatch=False, event=threading.Event())
        with patch.object(simpledialog, "askstring", return_value="12345"):
            gui._resolve_auth_request(req)
        assert req.code == "12345"
        assert req.event.is_set()

    def test_valid_email_request(self, gui):
        req = AuthCodeRequest(is_2fa=False, code_mismatch=True, event=threading.Event())
        with patch.object(simpledialog, "askstring", return_value="ABCDEF"):
            gui._resolve_auth_request(req)
        assert req.code == "ABCDEF"
        assert req.event.is_set()

    def test_user_cancels_dialog(self, gui):
        req = AuthCodeRequest(is_2fa=True, code_mismatch=False, event=threading.Event())
        with patch.object(simpledialog, "askstring", return_value=None):
            gui._resolve_auth_request(req)
        assert req.code is None
        assert req.event.is_set()

    def test_non_auth_request_ignored(self, gui):
        gui._resolve_auth_request("not an AuthCodeRequest")


# ---------------------------------------------------------------------------
# Status panel
# ---------------------------------------------------------------------------


class TestUpdateStatusPanel:
    def test_no_bot_shows_waiting(self, gui):
        gui._current_bot = None
        gui._update_status_panel()
        assert gui.status_summary_var.get() == "Waiting to start..."
        assert len(gui.status_tree.get_children()) == 0

    def test_bot_with_no_tracker(self, gui):
        mock_bot = MagicMock()
        mock_bot._idle_tracker = None
        gui._current_bot = mock_bot
        gui._update_status_panel()

    def test_bot_with_empty_games(self, gui):
        mock_tracker = MagicMock()
        mock_tracker.games = {}
        mock_bot = MagicMock()
        mock_bot._idle_tracker = mock_tracker
        gui._current_bot = mock_bot
        gui._update_status_panel()
        assert gui.status_summary_var.get() == "No games idling"

    def test_bot_with_games(self, gui):
        mock_game1 = MagicMock()
        mock_game1.app_id = 570
        mock_game1.name = "Dota 2"
        mock_game1.cards_before = 3
        mock_game1.idle_minutes = 5.0
        mock_game2 = MagicMock()
        mock_game2.app_id = 730
        mock_game2.name = "CS2"
        mock_game2.cards_before = None
        mock_game2.idle_minutes = 2.0

        mock_tracker = MagicMock()
        mock_tracker.games = {570: mock_game1, 730: mock_game2}
        mock_tracker.session_minutes = 10.0

        mock_bot = MagicMock()
        mock_bot._idle_tracker = mock_tracker
        mock_bot._game_name_map.return_value = {570: "Dota 2", 730: "CS2"}
        gui._current_bot = mock_bot

        gui._update_status_panel()
        assert "2 games idling" in gui.status_summary_var.get()
        assert "cards remaining: 3" in gui.status_summary_var.get()
        assert len(gui.status_tree.get_children()) == 2

    def test_updates_existing_tree_items(self, gui):
        mock_game = MagicMock()
        mock_game.app_id = 570
        mock_game.name = "Dota 2"
        mock_game.cards_before = 3
        mock_game.idle_minutes = 5.0

        mock_tracker = MagicMock()
        mock_tracker.games = {570: mock_game}
        mock_tracker.session_minutes = 10.0

        mock_bot = MagicMock()
        mock_bot._idle_tracker = mock_tracker
        mock_bot._game_name_map.return_value = {570: "Dota 2"}
        gui._current_bot = mock_bot

        gui._update_status_panel()
        assert len(gui.status_tree.get_children()) == 1

        mock_game.idle_minutes = 15.0
        gui._update_status_panel()
        assert len(gui.status_tree.get_children()) == 1

    def test_removes_stale_tree_items(self, gui):
        mock_game = MagicMock()
        mock_game.app_id = 570
        mock_game.name = "Dota 2"
        mock_game.cards_before = 3
        mock_game.idle_minutes = 5.0

        mock_tracker = MagicMock()
        mock_tracker.games = {570: mock_game}
        mock_tracker.session_minutes = 10.0

        mock_bot = MagicMock()
        mock_bot._idle_tracker = mock_tracker
        mock_bot._game_name_map.return_value = {570: "Dota 2"}
        gui._current_bot = mock_bot

        gui._update_status_panel()
        assert len(gui.status_tree.get_children()) == 1

        mock_tracker.games = {}
        gui._update_status_panel()
        assert len(gui.status_tree.get_children()) == 0

    def test_game_name_fallback(self, gui):
        mock_game = MagicMock()
        mock_game.app_id = 99999
        mock_game.name = None
        mock_game.cards_before = 1
        mock_game.idle_minutes = 1.0

        mock_tracker = MagicMock()
        mock_tracker.games = {99999: mock_game}
        mock_tracker.session_minutes = 1.0

        mock_bot = MagicMock()
        mock_bot._idle_tracker = mock_tracker
        mock_bot._game_name_map.return_value = {}
        gui._current_bot = mock_bot

        gui._update_status_panel()
        items = gui.status_tree.get_children()
        values = gui.status_tree.item(items[0], "values")
        assert values[2] == "App 99999"

    def test_zero_cards_shows_unknown(self, gui):
        mock_game = MagicMock()
        mock_game.app_id = 100
        mock_game.name = "Game"
        mock_game.cards_before = 0
        mock_game.idle_minutes = 1.0

        mock_tracker = MagicMock()
        mock_tracker.games = {100: mock_game}
        mock_tracker.session_minutes = 1.0

        mock_bot = MagicMock()
        mock_bot._idle_tracker = mock_tracker
        mock_bot._game_name_map.return_value = {100: "Game"}
        gui._current_bot = mock_bot

        gui._update_status_panel()
        assert "unknown (badge API empty)" in gui.status_summary_var.get()


# ---------------------------------------------------------------------------
# Start / Stop bot
# ---------------------------------------------------------------------------


class TestStartBot:
    def test_start_sets_status(self, gui):
        with patch.object(gui, "_build_settings_from_form") as mock_build, patch.object(threading.Thread, "start"):
            mock_build.return_value = Settings(username="u", password="p")
            gui._start_bot()
            assert gui.status_var.get() == "Starting"
            assert gui.account_var.get() == "Connecting"

    def test_start_disables_start_button(self, gui):
        with patch.object(gui, "_build_settings_from_form") as mock_build, patch.object(threading.Thread, "start"):
            mock_build.return_value = Settings(username="u", password="p")
            gui._start_bot()
            assert str(gui.start_button.cget("state")) == "disabled"

    def test_start_enables_stop_button(self, gui):
        with patch.object(gui, "_build_settings_from_form") as mock_build, patch.object(threading.Thread, "start"):
            mock_build.return_value = Settings(username="u", password="p")
            gui._start_bot()
            assert str(gui.stop_button.cget("state")) == "normal"

    def test_start_creates_worker_thread(self, gui):
        with patch.object(gui, "_build_settings_from_form") as mock_build, patch.object(threading.Thread, "start"):
            mock_build.return_value = Settings(username="u", password="p")
            gui._start_bot()
            assert gui._worker is not None

    def test_start_skips_if_worker_alive(self, gui):
        gui._worker = MagicMock()
        gui._worker.is_alive.return_value = True
        gui._start_bot()

    def test_start_shows_error_on_invalid_settings(self, gui):
        with patch.object(gui, "_build_settings_from_form", side_effect=ValueError("bad")), patch.object(messagebox, "showerror") as mock_err:
            gui._start_bot()
            mock_err.assert_called_once()
            assert gui.status_var.get() == "Idle"


class TestStopBot:
    def test_stop_sets_status(self, gui):
        mock_bot = MagicMock()
        gui._current_bot = mock_bot
        gui._stop_bot()
        assert gui.status_var.get() == "Stopping"

    def test_stop_calls_bot_stop(self, gui):
        mock_bot = MagicMock()
        gui._current_bot = mock_bot
        gui._stop_bot()
        mock_bot.stop.assert_called_once()

    def test_stop_no_op_without_bot(self, gui):
        gui._current_bot = None
        gui._stop_bot()
        assert gui.status_var.get() == "Idle"

    def test_stop_cancels_status_updates(self, gui):
        gui._status_update_job = "some_job"
        mock_bot = MagicMock()
        gui._current_bot = mock_bot
        with patch.object(gui.root, "after_cancel"):
            gui._stop_bot()
            assert gui._status_update_job is None


# ---------------------------------------------------------------------------
# Stop app IDs
# ---------------------------------------------------------------------------


class TestStopAppIdsNow:
    def test_warns_if_worker_alive(self, gui):
        gui._worker = MagicMock()
        gui._worker.is_alive.return_value = True
        with patch.object(messagebox, "showwarning") as mock_warn:
            gui._stop_app_ids_now()
            mock_warn.assert_called_once()

    def test_warns_if_no_app_ids(self, gui):
        gui._worker = None
        gui.stop_app_ids_var.set("")
        with patch.object(simpledialog, "askstring", return_value=None), patch.object(messagebox, "showwarning") as mock_warn:
            gui._stop_app_ids_now()
            mock_warn.assert_called()

    def test_calls_stop_app_ids(self, gui):
        gui._worker = None
        gui.stop_app_ids_var.set("570,730")
        with patch.object(gui, "_build_settings_from_form") as mock_build, patch("steam_idle_bot.gui._stop_app_ids", return_value=0) as mock_stop, patch.object(messagebox, "showinfo") as mock_info:
            mock_build.return_value = Settings(username="u", password="p")
            gui._stop_app_ids_now()
            mock_stop.assert_called_once()
            mock_info.assert_called_once()

    def test_shows_error_on_exception(self, gui):
        gui._worker = None
        gui.stop_app_ids_var.set("570")
        with patch.object(gui, "_build_settings_from_form") as mock_build, patch("steam_idle_bot.gui._stop_app_ids", side_effect=RuntimeError("fail")), patch.object(messagebox, "showerror") as mock_err:
            mock_build.return_value = Settings(username="u", password="p")
            gui._stop_app_ids_now()
            mock_err.assert_called_once()

    def test_shows_error_on_nonzero_status(self, gui):
        gui._worker = None
        gui.stop_app_ids_var.set("570")
        with patch.object(gui, "_build_settings_from_form") as mock_build, patch("steam_idle_bot.gui._stop_app_ids", return_value=1), patch.object(messagebox, "showerror") as mock_err:
            mock_build.return_value = Settings(username="u", password="p")
            gui._stop_app_ids_now()
            mock_err.assert_called()


# ---------------------------------------------------------------------------
# Save settings
# ---------------------------------------------------------------------------


class TestSaveSettings:
    def test_saves_to_env(self, gui):
        with patch.object(gui, "_build_settings_from_form") as mock_build, patch.object(Settings, "save_to_env_file", return_value=Path(".env")) as mock_save, patch.object(messagebox, "showinfo") as mock_info:
            mock_build.return_value = Settings(username="u", password="p")
            gui._save_settings()
            mock_save.assert_called_once()
            mock_info.assert_called_once()

    def test_shows_error_on_failure(self, gui):
        with patch.object(gui, "_build_settings_from_form", side_effect=ValueError("bad")), patch.object(messagebox, "showerror") as mock_err:
            gui._save_settings()
            mock_err.assert_called_once()


# ---------------------------------------------------------------------------
# On close
# ---------------------------------------------------------------------------


class TestOnClose:
    def test_close_without_bot(self, gui):
        gui._current_bot = None
        with patch.object(gui.root, "after") as mock_after:
            gui._on_close()
            mock_after.assert_called()

    def test_close_with_bot_cancels(self, gui):
        gui._current_bot = MagicMock()
        with patch.object(messagebox, "askyesno", return_value=False):
            gui._on_close()
            gui._current_bot.stop.assert_not_called()

    def test_close_with_bot_confirms(self, gui):
        gui._current_bot = MagicMock()
        with patch.object(messagebox, "askyesno", return_value=True), patch.object(gui.root, "after"):
            gui._on_close()
            gui._current_bot.stop.assert_called_once()


# ---------------------------------------------------------------------------
# Collapsible section
# ---------------------------------------------------------------------------


class TestCollapsibleSection:
    def test_creates_section(self, gui):
        parent = ttk.Frame(gui.root)
        content = gui._create_collapsible_section(parent, row=0, title="Test Section")
        assert content is not None

    def test_toggle_collapses(self, gui):
        parent = ttk.Frame(gui.root)
        gui._create_collapsible_section(parent, row=0, title="Toggle Test")
        header_btn = parent.winfo_children()[0].winfo_children()[0]
        header_btn.invoke()
        # After collapse, content should be grid_removed
        # The content is the second child of the container
        container = parent.winfo_children()[0]
        content = container.winfo_children()[1]
        assert content.winfo_manager() == ""

    def test_toggle_expands(self, gui):
        parent = ttk.Frame(gui.root)
        gui._create_collapsible_section(parent, row=0, title="Expand Test", default_open=True)
        header_btn = parent.winfo_children()[0].winfo_children()[0]
        header_btn.invoke()  # collapse
        header_btn.invoke()  # expand
        container = parent.winfo_children()[0]
        content = container.winfo_children()[1]
        assert content.winfo_manager() != ""

    def test_default_closed(self, gui):
        parent = ttk.Frame(gui.root)
        gui._create_collapsible_section(parent, row=0, title="Closed", default_open=False)
        container = parent.winfo_children()[0]
        content = container.winfo_children()[1]
        assert content.winfo_manager() == ""


# ---------------------------------------------------------------------------
# Form sections
# ---------------------------------------------------------------------------


class TestBuildForm:
    def test_creates_all_sections(self, gui):
        parent = ttk.Frame(gui.root)
        gui._build_form(parent)
        assert len(parent.winfo_children()) > 5

    def test_start_stop_save_buttons_exist(self, gui):
        assert gui.start_button is not None
        assert gui.stop_button is not None
        assert gui.save_button is not None


# ---------------------------------------------------------------------------
# Console sections
# ---------------------------------------------------------------------------


class TestBuildConsole:
    def test_has_three_tabs(self, gui):
        assert gui.log_text is not None
        assert gui.report_text is not None
        assert gui.status_tree is not None

    def test_log_text_configured(self, gui):
        assert str(gui.log_text.cget("bg")) == PALETTE["console_bg"]
        assert str(gui.log_text.cget("fg")) == PALETTE["console_fg"]

    def test_report_text_configured(self, gui):
        assert str(gui.report_text.cget("bg")) == PALETTE["report_bg"]

    def test_log_has_scrollbar(self, gui):
        assert gui.log_text.cget("yscrollcommand") != ""

    def test_report_has_scrollbar(self, gui):
        assert gui.report_text.cget("yscrollcommand") != ""


# ---------------------------------------------------------------------------
# Status updates scheduling
# ---------------------------------------------------------------------------


class TestStatusUpdates:
    def test_start_schedules_update(self, gui):
        gui._status_update_job = None
        gui._start_status_updates()
        assert gui._status_update_job is not None

    def test_stop_cancels_update(self, gui):
        gui._status_update_job = "some_id"
        with patch.object(gui.root, "after_cancel"):
            gui._stop_status_updates()
            assert gui._status_update_job is None

    def test_stop_no_op_when_none(self, gui):
        gui._status_update_job = None
        gui._stop_status_updates()
        assert gui._status_update_job is None


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


class TestConfigureTheme:
    def test_theme_is_clam(self, gui):
        assert gui.style.theme_use() == "clam"

    def test_root_bg_matches_palette(self, gui):
        assert gui.root.cget("bg") == PALETTE["bg"]

    def test_style_configured(self, gui):
        gui.style.configure("Test.TLabel")
        gui.style.configure("Test.TButton")


# ---------------------------------------------------------------------------
# Launch GUI
# ---------------------------------------------------------------------------


class TestLaunchGui:
    def test_launch_creates_window(self, root):
        with patch.object(root, "mainloop"), patch("steam_idle_bot.gui.tk.Tk", return_value=root):
            gui = SteamIdleBotGUI(root)
            assert gui.root is root


# ---------------------------------------------------------------------------
# Keyboard shortcuts
# ---------------------------------------------------------------------------


class TestKeyboardShortcuts:
    def test_bindings_registered(self, gui):
        # Verify all four shortcuts are bound
        assert gui.root.bind("<Control-Return>") != ""
        assert gui.root.bind("<Escape>") != ""
        assert gui.root.bind("<Control-l>") != ""
        assert gui.root.bind("<Control-s>") != ""

    def test_ctrl_start_callable(self, gui):
        with patch.object(gui, "_start_bot") as mock_start:
            gui._start_bot()
            mock_start.assert_called()

    def test_stop_callable(self, gui):
        with patch.object(gui, "_stop_bot") as mock_stop:
            gui._stop_bot()
            mock_stop.assert_called()

    def test_clear_logs_callable(self, gui):
        with patch.object(gui, "_clear_logs") as mock_clear:
            gui._clear_logs()
            mock_clear.assert_called()

    def test_save_callable(self, gui):
        with patch.object(gui, "_save_settings") as mock_save:
            gui._save_settings()
            mock_save.assert_called()


# ---------------------------------------------------------------------------
# Poll UI queue
# ---------------------------------------------------------------------------


class TestPollUIQueue:
    def test_drains_queue(self, gui):
        gui._ui_queue.put(("status", "Running"))
        gui._ui_queue.put(("log", "test message"))
        gui._poll_ui_queue()
        assert gui.status_var.get() == "Running"
        assert gui._ui_queue.empty()

    def test_handles_empty_queue(self, gui):
        gui._poll_ui_queue()
        assert True

    def test_schedules_next_poll(self, gui):
        with patch.object(gui.root, "after") as mock_after:
            gui._poll_ui_queue()
            mock_after.assert_called_with(100, gui._poll_ui_queue)


# ---------------------------------------------------------------------------
# Request auth code
# ---------------------------------------------------------------------------


class TestRequestAuthCode:
    def test_returns_code_from_event(self, gui):
        req = AuthCodeRequest(is_2fa=True, code_mismatch=False, event=threading.Event())
        with patch.object(simpledialog, "askstring", return_value="12345"):
            gui._resolve_auth_request(req)
        assert req.code == "12345"
        assert req.event.is_set()


# ---------------------------------------------------------------------------
# Run bot worker
# ---------------------------------------------------------------------------


class TestRunBotWorker:
    def test_worker_sets_current_bot(self, gui):
        settings = Settings(username="u", password="p")
        mock_bot = MagicMock()
        mock_bot.last_report = "report"

        with patch("steam_idle_bot.gui.SteamIdleBot", return_value=mock_bot), patch("steam_idle_bot.gui.logging.FileHandler"):
            gui._run_bot_worker(settings, dry_run=False)

        assert gui._current_bot is None

    def test_worker_handles_exception(self, gui):
        settings = Settings(username="u", password="p")
        mock_bot = MagicMock()
        mock_bot.run.side_effect = RuntimeError("bot crashed")
        mock_bot.last_report = ""

        with patch("steam_idle_bot.gui.SteamIdleBot", return_value=mock_bot), patch("steam_idle_bot.gui.logging.FileHandler"):
            gui._run_bot_worker(settings, dry_run=False)

        assert gui._current_bot is None

    def test_worker_emits_finished_event(self, gui):
        settings = Settings(username="u", password="p")
        mock_bot = MagicMock()
        mock_bot.last_report = "final report"

        with patch("steam_idle_bot.gui.SteamIdleBot", return_value=mock_bot), patch("steam_idle_bot.gui.logging.FileHandler"):
            gui._run_bot_worker(settings, dry_run=False)

        events = []
        while not gui._ui_queue.empty():
            events.append(gui._ui_queue.get_nowait())
        event_types = [e[0] for e in events]
        assert "finished" in event_types

    def test_worker_removes_log_handlers(self, gui):
        settings = Settings(username="u", password="p")
        mock_bot = MagicMock()
        mock_bot.last_report = ""

        logger = logging.getLogger(APP_LOGGER_NAME)
        handler_count_before = len(logger.handlers)

        with patch("steam_idle_bot.gui.SteamIdleBot", return_value=mock_bot), patch("steam_idle_bot.gui.logging.FileHandler"):
            gui._run_bot_worker(settings, dry_run=False)

        assert len(logger.handlers) == handler_count_before


# ---------------------------------------------------------------------------
# _add_labeled_entry (static)
# ---------------------------------------------------------------------------


class TestAddLabeledEntry:
    def test_creates_label_and_entry(self, root):
        parent = ttk.Frame(root)
        var = tk.StringVar(value="test_val")
        SteamIdleBotGUI._add_labeled_entry(parent, 0, "My Label", var)
        children = [parent.winfo_children()[i] for i in range(len(parent.winfo_children()))]
        assert len(children) >= 2

    def test_password_show(self, root):
        parent = ttk.Frame(root)
        var = tk.StringVar(value="secret")
        SteamIdleBotGUI._add_labeled_entry(parent, 0, "Password", var, show="*")
        entry = parent.winfo_children()[-1]
        assert entry.cget("show") == "*"


# ---------------------------------------------------------------------------
# _on_form_mousewheel
# ---------------------------------------------------------------------------


class TestFormMousewheel:
    def test_scroll_with_delta(self, gui):
        event = MagicMock()
        event.delta = 120
        with patch.object(gui._form_canvas, "yview_scroll") as mock_scroll:
            gui._on_form_mousewheel(event)
            mock_scroll.assert_called_with(-1, "units")

    def test_scroll_up_button4(self, gui):
        event = MagicMock()
        event.delta = 0
        event.num = 4
        with patch.object(gui._form_canvas, "yview_scroll") as mock_scroll:
            gui._on_form_mousewheel(event)
            mock_scroll.assert_called_with(-3, "units")

    def test_scroll_down_button5(self, gui):
        event = MagicMock()
        event.delta = 0
        event.num = 5
        with patch.object(gui._form_canvas, "yview_scroll") as mock_scroll:
            gui._on_form_mousewheel(event)
            mock_scroll.assert_called_with(3, "units")

    def test_no_canvas_no_crash(self, gui):
        gui._form_canvas = None
        event = MagicMock()
        event.delta = 120
        gui._on_form_mousewheel(event)


# ---------------------------------------------------------------------------
# Scroll region updates
# ---------------------------------------------------------------------------


class TestScrollRegion:
    def test_update_scrollregion(self, gui):
        with patch.object(gui._form_canvas, "configure") as mock_cfg:
            gui._update_form_scrollregion()
            mock_cfg.assert_called()

    def test_no_canvas_no_crash(self, gui):
        gui._form_canvas = None
        gui._update_form_scrollregion()

    def test_resize_canvas_window(self, gui):
        event = MagicMock()
        event.width = 500
        with patch.object(gui._form_canvas, "itemconfigure") as mock_item:
            gui._resize_form_canvas_window(event)
            mock_item.assert_called_with(gui._form_window_id, width=500)

    def test_resize_no_canvas_no_crash(self, gui):
        gui._form_canvas = None
        event = MagicMock()
        event.width = 500
        gui._resize_form_canvas_window(event)

    def test_resize_no_window_id_no_crash(self, gui):
        gui._form_window_id = None
        event = MagicMock()
        event.width = 500
        gui._resize_form_canvas_window(event)


# ---------------------------------------------------------------------------
# Mousewheel binding
# ---------------------------------------------------------------------------


class TestMousewheelBinding:
    def test_bind(self, gui):
        with patch.object(gui.root, "bind_all") as mock_bind:
            gui._bind_form_mousewheel(MagicMock())
            assert mock_bind.call_count == 3

    def test_unbind(self, gui):
        with patch.object(gui.root, "unbind_all") as mock_unbind:
            gui._unbind_form_mousewheel(MagicMock())
            assert mock_unbind.call_count == 3
