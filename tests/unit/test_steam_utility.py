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
    def __init__(self, *, running: bool = True, stdout: str = "", stderr: str = "", pid: int = 1000):
        self.running = running
        self.stdout_text = stdout
        self.stderr_text = stderr
        self.pid = pid
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
        self.idle_pids: dict[int, list[int]] = {}

    def find_idle_pids(self, proc_root="/proc"):
        del proc_root
        return {app_id: list(pids) for app_id, pids in self.idle_pids.items()}

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


def test_login_masks_account_name_in_logs(caplog):
    bridge = FakeBridge()
    client = SteamUtilityIdleClient(make_settings(), bridge=bridge)

    with caplog.at_level("INFO"):
        assert client.login() is True

    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "bot-user" not in messages
    assert "bot***r" in messages


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


def test_extract_idle_app_id_requires_marker():
    from steam_idle_bot.steam.steam_utility import _extract_idle_app_id

    assert _extract_idle_app_id(["dotnet", "run", "SteamUtility.Cli", "idle", "570"]) == 570
    # Missing steam-utility marker -> ignored.
    assert _extract_idle_app_id(["python", "idle", "570"]) is None
    # 'idle' present but no numeric app id following.
    assert _extract_idle_app_id(["SteamUtility.Cli", "idle"]) is None


def test_find_idle_pids_scans_proc(tmp_path):
    from steam_idle_bot.steam.steam_utility import SteamUtilityBridge

    def write_cmdline(pid, args):
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"\x00".join(a.encode() for a in args) + b"\x00")

    write_cmdline(111, ["dotnet", "run", "--project", "x/SteamUtility.Cli", "--", "idle", "570"])
    write_cmdline(112, ["dotnet", "run", "--project", "x/SteamUtility.Cli", "--", "idle", "570"])
    write_cmdline(222, ["dotnet", "run", "--project", "x/SteamUtility.Cli", "--", "idle", "730"])
    write_cmdline(333, ["bash"])  # unrelated
    (tmp_path / "kernel").mkdir()  # non-numeric entry ignored

    bridge = SteamUtilityBridge(configured_path=None)
    pids = bridge.find_idle_pids(str(tmp_path))
    assert pids == {570: [111, 112], 730: [222]}


def test_find_idle_pids_returns_empty_without_proc(tmp_path):
    from steam_idle_bot.steam.steam_utility import SteamUtilityBridge

    bridge = SteamUtilityBridge(configured_path=None)
    assert bridge.find_idle_pids(str(tmp_path / "nope")) == {}


def test_reconcile_reuses_first_stops_dupes_and_reports_untouched(monkeypatch):
    bridge = FakeBridge()
    bridge.idle_pids = {570: [111, 112], 730: [222]}
    client = SteamUtilityIdleClient(make_settings(), bridge=bridge)

    stopped: list[int] = []
    monkeypatch.setattr(client, "_stop_pid", stopped.append)

    report = client.reconcile_existing_idles([570, 570])  # duplicate target collapses

    assert report["reused"] == [(570, 111)]
    assert report["stopped"] == [(570, 112)]
    assert report["untouched"] == [(730, 222)]
    assert client._adopted_pids == {570: 111}
    assert stopped == [112]


def test_start_idling_skips_spawn_for_adopted_alive_pid(monkeypatch):
    bridge = FakeBridge()
    bridge.idle_pids = {570: [111]}
    client = SteamUtilityIdleClient(make_settings(), bridge=bridge)

    monkeypatch.setattr(SteamUtilityIdleClient, "_pid_alive", staticmethod(lambda pid, proc_root="/proc": True))

    assert client.start_idling([570]) is True
    # External idle adopted -> no new process spawned.
    assert bridge.spawned == []
    assert client._adopted_pids == {570: 111}
    assert client.is_connected() is True
