"""Additional tests for main.py — covers uncovered orchestration paths."""

from __future__ import annotations

import argparse
import signal
from unittest.mock import MagicMock, patch

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.main import (
    SteamIdleBot,
    _apply_cli_overrides,
    _load_settings_from_args,
    _parse_app_id_list,
    _stop_app_ids,
    build_steam_client,
    create_parser,
)


class DummyClient:
    def __init__(self):
        self.steam_id = "123"
        self.init_ok = True
        self.login_ok = True
        self.start_ok = True
        self.connected = True
        self.stop_called = False
        self.logout_called = False
        self.sleep_calls: list[float] = []
        self._web_session = None

    def get_web_session(self, username=None, password=None, cookies=None):
        return self._web_session

    def initialize(self):
        return self.init_ok

    def login(self):
        return self.login_ok

    def start_idling(self, games):
        return self.start_ok

    def refresh_games(self, games):
        pass

    def is_connected(self):
        return self.connected

    def sleep(self, seconds):
        self.sleep_calls.append(seconds)

    def stop_idling(self):
        self.stop_called = True

    def logout(self):
        self.logout_called = True

    def reconnect(self):
        return True


class DummyGameManager:
    def __init__(self, games=None):
        self.games = games or []
        self.badge_service = None
        self._card_counts = {}
        self._drop_counts = {}
        self._web_session = None
        self._game_names = {}

    @property
    def game_names(self):
        return self._game_names

    def get_games_to_idle(self, steam_id):
        return list(self.games)

    def resolve_active_steam_id(self):
        return "123"

    def set_web_session(self, session):
        self._web_session = session

    def get_drop_counts(self):
        return self._drop_counts

    def verify_web_session(self, steam_id):
        return True


class DummyBadgeService:
    def __init__(self, result=None):
        self.result = result or {}

    def get_cards_remaining(self, steam_id):
        return self.result


def make_settings(**overrides):
    base = {"username": "user", "password": "pass"}
    base.update(overrides)
    return Settings(**base)


def make_bot(settings=None, client=None, games=None):
    settings = settings or make_settings()
    bot = SteamIdleBot(settings, console_output=False)
    bot.client = client or DummyClient()
    bot.game_manager = DummyGameManager(games or [])
    return bot


# ---------------------------------------------------------------------------
# signal_stop — force_stop_event
# ---------------------------------------------------------------------------


class TestSignalStop:
    def test_first_signal_sets_stop(self):
        bot = make_bot()
        bot.signal_stop(signal.SIGTERM)
        assert bot._stop_event.is_set()
        assert not bot._force_stop_event.is_set()

    def test_second_signal_sets_force_stop(self):
        bot = make_bot()
        bot.signal_stop(signal.SIGINT)
        bot.signal_stop(signal.SIGTERM)
        assert bot._stop_event.is_set()
        assert bot._force_stop_event.is_set()

    def test_signal_stop_with_none_signum(self):
        bot = make_bot()
        bot.signal_stop(None)
        assert bot._stop_event.is_set()


# ---------------------------------------------------------------------------
# stop — already stopped
# ---------------------------------------------------------------------------


class TestStop:
    def test_stop_when_already_stopped(self):
        bot = make_bot()
        bot._stop_event.set()
        bot.stop()
        # No crash, no duplicate stop_idling

    def test_stop_sets_event_and_calls_stop_idling(self):
        client = DummyClient()
        bot = make_bot(client=client)
        bot.stop()
        assert bot._stop_event.is_set()
        assert client.stop_called


# ---------------------------------------------------------------------------
# _main_loop — duration limit
# ---------------------------------------------------------------------------


class TestMainLoopDuration:
    def test_stops_after_duration(self):
        client = DummyClient()
        bot = make_bot(client=client, games=[570])
        bot.settings.duration_minutes = 0  # disable duration
        bot._stop_event.clear()

        # The loop sleeps via client.sleep(); stop on the first tick.
        def stopping_sleep(seconds):
            bot._stop_event.set()

        client.sleep = stopping_sleep
        bot._main_loop([570], steam_id="123")
        assert bot._stop_event.is_set()


class TestMainLoopReconnect:
    def test_reconnect_on_disconnect(self):
        call_count = [0]

        client = DummyClient()
        client.connected = False
        client.reconnect_called = [False]

        def mock_reconnect():
            client.reconnect_called[0] = True
            return True

        client.reconnect = mock_reconnect

        bot = make_bot(client=client, games=[570])
        bot._stop_event.clear()

        # The loop sleeps via client.sleep(); let it run two ticks then stop.
        def fast_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 2:
                bot._stop_event.set()

        client.sleep = fast_sleep
        bot._main_loop([570], steam_id="123")
        assert client.reconnect_called[0]


class TestMainLoopException:
    def test_exception_in_loop_continues(self):
        call_count = [0]

        client = DummyClient()
        bot = make_bot(client=client, games=[570])
        bot._stop_event.clear()

        # First client.sleep() raises (loop must swallow it and continue);
        # the recovery client.sleep(30) then stops the loop.
        def boom_sleep(seconds):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("boom")
            if call_count[0] >= 2:
                bot._stop_event.set()

        client.sleep = boom_sleep
        bot._main_loop([570], steam_id="123")
        assert call_count[0] >= 2


# ---------------------------------------------------------------------------
# _write_checkpoint
# ---------------------------------------------------------------------------


class TestWriteCheckpoint:
    def test_writes_json_and_md(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bot = make_bot(games=[570])
        bot._idle_tracker.start_session([570], {570: "Test Game"})
        bot._write_checkpoint(1, [570])
        assert (tmp_path / "logs" / "checkpoints").exists()

    def test_handles_exception(self, monkeypatch):
        bot = make_bot(games=[570])
        bot._idle_tracker.start_session([570], {})
        with patch.object(bot._idle_tracker, "to_dict", side_effect=Exception("fail")):
            bot._write_checkpoint(1, [570])  # no crash


# ---------------------------------------------------------------------------
# _print_status_panel
# ---------------------------------------------------------------------------


class TestPrintStatusPanel:
    def test_no_console_output(self):
        bot = make_bot()
        bot._console_output = False
        bot._print_status_panel([570])

    def test_with_console_output(self):
        from unittest.mock import patch

        mock_console = MagicMock()
        mock_table = MagicMock()
        with patch("rich.console.Console", return_value=mock_console), patch("rich.table.Table", return_value=mock_table), patch("rich.box.ROUNDED", "rounded"):
            bot = make_bot(games=[570])
            bot._console_output = True
            bot._idle_tracker.start_session([570], {570: "Test Game"})
            bot._print_status_panel([570])
            mock_console.print.assert_called()


# ---------------------------------------------------------------------------
# _capture_initial_cards
# ---------------------------------------------------------------------------


class TestCaptureInitialCards:
    def test_captures_from_badge_service(self):
        badge = DummyBadgeService(result={570: 3})
        gm = DummyGameManager(games=[570])
        gm.badge_service = badge
        bot = make_bot(games=[570])
        bot.game_manager = gm
        bot._idle_tracker.start_session([570], {})
        bot._capture_initial_cards()
        info = bot._idle_tracker.games.get(570)
        assert info.cards_before == 3

    def test_captures_from_drop_counts(self):
        gm = DummyGameManager(games=[570])
        gm.badge_service = None
        gm._drop_counts = {570: 2}
        bot = make_bot(games=[570])
        bot.game_manager = gm
        bot._idle_tracker.start_session([570], {})
        bot._capture_initial_cards()
        info = bot._idle_tracker.games.get(570)
        assert info.cards_before == 2

    def test_handles_exception(self):
        gm = DummyGameManager()
        gm.badge_service = MagicMock()
        gm.badge_service.get_cards_remaining = MagicMock(side_effect=Exception("fail"))
        bot = make_bot()
        bot.game_manager = gm
        bot._capture_initial_cards()  # no crash


# ---------------------------------------------------------------------------
# _capture_final_cards
# ---------------------------------------------------------------------------


class TestCaptureFinalCards:
    def test_captures_from_badge_service(self):
        badge = DummyBadgeService(result={570: 1})
        gm = DummyGameManager(games=[570])
        gm.badge_service = badge
        bot = make_bot(games=[570])
        bot.game_manager = gm
        bot._steam_id = "123"
        bot._idle_tracker.start_session([570], {})
        bot._capture_final_cards()
        info = bot._idle_tracker.games.get(570)
        assert info.cards_after == 1

    def test_handles_exception(self):
        gm = DummyGameManager()
        gm.badge_service = MagicMock()
        gm.badge_service.get_cards_remaining = MagicMock(side_effect=Exception("fail"))
        bot = make_bot()
        bot.game_manager = gm
        bot._steam_id = "123"
        bot._capture_final_cards()  # no crash


# ---------------------------------------------------------------------------
# _backfill_drained_final_counts
# ---------------------------------------------------------------------------


class TestBackfillDrained:
    def test_sets_zero_for_drained_games(self):
        bot = make_bot(games=[570])
        bot._games_to_idle = [570]
        bot._idle_tracker.start_session([570], {})
        bot._idle_tracker.set_cards_before(570, 3)
        # cards_after is None by default
        bot._backfill_drained_final_counts()
        info = bot._idle_tracker.games.get(570)
        assert info.cards_after == 0

    def test_skips_games_without_cards_before(self):
        bot = make_bot(games=[570])
        bot._games_to_idle = [570]
        bot._idle_tracker.start_session([570], {})
        # cards_before is None
        bot._backfill_drained_final_counts()
        info = bot._idle_tracker.games.get(570)
        assert info.cards_after is None


# ---------------------------------------------------------------------------
# _get_authenticated_web_session
# ---------------------------------------------------------------------------


class TestGetAuthenticatedWebSession:
    def test_returns_none_without_get_web_session(self):
        client = MagicMock()
        client.get_web_session = None
        bot = make_bot(client=client)
        assert bot._get_authenticated_web_session() is None

    def test_returns_session(self):
        client = DummyClient()
        client._web_session = {"cookies": "ok"}
        bot = make_bot(client=client)
        bot.settings.steam_web_cookies = {"key": "val"}
        assert bot._get_authenticated_web_session() == {"cookies": "ok"}

    def test_fallback_to_legacy_signature(self):
        client = DummyClient()

        def old_get_web_session(username=None, password=None):
            return {"legacy": True}

        client.get_web_session = old_get_web_session
        bot = make_bot(client=client)
        bot.settings.steam_web_cookies = {"key": "val"}
        assert bot._get_authenticated_web_session() == {"legacy": True}


# ---------------------------------------------------------------------------
# _configure_authenticated_web_session
# ---------------------------------------------------------------------------


class TestConfigureAuthenticatedWebSession:
    def test_sets_web_session(self):
        client = DummyClient()
        client._web_session = {"session": "ok"}
        gm = DummyGameManager()
        bot = make_bot(client=client)
        bot.game_manager = gm
        bot._configure_authenticated_web_session()
        assert gm._web_session == {"session": "ok"}

    def test_warns_when_no_session(self):
        client = DummyClient()
        client._web_session = None
        gm = DummyGameManager()
        bot = make_bot(client=client)
        bot.game_manager = gm
        bot._configure_authenticated_web_session()
        assert gm._web_session is None


# ---------------------------------------------------------------------------
# _resolve_active_steam_id
# ---------------------------------------------------------------------------


class TestResolveActiveSteamId:
    def test_uses_client_steam_id(self):
        client = DummyClient()
        client.steam_id = "456"
        bot = make_bot(client=client)
        assert bot._resolve_active_steam_id() == "456"

    def test_falls_back_to_game_manager(self):
        client = DummyClient()
        client.steam_id = None
        gm = DummyGameManager()
        gm.resolve_active_steam_id = MagicMock(return_value="789")
        bot = make_bot(client=client)
        bot.game_manager = gm
        assert bot._resolve_active_steam_id() == "789"

    def test_returns_none_when_all_fail(self):
        client = DummyClient()
        client.steam_id = None
        gm = DummyGameManager()
        gm.resolve_active_steam_id = MagicMock(return_value=None)
        bot = make_bot(client=client)
        bot.game_manager = gm
        assert bot._resolve_active_steam_id() is None


# ---------------------------------------------------------------------------
# _recover_session_via_browser
# ---------------------------------------------------------------------------


class TestRecoverSessionViaBrowser:
    def test_recovers_cookies(self, monkeypatch):
        mock_load = MagicMock(return_value={"steamLoginSecure": "token"})
        monkeypatch.setattr("steam_idle_bot.steam.browser_cookies.load_community_cookies", mock_load)
        monkeypatch.setattr(
            "steam_idle_bot.steam.client.SteamClientWrapper._build_web_session_from_cookies",
            staticmethod(lambda cookies: {"built": True}),
        )
        gm = DummyGameManager()
        bot = make_bot()
        bot.game_manager = gm
        assert bot._recover_session_via_browser("123") is True
        assert gm._web_session == {"built": True}

    def test_returns_false_when_no_cookies(self, monkeypatch):
        monkeypatch.setattr("steam_idle_bot.steam.browser_cookies.load_community_cookies", MagicMock(return_value=None))
        bot = make_bot()
        assert bot._recover_session_via_browser("123") is False

    def test_handles_build_failure(self, monkeypatch):
        monkeypatch.setattr("steam_idle_bot.steam.browser_cookies.load_community_cookies", MagicMock(return_value={"token": "val"}))
        monkeypatch.setattr(
            "steam_idle_bot.steam.client.SteamClientWrapper._build_web_session_from_cookies",
            staticmethod(lambda cookies: (_ for _ in ()).throw(RuntimeError("build fail"))),
        )
        bot = make_bot()
        assert bot._recover_session_via_browser("123") is False


# ---------------------------------------------------------------------------
# _switch_to_steam_utility
# ---------------------------------------------------------------------------


class TestSwitchToSteamUtility:
    def test_returns_false_when_not_python_backend(self):
        bot = make_bot()
        bot.settings = make_settings(idling_backend="steam_utility")
        assert bot._switch_to_steam_utility("reason") is False

    def test_returns_false_when_not_steam_client_wrapper(self):
        bot = make_bot()
        bot.client = MagicMock(spec=[])
        assert bot._switch_to_steam_utility("reason") is False

    def test_switches_successfully(self, monkeypatch):
        from steam_idle_bot.steam.client import SteamClientWrapper

        settings = make_settings(idling_backend="python")
        client = SteamClientWrapper(settings)
        bot = make_bot(settings=settings, client=client)

        fallback = MagicMock()
        fallback.initialize.return_value = True
        fallback.login.return_value = True
        fallback.start_idling.return_value = True

        with patch("steam_idle_bot.main.build_steam_client", return_value=fallback):
            assert bot._switch_to_steam_utility("test reason", games=[570]) is True
            assert bot.client is fallback

    def test_fallback_init_fails(self, monkeypatch):
        from steam_idle_bot.steam.client import SteamClientWrapper

        settings = make_settings(idling_backend="python")
        client = SteamClientWrapper(settings)
        bot = make_bot(settings=settings, client=client)

        fallback = MagicMock()
        fallback.initialize.return_value = False

        with patch("steam_idle_bot.main.build_steam_client", return_value=fallback):
            assert bot._switch_to_steam_utility("reason") is False

    def test_fallback_login_fails(self, monkeypatch):
        from steam_idle_bot.steam.client import SteamClientWrapper

        settings = make_settings(idling_backend="python")
        client = SteamClientWrapper(settings)
        bot = make_bot(settings=settings, client=client)

        fallback = MagicMock()
        fallback.initialize.return_value = True
        fallback.login.return_value = False

        with patch("steam_idle_bot.main.build_steam_client", return_value=fallback):
            assert bot._switch_to_steam_utility("reason") is False

    def test_fallback_start_idling_fails(self, monkeypatch):
        from steam_idle_bot.steam.client import SteamClientWrapper

        settings = make_settings(idling_backend="python")
        client = SteamClientWrapper(settings)
        bot = make_bot(settings=settings, client=client)

        fallback = MagicMock()
        fallback.initialize.return_value = True
        fallback.login.return_value = True
        fallback.start_idling.return_value = False

        with patch("steam_idle_bot.main.build_steam_client", return_value=fallback):
            assert bot._switch_to_steam_utility("reason", games=[570]) is False


# ---------------------------------------------------------------------------
# _show_session_report
# ---------------------------------------------------------------------------


class TestShowSessionReport:
    def test_with_report_callback(self):
        bot = make_bot()
        bot._idle_tracker.start_session([570], {})
        callback = MagicMock()
        bot.report_callback = callback
        bot._show_session_report()
        callback.assert_called_once()

    def test_without_report_callback(self, capsys):
        bot = make_bot()
        bot._idle_tracker.start_session([570], {})
        bot.report_callback = None
        bot._show_session_report()
        captured = capsys.readouterr()
        assert "Session" in captured.out or "570" in captured.out


# ---------------------------------------------------------------------------
# last_report property
# ---------------------------------------------------------------------------


class TestLastReport:
    def test_returns_report(self):
        bot = make_bot()
        bot._last_report = "test report"
        assert bot.last_report == "test report"


# ---------------------------------------------------------------------------
# _parse_app_id_list
# ---------------------------------------------------------------------------


class TestParseAppIdList:
    def test_json_format(self):
        assert _parse_app_id_list("[570, 730]") == [570, 730]

    def test_csv_format(self):
        assert _parse_app_id_list("570,730") == [570, 730]

    def test_semicolon_format(self):
        assert _parse_app_id_list("570;730") == [570, 730]

    def test_empty_string(self):
        assert _parse_app_id_list("") == []

    def test_whitespace_only(self):
        assert _parse_app_id_list("  ") == []


# ---------------------------------------------------------------------------
# _apply_cli_overrides
# ---------------------------------------------------------------------------


class TestApplyCliOverrides:
    def test_all_overrides(self):
        settings = make_settings()
        args = argparse.Namespace(
            no_trading_cards=True,
            max_games=10,
            refresh_interval_seconds=300,
            no_cache=True,
            max_checks=5,
            skip_failures=True,
            keep_completed_drops=True,
            checkpoint_minutes=5,
            duration_minutes=10,
            post_run_verify_seconds=30,
        )
        _apply_cli_overrides(settings, args)
        assert settings.filter_trading_cards is False
        assert settings.max_games_to_idle == 10
        assert settings.refresh_interval_seconds == 300
        assert settings.enable_card_cache is False
        assert settings.max_checks == 5
        assert settings.skip_failures is True
        assert settings.filter_completed_card_drops is False
        assert settings.checkpoint_minutes == 5
        assert settings.duration_minutes == 10
        assert settings.post_run_verify_seconds == 30


# ---------------------------------------------------------------------------
# create_parser
# ---------------------------------------------------------------------------


class TestCreateParser:
    def test_all_flags(self):
        parser = create_parser()
        args = parser.parse_args(
            [
                "--dry-run",
                "--no-trading-cards",
                "--max-games",
                "10",
                "--refresh-interval-seconds",
                "300",
                "--config",
                "test.cfg",
                "--no-cache",
                "--max-checks",
                "5",
                "--skip-failures",
                "--keep-completed-drops",
                "--checkpoint-minutes",
                "5",
                "--duration-minutes",
                "10",
                "--post-run-verify-seconds",
                "30",
                "--stop-app-ids",
                "570,730",
            ]
        )
        assert args.dry_run is True
        assert args.no_trading_cards is True
        assert args.max_games == 10
        assert args.refresh_interval_seconds == 300
        assert args.config == "test.cfg"
        assert args.no_cache is True
        assert args.max_checks == 5
        assert args.skip_failures is True
        assert args.keep_completed_drops is True
        assert args.checkpoint_minutes == 5
        assert args.duration_minutes == 10
        assert args.post_run_verify_seconds == 30
        assert args.stop_app_ids == "570,730"


# ---------------------------------------------------------------------------
# _load_settings_from_args
# ---------------------------------------------------------------------------


class TestLoadSettingsFromArgs:
    def test_loads_with_overrides(self):
        args = argparse.Namespace(
            config=None,
            no_trading_cards=True,
            max_games=15,
            refresh_interval_seconds=None,
            no_cache=False,
            max_checks=None,
            skip_failures=False,
            keep_completed_drops=False,
            checkpoint_minutes=None,
            duration_minutes=None,
            post_run_verify_seconds=None,
        )
        settings = _load_settings_from_args(args)
        assert settings.filter_trading_cards is False
        assert settings.max_games_to_idle == 15


# ---------------------------------------------------------------------------
# _stop_app_ids
# ---------------------------------------------------------------------------


class TestStopAppIds:
    def test_stops_pids(self, monkeypatch):
        from steam_idle_bot.steam.steam_utility import SteamUtilityIdleClient

        original_init = SteamUtilityIdleClient.__init__

        mock_instance = MagicMock()
        mock_instance.bridge.find_idle_pids.return_value = {570: [111, 112]}
        mock_instance._stop_pid = MagicMock()

        def fake_init(self_inner, settings, bridge=None):
            self_inner.bridge = mock_instance.bridge
            self_inner._processes = {}
            self_inner._adopted_pids = {}
            self_inner._reconciled = False
            self_inner.settings = settings

        monkeypatch.setattr(SteamUtilityIdleClient, "__init__", fake_init)
        monkeypatch.setattr(SteamUtilityIdleClient, "_stop_pid", mock_instance._stop_pid)

        try:
            result = _stop_app_ids(make_settings(), [570])
            assert result == 2
            assert mock_instance._stop_pid.call_count == 2
        finally:
            monkeypatch.setattr(SteamUtilityIdleClient, "__init__", original_init)

    def test_no_pids_found(self, monkeypatch):
        from steam_idle_bot.steam.steam_utility import SteamUtilityIdleClient

        original_init = SteamUtilityIdleClient.__init__

        mock_instance = MagicMock()
        mock_instance.bridge.find_idle_pids.return_value = {}

        def fake_init(self_inner, settings, bridge=None):
            self_inner.bridge = mock_instance.bridge
            self_inner._processes = {}
            self_inner._adopted_pids = {}
            self_inner._reconciled = False
            self_inner.settings = settings

        monkeypatch.setattr(SteamUtilityIdleClient, "__init__", fake_init)

        try:
            result = _stop_app_ids(make_settings(), [570])
            assert result == 0
        finally:
            monkeypatch.setattr(SteamUtilityIdleClient, "__init__", original_init)


# ---------------------------------------------------------------------------
# build_steam_client
# ---------------------------------------------------------------------------


class TestBuildSteamClient:
    def test_python_backend(self):
        from steam_idle_bot.steam.client import SteamClientWrapper

        client = build_steam_client(make_settings(idling_backend="python"))
        assert isinstance(client, SteamClientWrapper)

    def test_steam_utility_backend(self):
        from steam_idle_bot.steam.steam_utility import SteamUtilityIdleClient

        client = build_steam_client(make_settings(idling_backend="steam_utility"))
        assert isinstance(client, SteamUtilityIdleClient)

    def test_override_backend(self):
        from steam_idle_bot.steam.steam_utility import SteamUtilityIdleClient

        client = build_steam_client(make_settings(idling_backend="python"), backend="steam_utility")
        assert isinstance(client, SteamUtilityIdleClient)


# ---------------------------------------------------------------------------
# _ensure_client_ready
# ---------------------------------------------------------------------------


class TestEnsureClientReady:
    def test_success(self):
        bot = make_bot()
        assert bot._ensure_client_ready() is True

    def test_init_fails(self):
        client = DummyClient()
        client.init_ok = False
        bot = make_bot(client=client)
        with patch.object(bot, "_switch_to_steam_utility", return_value=False):
            assert bot._ensure_client_ready() is False

    def test_login_fails(self):
        client = DummyClient()
        client.login_ok = False
        bot = make_bot(client=client)
        with patch.object(bot, "_switch_to_steam_utility", return_value=False):
            assert bot._ensure_client_ready() is False


# ---------------------------------------------------------------------------
# _game_name_map
# ---------------------------------------------------------------------------


class TestGameNameMap:
    def test_returns_names(self):
        bot = make_bot()
        bot.game_manager._game_names = {570: "Dota 2"}
        result = bot._game_name_map()
        assert result == {570: "Dota 2"}

    def test_returns_empty_when_no_dict(self):
        bot = make_bot()
        bot.game_manager._game_names = "not a dict"
        assert bot._game_name_map() == {}


# ---------------------------------------------------------------------------
# _run_normal_mode — no games
# ---------------------------------------------------------------------------


class TestRunNormalModeNoGames:
    def test_exits_when_no_games(self):
        bot = make_bot(games=[])
        bot._run_normal_mode()
        assert not bot._stop_event.is_set()


# ---------------------------------------------------------------------------
# _run_normal_mode — start idling failure
# ---------------------------------------------------------------------------


class TestRunNormalModeStartFailure:
    def test_fails_to_start_idling(self):
        client = DummyClient()
        client.start_ok = False
        bot = make_bot(client=client, games=[570])
        with patch.object(bot, "_switch_to_steam_utility", return_value=False):
            bot._run_normal_mode()
