"""Optional native idling backend powered by the local steam-utility project."""

from __future__ import annotations

__all__ = ["SteamUtilityError", "SteamUtilityBridge", "SteamUtilityIdleClient"]

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
            f" for {self._username}" if self._username else "",
        )
        return True

    def start_idling(self, game_ids: list[int]) -> bool:
        """Start or refresh long-running native idling processes."""
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

        started_all = True
        for app_id in desired:
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
        """Stop all native idling processes."""
        for app_id in list(self._processes):
            self._stop_process(app_id)
        return True

    def refresh_games(self, game_ids: list[int]) -> bool:
        """Apply a new idling set."""
        return self.start_idling(game_ids)

    def is_connected(self) -> bool:
        """Consider the backend healthy while all managed processes are alive."""
        if not self._processes:
            return False
        return all(process.poll() is None for process in self._processes.values())

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
