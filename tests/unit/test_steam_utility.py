"""Tests for the optional steam-utility backend."""

from __future__ import annotations

from pathlib import Path

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.main import build_steam_client
from steam_idle_bot.steam.steam_utility import (
    SteamUtilityError,
    SteamUtilityIdleClient,
)


def make_settings(**overrides) -> Settings:
    base = {
        "username": "user",
        "password": "pass",
        "idling_backend": "steam_utility",
    }
    base.update(overrides)
    return Settings(**base)


class FakeProcess:
    def __init__(self, *, running: bool = True, stdout: str = "", stderr: str = ""):
        self.running = running
        self.stdout_text = stdout
        self.stderr_text = stderr
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self.running else 1

    def communicate(self):
        return self.stdout_text, self.stderr_text

    def terminate(self):
        self.terminated = True
        self.running = False

    def wait(self, timeout=None):
        del timeout
        self.running = False
        return 0

    def kill(self):
        self.killed = True
        self.running = False


class FakeBridge:
    def __init__(self):
        self.project_root = Path("/tmp/steam-utility")
        self.report = {
            "activeSteamId": 76561198000000000,
            "activeAccountName": "bot-user",
        }
        self.spawned: list[int] = []
        self.processes: dict[int, FakeProcess] = {}

    def get_state_report(self):
        return dict(self.report)

    def spawn_idle_process(self, app_id: int):
        self.spawned.append(app_id)
        process = self.processes.get(app_id, FakeProcess())
        self.processes[app_id] = process
        return process


class BrokenBridge(FakeBridge):
    @property
    def project_root(self):
        raise SteamUtilityError("missing")

    @project_root.setter
    def project_root(self, value):
        del value


def test_build_steam_client_uses_steam_utility_backend():
    client = build_steam_client(make_settings())
    assert isinstance(client, SteamUtilityIdleClient)


def test_initialize_returns_false_when_bridge_is_missing():
    client = SteamUtilityIdleClient(make_settings(), bridge=BrokenBridge())
    assert client.initialize() is False


def test_login_reads_active_steam_user_from_state_report():
    bridge = FakeBridge()
    client = SteamUtilityIdleClient(make_settings(), bridge=bridge)

    assert client.initialize() is True
    assert client.login() is True
    assert client.steam_id == "76561198000000000"
    assert client.username == "bot-user"


def test_login_reads_pascal_case_state_report_fields():
    bridge = FakeBridge()
    bridge.report = {
        "ActiveSteamId": 76561198000000000,
        "ActiveAccountName": "bot-user",
    }
    client = SteamUtilityIdleClient(make_settings(), bridge=bridge)

    assert client.login() is True
    assert client.steam_id == "76561198000000000"
    assert client.username == "bot-user"


def test_login_fails_without_active_steam_user():
    bridge = FakeBridge()
    bridge.report = {"activeSteamId": None}
    client = SteamUtilityIdleClient(make_settings(), bridge=bridge)

    assert client.login() is False


def test_start_idling_reuses_running_processes_and_stops_removed(monkeypatch):
    monkeypatch.setattr("steam_idle_bot.steam.steam_utility.time.sleep", lambda seconds: None)

    bridge = FakeBridge()
    client = SteamUtilityIdleClient(make_settings(), bridge=bridge)

    assert client.start_idling([10, 20]) is True
    assert bridge.spawned == [10, 20]
    assert client.is_connected() is True

    existing = bridge.processes[20]
    assert client.start_idling([20, 30]) is True
    assert bridge.spawned == [10, 20, 30]
    assert bridge.processes[20] is existing
    assert 10 not in client._processes


def test_start_idling_reports_immediate_process_exit(monkeypatch):
    monkeypatch.setattr("steam_idle_bot.steam.steam_utility.time.sleep", lambda seconds: None)

    bridge = FakeBridge()
    bridge.processes[10] = FakeProcess(running=False, stderr="boom")
    client = SteamUtilityIdleClient(make_settings(), bridge=bridge)

    assert client.start_idling([10]) is False
    assert client.is_connected() is False


def test_get_web_session_uses_configured_cookies(monkeypatch):
    bridge = FakeBridge()
    client = SteamUtilityIdleClient(make_settings(), bridge=bridge)

    monkeypatch.setattr(
        "steam_idle_bot.steam.client.SteamClientWrapper._build_web_session_from_cookies",
        staticmethod(lambda cookies: {"cookies": cookies}),
    )

    session = client.get_web_session(cookies={"sessionid": "abc"})
    assert session == {"cookies": {"sessionid": "abc"}}
