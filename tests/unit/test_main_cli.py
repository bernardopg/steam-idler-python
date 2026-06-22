"""Tests for CLI and orchestration paths in main module."""

from __future__ import annotations

import importlib
import runpy
from types import SimpleNamespace

import pytest

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.main import SteamIdleBot, create_parser, main

main_module = importlib.import_module("steam_idle_bot.main")


class DummyLogger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def info(self, msg):
        self.messages.append(("info", str(msg)))

    def error(self, msg):
        self.messages.append(("error", str(msg)))

    def warning(self, msg):
        self.messages.append(("warning", str(msg)))

    def debug(self, msg):
        self.messages.append(("debug", str(msg)))


class DummyClient:
    def __init__(self) -> None:
        self.steam_id = "123"
        self.init_ok = True
        self.login_ok = True
        self.start_ok = True
        self.connected = True
        self.refresh_calls: list[list[int]] = []
        self.sleep_calls: list[int] = []
        self.stop_called = False
        self.logout_called = False

    def get_web_session(self, username=None, password=None):
        return None

    def initialize(self):
        return self.init_ok

    def login(self):
        return self.login_ok

    def start_idling(self, games):
        return self.start_ok

    def refresh_games(self, games):
        self.refresh_calls.append(list(games))

    def is_connected(self):
        return self.connected

    def sleep(self, seconds):
        self.sleep_calls.append(seconds)

    def stop_idling(self):
        self.stop_called = True

    def logout(self):
        self.logout_called = True


class DummyBadgeService:
    def __init__(self, result=None, exc=None):
        self.result = result or {}
        self.exc = exc

    def _fetch_cards_remaining(self, steam_id):
        if self.exc:
            raise self.exc
        return self.result


class DummyGameManager:
    def __init__(self, games):
        self.games = list(games)
        self.badge_service = None
        self._card_counts = {10: 4}

    def get_games_to_idle(self, steam_id):
        return list(self.games)


def make_settings(**overrides):
    base = {
        "username": "user",
        "password": "pass",
        "game_app_ids": [10, 20],
        "max_games_to_idle": 2,
        "filter_completed_card_drops": True,
    }
    base.update(overrides)
    return Settings(**base)


def _build_bot(settings=None):
    settings = settings or make_settings()
    bot = SteamIdleBot(settings)
    bot.logger = DummyLogger()
    bot.client = DummyClient()
    bot.game_manager = DummyGameManager([10, 20])
    return bot


def test_run_dry_mode_and_cleanup(monkeypatch):
    bot = _build_bot()

    called = {"cleanup": 0, "report": 0}
    monkeypatch.setattr(bot, "_cleanup", lambda: called.__setitem__("cleanup", 1))
    monkeypatch.setattr(bot, "_show_session_report", lambda: called.__setitem__("report", 1))

    bot.run(dry_run=True)

    assert called == {"cleanup": 1, "report": 1}


def test_run_handles_keyboard_interrupt(monkeypatch):
    bot = _build_bot()
    monkeypatch.setattr(bot, "_run_normal_mode", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(bot, "_show_session_report", lambda: None)
    monkeypatch.setattr(bot, "_cleanup", lambda: None)

    bot.run()
    assert any("interrupted" in msg for level, msg in bot.logger.messages if level == "info")


def test_run_reraises_unexpected_exception(monkeypatch):
    bot = _build_bot()
    monkeypatch.setattr(bot, "_run_normal_mode", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(bot, "_show_session_report", lambda: None)
    monkeypatch.setattr(bot, "_cleanup", lambda: None)

    with pytest.raises(RuntimeError):
        bot.run()


def test_run_normal_mode_failure_paths(monkeypatch):
    bot = _build_bot()

    bot.client.init_ok = False
    with patch_sys_exit(monkeypatch) as exits, pytest.raises(SystemExit):
        bot._run_normal_mode()
    assert exits == [1]

    bot = _build_bot()
    bot.client.login_ok = False
    with patch_sys_exit(monkeypatch) as exits, pytest.raises(SystemExit):
        bot._run_normal_mode()
    assert exits == [1]

    bot = _build_bot()
    bot.game_manager = DummyGameManager([])
    bot._run_normal_mode()
    assert any("No games to idle" in msg for level, msg in bot.logger.messages if level == "error")

    bot = _build_bot()
    bot.client.start_ok = False
    bot._run_normal_mode()
    assert any("Failed to start idling" in msg for level, msg in bot.logger.messages if level == "error")


def test_ensure_client_ready_uses_failover_on_initialize_failure(monkeypatch):
    bot = _build_bot()
    bot.client.init_ok = False
    called: list[str] = []
    monkeypatch.setattr(
        bot,
        "_switch_to_steam_utility",
        lambda reason, games=None: called.append(reason) or True,
    )

    assert bot._ensure_client_ready() is True
    assert called == ["python client initialization failure"]


def test_ensure_client_ready_uses_failover_on_login_failure(monkeypatch):
    bot = _build_bot()
    bot.client.login_ok = False
    called: list[str] = []
    monkeypatch.setattr(
        bot,
        "_switch_to_steam_utility",
        lambda reason, games=None: called.append(reason) or True,
    )

    assert bot._ensure_client_ready() is True
    assert called == ["python client login failure"]


def test_run_normal_mode_uses_failover_when_start_idling_fails(monkeypatch):
    bot = _build_bot()
    bot.client.start_ok = False
    switched: list[tuple[str, list[int] | None]] = []
    monkeypatch.setattr(
        bot,
        "_switch_to_steam_utility",
        lambda reason, games=None: switched.append((reason, games)) or True,
    )
    monkeypatch.setattr(bot, "_main_loop", lambda games, steam_id=None: None)

    bot._run_normal_mode()

    assert switched == [("failed to start idling with python backend", [10, 20])]


def test_main_loop_handles_refresh_and_disconnect(monkeypatch):
    bot = _build_bot()
    bot._running = True

    def get_games(_steam_id):
        bot._running = False
        return [10, 30]

    bot.game_manager.get_games_to_idle = get_games

    seq = iter([0.0, 700.0, 700.0])
    monkeypatch.setattr("time.time", lambda: next(seq))

    bot.client.sleep = lambda seconds: None
    bot._main_loop([10, 20])

    assert bot.client.refresh_calls == [[10, 30]]


def test_main_loop_handles_errors(monkeypatch):
    bot = _build_bot()
    bot._running = True

    monkeypatch.setattr("time.time", lambda: 0.0)

    calls = {"count": 0}

    def fake_sleep(seconds):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("loop error")
        bot._running = False

    bot.client.sleep = fake_sleep
    bot._main_loop([10, 20])


def test_main_loop_keyboard_interrupt_stops(monkeypatch):
    bot = _build_bot()
    bot._running = True
    bot.client.sleep = lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt())
    bot._main_loop([1])


def test_capture_cards_paths():
    bot = _build_bot()
    bot.game_manager.badge_service = DummyBadgeService({10: 3, 20: 1})
    bot._capture_initial_cards()
    bot._idle_tracker.start_session([10, 20])
    assert bot._idle_tracker.games[10].cards_before == 3
    assert bot._idle_tracker.games[20].cards_before == 1
    bot._capture_final_cards()
    assert bot._idle_tracker.games[10].cards_after == 3
    assert bot._idle_tracker.games[20].cards_after == 1

    bot.game_manager.badge_service = None
    bot.game_manager._card_counts = {10: 2}
    bot._capture_initial_cards()
    bot._capture_final_cards()

    bot.game_manager.badge_service = DummyBadgeService(exc=RuntimeError("x"))
    bot._capture_initial_cards()
    bot._capture_final_cards()


def test_show_session_report_and_cleanup(tmp_path, monkeypatch):
    bot = _build_bot()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        main_module,
        "time",
        SimpleNamespace(strftime=lambda fmt: "20260101_010101"),
    )

    bot._show_session_report()
    report_file = tmp_path / "logs" / "idle_report_20260101_010101.txt"
    assert report_file.exists()

    bot._cleanup()
    assert bot.client.stop_called is True
    assert bot.client.logout_called is True


def test_create_parser_parses_flags():
    parser = create_parser()
    args = parser.parse_args(
        [
            "--gui",
            "--dry-run",
            "--no-trading-cards",
            "--max-games",
            "5",
            "--config",
            "cfg.py",
            "--no-cache",
            "--max-checks",
            "7",
            "--skip-failures",
            "--keep-completed-drops",
        ]
    )
    assert args.gui is True
    assert args.dry_run is True
    assert args.no_trading_cards is True
    assert args.max_games == 5
    assert args.config == "cfg.py"
    assert args.no_cache is True
    assert args.max_checks == 7
    assert args.skip_failures is True
    assert args.keep_completed_drops is True


def test_main_applies_overrides(monkeypatch):
    args = SimpleNamespace(
        gui=False,
        config="config.py",
        no_trading_cards=True,
        max_games=4,
        no_cache=True,
        max_checks=8,
        skip_failures=True,
        keep_completed_drops=True,
        dry_run=True,
    )
    parser = SimpleNamespace(parse_args=lambda: args)

    settings = make_settings()
    state = {}

    class Bot:
        def __init__(self, s):
            state["settings"] = s

        def run(self, dry_run=False):
            state["dry_run"] = dry_run

    monkeypatch.setattr(main_module, "create_parser", lambda: parser)
    monkeypatch.setattr(main_module.Settings, "load_from_file", lambda p: settings)
    monkeypatch.setattr(main_module, "SteamIdleBot", Bot)

    main()

    assert settings.filter_trading_cards is False
    assert settings.max_games_to_idle == 4
    assert settings.enable_card_cache is False
    assert settings.max_checks == 8
    assert settings.skip_failures is True
    assert settings.filter_completed_card_drops is False
    assert state["dry_run"] is True


def test_main_keyboard_interrupt_and_fatal(monkeypatch, capsys):
    parser = SimpleNamespace(
        parse_args=lambda: SimpleNamespace(
            gui=False,
            config=None,
            no_trading_cards=False,
            max_games=None,
            no_cache=False,
            max_checks=None,
            skip_failures=False,
            keep_completed_drops=False,
            dry_run=False,
        )
    )

    monkeypatch.setattr(main_module, "create_parser", lambda: parser)
    monkeypatch.setattr(
        main_module.Settings,
        "load_from_file",
        lambda p: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    main()
    assert "interrupted" in capsys.readouterr().out.lower()

    monkeypatch.setattr(
        main_module.Settings,
        "load_from_file",
        lambda p: (_ for _ in ()).throw(RuntimeError("fatal")),
    )
    exits = []
    monkeypatch.setattr("sys.exit", lambda code=0: exits.append(code))
    main()
    out = capsys.readouterr().out
    assert "Fatal error" in out
    assert exits == [1]


def test_main_gui_launches_without_loading_settings(monkeypatch):
    parser = SimpleNamespace(
        parse_args=lambda: SimpleNamespace(
            gui=True,
            config="cfg.py",
            no_trading_cards=False,
            max_games=None,
            no_cache=False,
            max_checks=None,
            skip_failures=False,
            keep_completed_drops=False,
            dry_run=False,
        )
    )

    launched = {}

    monkeypatch.setattr(main_module, "create_parser", lambda: parser)
    monkeypatch.setattr(
        "steam_idle_bot.gui.launch_gui",
        lambda config_path=None: launched.setdefault("path", config_path),
    )

    main()

    assert launched["path"] == "cfg.py"


def test_dunder_main_executes_main(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(main_module, "main", lambda: called.__setitem__("n", 1))
    runpy.run_module("steam_idle_bot.__main__", run_name="__main__")
    assert called["n"] == 1


def test_dunder_main_import_does_not_execute(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(main_module, "main", lambda: called.__setitem__("n", 1))
    __import__("steam_idle_bot.__main__")
    assert called["n"] == 0


def test_init_without_badge_service():
    bot = _build_bot(make_settings(filter_completed_card_drops=False))
    assert bot.game_manager.badge_service is None


def test_show_session_report_ignores_capture_errors(monkeypatch, tmp_path):
    bot = _build_bot()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main_module, "time", SimpleNamespace(strftime=lambda fmt: "20260101_010101"))
    monkeypatch.setattr(bot, "_capture_final_cards", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    bot._show_session_report()


def test_cleanup_without_client():
    bot = _build_bot()
    bot.client = None
    bot._cleanup()


class patch_sys_exit:
    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.calls = []

    def __enter__(self):
        def _exit(code=0):
            self.calls.append(code)
            raise SystemExit(code)

        self.monkeypatch.setattr("sys.exit", _exit)
        return self.calls

    def __exit__(self, exc_type, exc, tb):
        return False
