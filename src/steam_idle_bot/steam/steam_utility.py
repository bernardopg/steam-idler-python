"""Optional native idling backend powered by the local steam-utility project."""

from __future__ import annotations

__all__ = ["SteamUtilityError", "SteamUtilityBridge", "SteamUtilityIdleClient"]

import contextlib
import json
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from ..utils.redaction import mask_username

logger = logging.getLogger(__name__)


def _extract_idle_app_id(args: list[str]) -> int | None:
    """Return the app id of a steam-utility ``idle <app_id>`` invocation.

    Requires a ``SteamUtility`` marker among the args so unrelated processes
    that merely contain an ``idle`` token are not misidentified.
    """
    if not any("steamutility" in a.lower() for a in args):
        return None
    for index, arg in enumerate(args):
        if arg == "idle" and index + 1 < len(args) and args[index + 1].isdigit():
            return int(args[index + 1])
    return None


class SteamUtilityError(RuntimeError):
    """Raised when the steam-utility integration cannot be used."""


class SteamUtilityBridge:
    """Adapter for invoking the local steam-utility CLI."""

    def __init__(self, configured_path: str | None = None) -> None:
        self._configured_path = configured_path
        self._project_root: Path | None = None

    @property
    def project_root(self) -> Path:
        """Return the resolved steam-utility project root."""
        if self._project_root is None:
            self._project_root = self._resolve_project_root()
        return self._project_root

    @property
    def cli_project_path(self) -> Path:
        """Return the CLI csproj used for dotnet run."""
        return self.project_root / "src" / "SteamUtility.Cli" / "SteamUtility.Cli.csproj"

    def get_state_report(self) -> dict[str, Any]:
        """Return the Steam state-report JSON payload."""
        payload = self.run_json_command("state-report")
        if not isinstance(payload, dict):
            raise SteamUtilityError("steam-utility state-report returned an invalid payload")
        return payload

    def run_json_command(self, command: str, *positionals: str) -> Any:
        """Execute a steam-utility command that emits JSON."""
        completed = subprocess.run(
            [
                "dotnet",
                "run",
                "--project",
                str(self.cli_project_path),
                "--",
                command,
                *positionals,
                "--json",
            ],
            cwd=self.project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise SteamUtilityError(f"steam-utility command {command!r} failed with code {completed.returncode}: {stderr or 'no stderr'}")

        stdout = completed.stdout.strip()
        if not stdout:
            raise SteamUtilityError(f"steam-utility command {command!r} produced no JSON output")

        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise SteamUtilityError(f"steam-utility command {command!r} returned invalid JSON: {stdout[:200]}") from exc

    def spawn_idle_process(self, app_id: int) -> subprocess.Popen[str]:
        """Launch a long-running native idling process for a single app."""
        return subprocess.Popen(
            [
                "dotnet",
                "run",
                "--project",
                str(self.cli_project_path),
                "--",
                "idle",
                str(app_id),
            ],
            cwd=self.project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def find_idle_pids(self, proc_root: str = "/proc") -> dict[int, list[int]]:
        """Map app_id -> sorted PIDs of running steam-utility idle processes.

        Scans ``/proc`` command lines; returns an empty map where ``/proc`` is
        unavailable (e.g. non-Linux), making reconciliation a no-op there.
        """
        root = Path(proc_root)
        if not root.is_dir():
            return {}

        found: dict[int, list[int]] = {}
        for entry in root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
            except OSError:
                continue
            args = [part.decode("utf-8", "replace") for part in raw.split(b"\x00") if part]
            app_id = _extract_idle_app_id(args)
            if app_id is not None:
                found.setdefault(app_id, []).append(int(entry.name))
        return {app_id: sorted(pids) for app_id, pids in found.items()}

    def _resolve_project_root(self) -> Path:
        for candidate in self._candidate_paths():
            root = self._normalize_candidate(candidate)
            if root is None:
                continue

            csproj = root / "src" / "SteamUtility.Cli" / "SteamUtility.Cli.csproj"
            if csproj.is_file():
                return root

        raise SteamUtilityError("Could not find steam-utility-multiplataform. Set STEAM_UTILITY_PATH to the repository root.")

    def _candidate_paths(self) -> list[Path]:
        candidates: list[Path] = []
        if self._configured_path:
            candidates.append(Path(self._configured_path).expanduser())

        repo_root = Path(__file__).resolve().parents[3]
        candidates.append(repo_root.parent / "steam-utility-multiplataform")
        candidates.append(Path.home() / "development" / "steam-utility-multiplataform")

        unique_candidates: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            unique_candidates.append(candidate)
        return unique_candidates

    @staticmethod
    def _normalize_candidate(path: Path) -> Path | None:
        if path.is_file() and path.name == "SteamUtility.Cli.csproj":
            return path.parents[2]

        if path.is_dir() and path.name == "SteamUtility.Cli":
            return path.parents[1]

        if path.is_dir():
            return path

        return None


class SteamUtilityIdleClient:
    """Client-compatible interface that idles via steam-utility subprocesses."""

    def __init__(self, settings: Any, bridge: SteamUtilityBridge | None = None) -> None:
        self.settings = settings
        self.bridge = bridge or SteamUtilityBridge(settings.steam_utility_path)
        self._steam_id: str | None = None
        self._username: str | None = None
        self._processes: dict[int, subprocess.Popen[str]] = {}
        # External idle PIDs adopted from a previous run instead of re-spawned.
        self._adopted_pids: dict[int, int] = {}
        self._reconciled = False

    def initialize(self) -> bool:
        """Resolve the steam-utility repository before starting."""
        try:
            project_root = self.bridge.project_root
        except SteamUtilityError as exc:
            logger.error(str(exc))
            return False

        logger.info("Using steam-utility backend from %s", project_root)
        return True

    def login(self, auth_code_provider: Any | None = None) -> bool:
        """Validate that a Steam session is already active locally."""
        del auth_code_provider
        try:
            report = self.bridge.get_state_report()
        except SteamUtilityError as exc:
            logger.error("steam-utility state-report failed: %s", exc)
            return False

        steam_id = report.get("activeSteamId") or report.get("ActiveSteamId")
        if steam_id is None:
            logger.error("steam-utility did not report an active logged-in Steam account")
            return False

        self._steam_id = str(steam_id)
        active_name = report.get("activeAccountName") or report.get("ActiveAccountName")
        self._username = str(active_name) if active_name else None
        logger.info(
            "Connected to local Steam session%s",
            f" for {mask_username(self._username)}" if self._username else "",
        )
        return True

    def reconcile_existing_idles(
        self,
        game_ids: list[int],
        *,
        proc_root: str = "/proc",
    ) -> dict[str, list[tuple[int, int]]]:
        """Adopt or deduplicate pre-existing steam-utility idles before starting.

        For each target app id already being idled by an external process (e.g. a
        previous bot run), the first PID is **reused** (adopted) and any further
        duplicates are **stopped**. Idles for non-target apps are **left
        untouched** and only reported. Returns a report keyed by
        ``reused``/``stopped``/``untouched`` mapping to ``(app_id, pid)`` tuples.
        """
        targets: list[int] = []
        seen: set[int] = set()
        for app_id in game_ids:
            if app_id not in seen:
                seen.add(app_id)
                targets.append(app_id)

        existing = self.bridge.find_idle_pids(proc_root)
        own = {process.pid for process in self._processes.values()}
        report: dict[str, list[tuple[int, int]]] = {"reused": [], "stopped": [], "untouched": []}

        for app_id in targets:
            pids = [pid for pid in existing.get(app_id, []) if pid not in own]
            if not pids:
                continue
            keep = pids[0]
            self._adopted_pids[app_id] = keep
            report["reused"].append((app_id, keep))
            for duplicate in pids[1:]:
                self._stop_pid(duplicate)
                report["stopped"].append((app_id, duplicate))

        for app_id, pids in existing.items():
            if app_id in seen:
                continue
            for pid in pids:
                if pid not in own:
                    report["untouched"].append((app_id, pid))

        if any(report.values()):
            logger.info(
                "Reconciled existing steam-utility idles: %d reused, %d duplicates stopped, %d left untouched",
                len(report["reused"]),
                len(report["stopped"]),
                len(report["untouched"]),
            )
        return report

    def start_idling(self, game_ids: list[int]) -> bool:
        """Start or refresh long-running native idling processes."""
        if not self._reconciled:
            self._reconciled = True
            with contextlib.suppress(Exception):
                self.reconcile_existing_idles(game_ids)

        desired = []
        seen: set[int] = set()
        for game_id in game_ids:
            if game_id in seen:
                continue
            seen.add(game_id)
            desired.append(game_id)

        desired_set = set(desired)
        for app_id in list(self._processes):
            if app_id not in desired_set:
                self._stop_process(app_id)
        for app_id in list(self._adopted_pids):
            if app_id not in desired_set:
                del self._adopted_pids[app_id]

        started_all = True
        for app_id in desired:
            adopted = self._adopted_pids.get(app_id)
            if adopted is not None and self._pid_alive(adopted):
                # An external idle from a previous run is already covering this app.
                continue

            process = self._processes.get(app_id)
            if process is not None and process.poll() is None:
                continue

            if process is not None:
                self._stop_process(app_id)

            try:
                new_process = self.bridge.spawn_idle_process(app_id)
            except SteamUtilityError as exc:
                logger.error("Failed to start steam-utility idler for %s: %s", app_id, exc)
                started_all = False
                continue

            time.sleep(1.0)
            if new_process.poll() is not None:
                stdout, stderr = new_process.communicate()
                logger.error(
                    "steam-utility idler for %s exited immediately: %s",
                    app_id,
                    (stderr or stdout).strip() or "no output",
                )
                started_all = False
                continue

            self._processes[app_id] = new_process
            logger.info("Started native idling for app %s", app_id)

        return started_all and self.is_connected()

    def stop_idling(self) -> bool:
        """Stop all native idling processes (adopted external idles are left running)."""
        for app_id in list(self._processes):
            self._stop_process(app_id)
        self._adopted_pids.clear()
        return True

    def refresh_games(self, game_ids: list[int]) -> bool:
        """Apply a new idling set."""
        return self.start_idling(game_ids)

    def is_connected(self) -> bool:
        """Healthy while every managed process and adopted external idle is alive."""
        if not self._processes and not self._adopted_pids:
            return False
        managed_ok = all(process.poll() is None for process in self._processes.values())
        adopted_ok = all(self._pid_alive(pid) for pid in self._adopted_pids.values())
        return managed_ok and adopted_ok

    @staticmethod
    def _pid_alive(pid: int, proc_root: str = "/proc") -> bool:
        """Return True while the PID is present (a live process)."""
        return Path(proc_root, str(pid)).exists()

    def _stop_pid(self, pid: int) -> None:
        """Terminate an external idle PID we did not spawn ourselves."""
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.kill(pid, signal.SIGTERM)
        logger.info("Stopped duplicate steam-utility idle PID %s", pid)

    def reconnect(self) -> bool:
        """Re-read the local Steam state and let the caller restart idling."""
        return self.initialize() and self.login()

    def logout(self) -> bool:
        """No explicit logout exists; just ensure children are gone."""
        return self.stop_idling()

    @staticmethod
    def sleep(seconds: float) -> None:
        """Sleep using the standard clock."""
        time.sleep(seconds)

    def get_web_session(
        self,
        username: str | None = None,
        password: str | None = None,
        cookies: dict[str, str] | list[dict[str, Any]] | None = None,
    ) -> Any | None:
        """Build a Steam web session only from configured browser cookies."""
        del username, password
        if not cookies:
            logger.warning("steam-utility backend cannot derive Steam web cookies automatically; configure STEAM_WEB_COOKIES for badge scraping")
            return None

        from .client import SteamClientWrapper

        return SteamClientWrapper._build_web_session_from_cookies(cookies)

    @property
    def steam_id(self) -> str | None:
        """Active SteamID reported by steam-utility."""
        return self._steam_id

    @property
    def username(self) -> str | None:
        """Active account name reported by steam-utility."""
        return self._username

    @property
    def client(self) -> None:
        """Mirror the python backend property for compatibility."""
        return None

    def _stop_process(self, app_id: int) -> None:
        process = self._processes.pop(app_id, None)
        if process is None:
            return

        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        logger.info("Stopped native idling for app %s", app_id)
