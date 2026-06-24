"""Additional tests for steam_utility backend — covers uncovered paths."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.steam_utility import (
    SteamUtilityBridge,
    SteamUtilityError,
    SteamUtilityIdleClient,
    _extract_idle_app_id,
)


def make_settings(**overrides) -> Settings:
    base = {"username": "user", "password": "pass", "idling_backend": "steam_utility"}
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
        self._project_root = Path("/tmp/steam-utility")
        self.report = {"activeSteamId": 76561198000000000, "activeAccountName": "bot-user"}
        self.spawned: list[int] = []
        self.processes: dict[int, FakeProcess] = {}
        self.idle_pids: dict[int, list[int]] = {}

    @property
    def project_root(self):
        return self._project_root

    @project_root.setter
    def project_root(self, value):
        self._project_root = value

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


# ---------------------------------------------------------------------------
# SteamUtilityBridge — run_json_command
# ---------------------------------------------------------------------------


class TestRunJsonCommand:
    def test_success(self):
        bridge = SteamUtilityBridge(configured_path=None)
        bridge._project_root = Path("/tmp/steam-utility")  # skip filesystem discovery
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = json.dumps({"ok": True})
        completed.stderr = ""
        with patch("subprocess.run", return_value=completed):
            result = bridge.run_json_command("state-report")
        assert result == {"ok": True}

    def test_nonzero_exit_code(self):
        bridge = SteamUtilityBridge(configured_path=None)
        bridge._project_root = Path("/tmp/steam-utility")  # skip filesystem discovery
        completed = MagicMock()
        completed.returncode = 1
        completed.stderr = "error msg"
        completed.stdout = ""
        with patch("subprocess.run", return_value=completed), pytest.raises(SteamUtilityError, match="failed with code 1"):
            bridge.run_json_command("bad-cmd")

    def test_empty_stdout(self):
        bridge = SteamUtilityBridge(configured_path=None)
        bridge._project_root = Path("/tmp/steam-utility")  # skip filesystem discovery
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = ""
        completed.stderr = ""
        with patch("subprocess.run", return_value=completed), pytest.raises(SteamUtilityError, match="no JSON output"):
            bridge.run_json_command("empty-cmd")

    def test_invalid_json(self):
        bridge = SteamUtilityBridge(configured_path=None)
        bridge._project_root = Path("/tmp/steam-utility")  # skip filesystem discovery
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "not json {{{"
        completed.stderr = ""
        with patch("subprocess.run", return_value=completed), pytest.raises(SteamUtilityError, match="invalid JSON"):
            bridge.run_json_command("bad-json")


# ---------------------------------------------------------------------------
# SteamUtilityBridge — get_state_report
# ---------------------------------------------------------------------------


class TestGetStateReport:
    def test_invalid_payload(self):
        bridge = SteamUtilityBridge(configured_path=None)
        with patch.object(bridge, "run_json_command", return_value="not a dict"), pytest.raises(SteamUtilityError, match="invalid payload"):
            bridge.get_state_report()


# ---------------------------------------------------------------------------
# SteamUtilityBridge — _candidate_paths / _normalize_candidate
# ---------------------------------------------------------------------------


class TestCandidatePaths:
    def test_includes_configured_path(self):
        bridge = SteamUtilityBridge(configured_path="/my/custom/path")
        candidates = bridge._candidate_paths()
        assert Path("/my/custom/path") in candidates

    def test_deduplicates(self):
        bridge = SteamUtilityBridge(configured_path=None)
        candidates = bridge._candidate_paths()
        paths = [str(c) for c in candidates]
        assert len(paths) == len(set(paths))


class TestNormalizeCandidate:
    def test_csproj_file(self, tmp_path):
        csproj = tmp_path / "src" / "SteamUtility.Cli" / "SteamUtility.Cli.csproj"
        csproj.parent.mkdir(parents=True)
        csproj.write_text("<project/>")
        result = SteamUtilityBridge._normalize_candidate(csproj)
        assert result == tmp_path

    def test_cli_directory(self, tmp_path):
        cli_dir = tmp_path / "src" / "SteamUtility.Cli"
        cli_dir.mkdir(parents=True)
        result = SteamUtilityBridge._normalize_candidate(cli_dir)
        assert result == tmp_path

    def test_regular_directory(self, tmp_path):
        result = SteamUtilityBridge._normalize_candidate(tmp_path)
        assert result == tmp_path

    def test_nonexistent_path(self, tmp_path):
        result = SteamUtilityBridge._normalize_candidate(tmp_path / "nope")
        assert result is None


# ---------------------------------------------------------------------------
# SteamUtilityIdleClient — stop_idling / refresh_games / reconnect / logout
# ---------------------------------------------------------------------------


class TestClientLifecycle:
    def test_stop_idling(self, monkeypatch):
        monkeypatch.setattr("steam_idle_bot.steam.steam_utility.time.sleep", lambda s: None)
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        client.start_idling([570])
        assert client.stop_idling() is True
        assert client._processes == {}
        assert client._adopted_pids == {}

    def test_refresh_games(self, monkeypatch):
        monkeypatch.setattr("steam_idle_bot.steam.steam_utility.time.sleep", lambda s: None)
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        client.start_idling([570])
        assert client.refresh_games([730]) is True
        assert 570 not in client._processes
        assert 730 in client._processes

    def test_reconnect(self, monkeypatch):
        monkeypatch.setattr("steam_idle_bot.steam.steam_utility.time.sleep", lambda s: None)
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        assert client.reconnect() is True

    def test_logout(self, monkeypatch):
        monkeypatch.setattr("steam_idle_bot.steam.steam_utility.time.sleep", lambda s: None)
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        client.start_idling([570])
        assert client.logout() is True
        assert client._processes == {}


# ---------------------------------------------------------------------------
# SteamUtilityIdleClient — sleep, client property
# ---------------------------------------------------------------------------


class TestClientMisc:
    def test_sleep(self, monkeypatch):
        called = []
        monkeypatch.setattr("steam_idle_bot.steam.steam_utility.time.sleep", lambda s: called.append(s))
        SteamUtilityIdleClient.sleep(2.5)
        assert called == [2.5]

    def test_client_property(self):
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        assert client.client is None


# ---------------------------------------------------------------------------
# SteamUtilityIdleClient — is_connected edge cases
# ---------------------------------------------------------------------------


class TestIsConnected:
    def test_no_processes_no_adopted(self):
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        assert client.is_connected() is False

    def test_managed_process_dead(self, monkeypatch):
        monkeypatch.setattr("steam_idle_bot.steam.steam_utility.time.sleep", lambda s: None)
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        client.start_idling([570])
        # Simulate process death
        client._processes[570] = FakeProcess(running=False)
        assert client.is_connected() is False

    def test_adopted_pid_dead(self, monkeypatch):
        bridge = FakeBridge()
        bridge.idle_pids = {570: [111]}
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        client._adopted_pids = {570: 111}
        with patch.object(SteamUtilityIdleClient, "_pid_alive", return_value=False):
            assert client.is_connected() is False


# ---------------------------------------------------------------------------
# SteamUtilityIdleClient — _stop_process with timeout
# ---------------------------------------------------------------------------


class TestStopProcess:
    def test_terminate_then_kill_on_timeout(self, monkeypatch):
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        proc = FakeProcess(running=True)
        client._processes[570] = proc

        def fake_wait(timeout=None):
            if proc.terminated and not proc.killed:
                raise subprocess.TimeoutExpired(cmd="dotnet", timeout=timeout)
            proc.running = False
            return 0

        proc.wait = fake_wait
        client._stop_process(570)
        assert proc.killed is True
        assert 570 not in client._processes

    def test_stop_nonexistent(self):
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        client._stop_process(999)  # no crash

    def test_stop_already_exited(self):
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        proc = FakeProcess(running=False)
        client._processes[570] = proc
        client._stop_process(570)
        assert 570 not in client._processes
        assert proc.terminated is False


# ---------------------------------------------------------------------------
# SteamUtilityIdleClient — _stop_pid with ProcessLookupError
# ---------------------------------------------------------------------------


class TestStopPid:
    def test_suppresses_process_lookup_error(self):
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        with patch("os.kill", side_effect=ProcessLookupError):
            client._stop_pid(99999)  # no crash

    def test_suppresses_permission_error(self):
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        with patch("os.kill", side_effect=PermissionError):
            client._stop_pid(99999)  # no crash


# ---------------------------------------------------------------------------
# SteamUtilityIdleClient — start_idling with adopted pid no longer alive
# ---------------------------------------------------------------------------


class TestStartIdlingAdoptedDead:
    def test_respawns_when_adopted_pid_dies(self, monkeypatch):
        monkeypatch.setattr("steam_idle_bot.steam.steam_utility.time.sleep", lambda s: None)
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        client._adopted_pids = {570: 111}

        call_count = [0]

        def selective_alive(pid, proc_root="/proc"):
            call_count[0] += 1
            # First call: adopted pid 111 is dead; subsequent calls: alive
            return call_count[0] > 1

        with patch.object(SteamUtilityIdleClient, "_pid_alive", side_effect=selective_alive):
            assert client.start_idling([570]) is True
        assert bridge.spawned == [570]


# ---------------------------------------------------------------------------
# SteamUtilityIdleClient — login failure paths
# ---------------------------------------------------------------------------


class TestLoginFailures:
    def test_login_fails_on_bridge_error(self):
        bridge = FakeBridge()
        bridge.get_state_report = MagicMock(side_effect=SteamUtilityError("broken"))
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        assert client.login() is False

    def test_login_fails_without_steam_id(self):
        bridge = FakeBridge()
        bridge.report = {}
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        assert client.login() is False

    def test_login_fails_with_null_steam_id(self):
        bridge = FakeBridge()
        bridge.report = {"activeSteamId": None, "activeAccountName": None}
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        assert client.login() is False


# ---------------------------------------------------------------------------
# SteamUtilityIdleClient — get_web_session without cookies
# ---------------------------------------------------------------------------


class TestGetWebSession:
    def test_returns_none_without_cookies(self):
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        assert client.get_web_session() is None

    def test_returns_none_with_empty_cookies(self):
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        assert client.get_web_session(cookies={}) is None


# ---------------------------------------------------------------------------
# _extract_idle_app_id edge cases
# ---------------------------------------------------------------------------


class TestExtractIdleAppId:
    def test_no_idle_command(self):
        assert _extract_idle_app_id(["SteamUtility.Cli", "status"]) is None

    def test_idle_without_number(self):
        assert _extract_idle_app_id(["SteamUtility.Cli", "idle", "abc"]) is None

    def test_empty_args(self):
        assert _extract_idle_app_id([]) is None


# ---------------------------------------------------------------------------
# SteamUtilityBridge — find_idle_pids with unreadable cmdline
# ---------------------------------------------------------------------------


class TestFindIdlePidsEdgeCases:
    def test_skips_unreadable_cmdline(self, tmp_path):
        proc_dir = tmp_path / "12345"
        proc_dir.mkdir()
        # Don't write cmdline -> OSError on read
        bridge = SteamUtilityBridge(configured_path=None)
        pids = bridge.find_idle_pids(str(tmp_path))
        assert pids == {}

    def test_non_proc_directory(self, tmp_path):
        bridge = SteamUtilityBridge(configured_path=None)
        assert bridge.find_idle_pids(str(tmp_path / "nonexistent")) == {}


# ---------------------------------------------------------------------------
# SteamUtilityIdleClient — start_idling spawn failure
# ---------------------------------------------------------------------------


class TestStartIdlingSpawnFailure:
    def test_spawn_failure_sets_started_all_false(self, monkeypatch):
        monkeypatch.setattr("steam_idle_bot.steam.steam_utility.time.sleep", lambda s: None)
        bridge = FakeBridge()
        bridge.spawn_idle_process = MagicMock(side_effect=SteamUtilityError("spawn fail"))
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        assert client.start_idling([570]) is False


# ---------------------------------------------------------------------------
# SteamUtilityIdleClient — reconcile with no existing idles
# ---------------------------------------------------------------------------


class TestReconcileNoIdles:
    def test_returns_empty_report(self):
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        report = client.reconcile_existing_idles([570])
        assert report == {"reused": [], "stopped": [], "untouched": []}


# ---------------------------------------------------------------------------
# SteamUtilityIdleClient — start_idling deduplicates game_ids
# ---------------------------------------------------------------------------


class TestStartIdlingDedup:
    def test_deduplicates_game_ids(self, monkeypatch):
        monkeypatch.setattr("steam_idle_bot.steam.steam_utility.time.sleep", lambda s: None)
        bridge = FakeBridge()
        client = SteamUtilityIdleClient(make_settings(), bridge=bridge)
        client.start_idling([570, 570, 730])
        assert bridge.spawned == [570, 730]
