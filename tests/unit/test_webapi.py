"""Tests for the web API backend (FastAPI + BotController)."""

from __future__ import annotations

import re
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.webapi.controller import AuthCodeRequest, BotController
from steam_idle_bot.webapi.server import create_app

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def controller() -> BotController:
    return BotController()


@pytest.fixture
def client(controller: BotController) -> TestClient:
    return TestClient(create_app(controller))


@pytest.fixture
def hermetic_env(monkeypatch, tmp_path):
    """Isolate settings from the developer's real env/.env."""
    for var in ("USERNAME", "PASSWORD", "STEAM_API_KEY", "GAME_APP_IDS", "STEAM_WEB_COOKIES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# BotController
# ---------------------------------------------------------------------------


class TestController:
    def test_events_since_cursor(self, controller: BotController):
        controller._emit({"type": "log", "level": "INFO", "line": "a"})
        events, cursor = controller.events_since(0)
        assert [e["line"] for e in events] == ["a"]

        controller._emit({"type": "log", "level": "INFO", "line": "b"})
        events, cursor = controller.events_since(cursor)
        assert [e["line"] for e in events] == ["b"]

        events, _ = controller.events_since(cursor)
        assert events == []

    def test_log_backlog_only_keeps_logs(self, controller: BotController):
        controller._emit({"type": "status", "state": "running"})
        controller._emit({"type": "log", "level": "INFO", "line": "x"})
        assert [e["line"] for e in controller.log_backlog()] == ["x"]

    def test_provide_auth_code(self, controller: BotController):
        request = AuthCodeRequest(is_2fa=True, code_mismatch=False)
        controller.pending_auth = request

        assert controller.provide_auth_code("ABC12") is True
        assert request.code == "ABC12"
        assert request.event.is_set()
        assert controller.pending_auth is None
        assert controller.provide_auth_code("XYZ") is False

    def test_snapshot_idle(self, controller: BotController):
        snapshot = controller.snapshot()
        assert snapshot["status"] == "stopped"
        assert snapshot["running"] is False
        assert snapshot["games"] == []
        assert snapshot["auth_pending"] is False

    def test_snapshot_with_tracker(self, controller: BotController):
        class Info:
            name = "Dota 2"
            cards_before = 3
            cards_dropped = 1
            idle_minutes = 12.34

        class Tracker:
            session_minutes = 45.6
            games = {570: Info()}

        class Client:
            username = "user"

        class Bot:
            client = Client()
            _idle_tracker = Tracker()

        controller._bot = Bot()
        snapshot = controller.snapshot()
        assert snapshot["account"] == "user"
        assert snapshot["session_minutes"] == 45.6
        assert snapshot["cards_remaining_known"] == 2
        assert snapshot["session_drops"] == 1
        assert snapshot["games"][0] == {
            "app_id": 570,
            "name": "Dota 2",
            "cards_remaining": 2,
            "drops": 1,
            "idle_minutes": 12.3,
        }

    def test_start_rejects_when_running(self, controller: BotController):
        class FakeWorker:
            def is_alive(self) -> bool:
                return True

        controller._worker = FakeWorker()  # type: ignore[assignment]
        with pytest.raises(RuntimeError):
            controller.start(Settings(username="user", password="pass"))

    def test_stop_noop_without_bot(self, controller: BotController):
        """``stop()`` on an idle controller (``_bot is None``) is a safe no-op."""
        controller.status = "stopped"
        controller.stop()
        assert controller.status == "stopped"

    def test_stop_sets_status_and_calls_bot_stop(self, controller: BotController):
        class FakeBot:
            def __init__(self) -> None:
                self.stopped = False

            def stop(self) -> None:
                self.stopped = True

        bot = FakeBot()
        controller._bot = bot  # type: ignore[assignment]
        controller.stop()
        assert controller.status == "stopping"
        assert bot.stopped is True

    def test_stop_suppresses_bot_stop_exceptions(self, controller: BotController):
        class ExplodingBot:
            def stop(self) -> None:
                raise RuntimeError("boom")

        controller._bot = ExplodingBot()  # type: ignore[assignment]
        controller.stop()  # must not raise
        assert controller.status == "stopping"

    def test_real_dry_run_lifecycle_via_worker_thread(self, controller: BotController, hermetic_env):
        """End-to-end, no mocking of Steam internals: a real worker thread runs a
        real ``SteamIdleBot`` in dry-run mode through ``BotController._run_worker``,
        exercising thread startup, log forwarding, report emission and the
        finally-block teardown for real.
        """
        settings = Settings(
            username="tester",
            password="secret",
            filter_trading_cards=False,
            filter_completed_card_drops=False,
            use_owned_games=False,
            game_app_ids=[570],
        )

        controller.start(settings, dry_run=True)
        assert controller.is_running is True

        assert controller._worker is not None
        controller._worker.join(timeout=10)
        assert controller._worker.is_alive() is False

        assert controller.status == "stopped"
        assert controller.last_error is None
        assert controller.last_report  # a real session report was generated

        events, _ = controller.events_since(0)
        event_types = {event["type"] for event in events}
        assert {"status", "log", "finished"} <= event_types

        run_logs = list((hermetic_env / "logs" / "runs").glob("run_*.log"))
        assert run_logs, "expected a per-run transcript log under logs/runs/"

        idle_reports = list((hermetic_env / "logs").glob("idle_report_*.txt"))
        assert idle_reports, "expected a saved session report under logs/"

    def test_real_dry_run_with_steam_utility_backend_skips_auth_wiring(self, controller: BotController, hermetic_env):
        """``SteamUtilityIdleClient`` has no ``auth_code_provider`` attribute, so
        ``_run_worker`` must skip wiring it (the ``hasattr`` guard's false branch)
        while still completing the dry run and tearing down cleanly."""
        settings = Settings(
            username="tester",
            password="secret",
            idling_backend="steam_utility",
            filter_trading_cards=False,
            filter_completed_card_drops=False,
            use_owned_games=False,
            game_app_ids=[570],
        )

        controller.start(settings, dry_run=True)
        controller._worker.join(timeout=10)

        assert controller.status == "stopped"
        assert controller.last_error is None

    def test_request_auth_code_blocks_until_delivered(self, controller: BotController):
        """Real threading: the worker-side call blocks on a real ``Event`` until
        the API-side ``provide_auth_code`` unblocks it — no mocking of either."""
        results: list[str | None] = []

        def _worker() -> None:
            results.append(controller._request_auth_code(is_2fa=True, code_mismatch=False))

        thread = threading.Thread(target=_worker)
        thread.start()
        try:
            for _ in range(200):
                if controller.pending_auth is not None:
                    break
                threading.Event().wait(0.01)
            assert controller.pending_auth is not None
            assert controller.provide_auth_code("ABC12") is True
        finally:
            thread.join(timeout=5)

        assert results == ["ABC12"]
        events, _ = controller.events_since(0)
        assert any(event["type"] == "auth_request" for event in events)

    def test_snapshot_ignores_broken_tracker_without_crashing(self, controller: BotController):
        """``snapshot()`` wraps tracker access in ``suppress(Exception)`` so a
        misbehaving tracker can never break the status endpoint/WebSocket."""

        class BrokenTracker:
            @property
            def session_minutes(self):
                raise RuntimeError("tracker exploded")

        class Client:
            username = "user"

        class Bot:
            client = Client()
            _idle_tracker = BrokenTracker()

        controller._bot = Bot()  # type: ignore[assignment]
        snapshot = controller.snapshot()
        assert snapshot["account"] == "user"
        assert snapshot["session_minutes"] == 0.0
        assert snapshot["games"] == []

    def test_snapshot_with_tracker_without_known_cards(self, controller: BotController):
        """Games whose ``cards_before`` is None stay in the table but don't feed
        the ``cards_remaining_known`` aggregate (branch 217->219 / 228->231)."""

        class Info:
            name = "Mystery"
            cards_before = None
            cards_dropped = 0
            idle_minutes = 1.0

        class Tracker:
            session_minutes = 2.0
            games = {1234: Info()}

        class Bot:
            client = None
            _idle_tracker = Tracker()

        controller._bot = Bot()  # type: ignore[assignment]
        snapshot = controller.snapshot()
        assert snapshot["cards_remaining_known"] is None
        assert snapshot["games"][0]["cards_remaining"] is None
        assert snapshot["games"][0]["name"] == "Mystery"

    def test_snapshot_with_bot_without_tracker(self, controller: BotController):
        """A bot object lacking ``_idle_tracker`` yields an empty but valid
        snapshot (branch 209->231)."""

        class Bot:
            client = None

        controller._bot = Bot()  # type: ignore[assignment]
        snapshot = controller.snapshot()
        assert snapshot["games"] == []
        assert snapshot["session_minutes"] == 0.0

    def test_real_run_worker_records_last_error_on_exception(self, controller: BotController, hermetic_env, monkeypatch):
        """A real run that raises still tears down cleanly and surfaces the error."""
        settings = Settings(username="tester", password="secret")

        from steam_idle_bot.main import SteamIdleBot

        def _boom(self, dry_run: bool = False) -> None:
            raise RuntimeError("synthetic failure")

        monkeypatch.setattr(SteamIdleBot, "run", _boom)

        controller.start(settings, dry_run=True)
        controller._worker.join(timeout=10)

        assert controller.status == "error"
        assert controller.last_error == "synthetic failure"
        events, _ = controller.events_since(0)
        assert any(event["type"] == "error" for event in events)


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------


class TestApi:
    def test_status(self, client: TestClient):
        response = client.get("/api/status")
        assert response.status_code == 200
        assert response.json()["status"] == "stopped"

    def test_settings_unconfigured(self, client: TestClient, hermetic_env):
        response = client.get("/api/settings")
        assert response.status_code == 200
        assert response.json() == {"configured": False, "settings": None}

    def test_settings_save_and_mask(self, client: TestClient, hermetic_env):
        payload = {"username": "someone", "password": "secret", "game_app_ids": "570, 730"}
        response = client.put("/api/settings", json=payload)
        assert response.status_code == 200
        assert (hermetic_env / ".env").exists()

        fetched = client.get("/api/settings").json()
        assert fetched["configured"] is True
        assert fetched["settings"]["username"] == "someone"
        assert fetched["settings"]["password"] == "********"
        assert fetched["settings"]["game_app_ids"] == [570, 730]

    def test_settings_blank_password_reuses_saved(self, client: TestClient, hermetic_env):
        client.put("/api/settings", json={"username": "someone", "password": "secret"})
        response = client.put("/api/settings", json={"username": "renamed", "password": ""})
        assert response.status_code == 200

        env_text = (hermetic_env / ".env").read_text(encoding="utf-8")
        assert "renamed" in env_text
        assert "secret" in env_text

    def test_settings_blank_password_without_saved_fails(self, client: TestClient, hermetic_env):
        response = client.put("/api/settings", json={"username": "someone", "password": ""})
        assert response.status_code == 422

    def test_settings_placeholder_rejected(self, client: TestClient, hermetic_env):
        response = client.put("/api/settings", json={"username": "your_steam_username", "password": "x"})
        assert response.status_code == 422

    def test_start_without_settings(self, client: TestClient, hermetic_env):
        response = client.post("/api/bot/start", json={"dry_run": True})
        assert response.status_code == 422

    def test_stop_when_not_running(self, client: TestClient):
        response = client.post("/api/bot/stop", json={})
        assert response.status_code == 409

    def test_auth_code_without_pending(self, client: TestClient):
        response = client.post("/api/auth-code", json={"code": "ABC12"})
        assert response.status_code == 409

    def test_auth_code_delivery(self, client: TestClient, controller: BotController):
        request = AuthCodeRequest(is_2fa=True, code_mismatch=False, event=threading.Event())
        controller.pending_auth = request
        response = client.post("/api/auth-code", json={"code": "ABC12"})
        assert response.status_code == 200
        assert request.code == "ABC12"

    def test_report(self, client: TestClient, controller: BotController):
        controller.last_report = "session report"
        assert client.get("/api/report").json() == {"report": "session report"}

    def test_websocket_init(self, client: TestClient, controller: BotController):
        controller._emit({"type": "log", "level": "INFO", "line": "hello"})
        with client.websocket_connect("/api/ws") as websocket:
            message = websocket.receive_json()
        assert message["type"] == "init"
        assert message["snapshot"]["status"] == "stopped"
        assert [log["line"] for log in message["logs"]] == ["hello"]

    @pytest.mark.timeout(15)
    def test_websocket_streams_new_events_and_periodic_snapshot(self, client: TestClient, controller: BotController):
        """Real end-to-end WebSocket loop: connect, emit a live event, and stay
        connected long enough for the periodic snapshot push (every 4 polls of
        ~0.3s) to fire for real — no mocking of the asyncio loop."""
        with client.websocket_connect("/api/ws") as websocket:
            init = websocket.receive_json()
            assert init["type"] == "init"

            controller._emit({"type": "log", "level": "INFO", "line": "live-event"})

            seen_types: list[str] = []
            for _ in range(8):
                message = websocket.receive_json()
                seen_types.append(message["type"])
                if message["type"] == "log":
                    assert message["line"] == "live-event"
                if "snapshot" in seen_types and "log" in seen_types:
                    break

            assert "log" in seen_types
            assert "snapshot" in seen_types
        # Exiting the `with` block closes the socket; the server-side handler
        # must absorb the resulting WebSocketDisconnect without raising.

    def test_start_bot_conflict_when_already_running(self, client: TestClient, controller: BotController, hermetic_env):
        client.put("/api/settings", json={"username": "tester", "password": "secret"})

        class FakeWorker:
            def is_alive(self) -> bool:
                return True

        controller._worker = FakeWorker()  # type: ignore[assignment]
        response = client.post("/api/bot/start", json={"dry_run": True})
        assert response.status_code == 409

    def test_start_bot_real_dry_run_via_rest(self, client: TestClient, controller: BotController, hermetic_env):
        """Real end-to-end: save settings over REST, start a real dry-run worker
        through the API, and observe it finish through the same REST surface."""
        saved = client.put(
            "/api/settings",
            json={
                "username": "tester",
                "password": "secret",
                "filter_trading_cards": False,
                "filter_completed_card_drops": False,
                "use_owned_games": False,
                "game_app_ids": "570",
            },
        )
        assert saved.status_code == 200

        response = client.post("/api/bot/start", json={"dry_run": True})
        assert response.status_code == 200
        assert response.json() == {"started": True, "dry_run": True}

        assert controller._worker is not None
        controller._worker.join(timeout=10)

        status = client.get("/api/status").json()
        assert status["running"] is False
        assert status["status"] == "stopped"

        report = client.get("/api/report").json()
        assert report["report"] == controller.last_report
        assert report["report"]

    def test_stop_bot_success(self, client: TestClient, controller: BotController):
        class FakeWorker:
            def is_alive(self) -> bool:
                return True

        class FakeBot:
            def __init__(self) -> None:
                self.stopped = False

            def stop(self) -> None:
                self.stopped = True

        fake_bot = FakeBot()
        controller._worker = FakeWorker()  # type: ignore[assignment]
        controller._bot = fake_bot  # type: ignore[assignment]

        response = client.post("/api/bot/stop", json={})
        assert response.status_code == 200
        assert response.json() == {"stopping": True}
        assert fake_bot.stopped is True
        assert controller.status == "stopping"

    def test_stop_app_ids_endpoint_real(self, client: TestClient, hermetic_env):
        """Real call into ``main._stop_app_ids`` -> ``SteamUtilityBridge.find_idle_pids``,
        which really scans ``/proc``. No steam-utility installation is required
        because no matching idle process exists for this made-up App ID."""
        client.put("/api/settings", json={"username": "tester", "password": "secret"})

        response = client.post("/api/stop-app-ids", json={"app_ids": [999999999]})
        assert response.status_code == 200
        assert response.json() == {"status": 0}

    def test_stop_app_ids_rejected_while_running(self, client: TestClient, controller: BotController, hermetic_env):
        class FakeWorker:
            def is_alive(self) -> bool:
                return True

        controller._worker = FakeWorker()  # type: ignore[assignment]
        response = client.post("/api/stop-app-ids", json={"app_ids": [570]})
        assert response.status_code == 409

    def test_stop_app_ids_without_settings(self, client: TestClient, hermetic_env):
        response = client.post("/api/stop-app-ids", json={"app_ids": [570]})
        assert response.status_code == 422

    def test_lifespan_shutdown_stops_controller(self, controller: BotController):
        """The app's lifespan context calls ``controller.stop()`` on shutdown."""

        class FakeBot:
            def __init__(self) -> None:
                self.stopped = False

            def stop(self) -> None:
                self.stopped = True

        fake_bot = FakeBot()
        controller._bot = fake_bot  # type: ignore[assignment]

        with TestClient(create_app(controller)):
            pass

        assert fake_bot.stopped is True

    def test_frontend_missing_branch_serves_json_error(self, controller: BotController, monkeypatch):
        """When ``frontend/dist`` is absent (e.g. a fresh CI checkout), the root
        route must serve the actionable JSON error instead of mounting statics."""
        import steam_idle_bot.webapi.server as server_module

        monkeypatch.setattr(server_module, "FRONTEND_DIST", Path("/nonexistent-frontend-dist"))
        app = server_module.create_app(controller)

        with TestClient(app) as plain_client:
            response = plain_client.get("/")

        assert response.status_code == 200
        payload = response.json()
        assert payload["error"] == "Frontend not built"
        assert "npm install" in payload["hint"]

    def test_launch_web_runs_uvicorn_without_browser(self, monkeypatch):
        from steam_idle_bot.webapi.server import launch_web

        captured: dict = {}

        def _fake_run(app, **kwargs):
            captured["app"] = app
            captured.update(kwargs)

        monkeypatch.setattr("uvicorn.run", _fake_run)
        launch_web(port=8799, open_browser=False)

        assert captured["host"] == "127.0.0.1"
        assert captured["port"] == 8799
        assert captured["log_level"] == "warning"
        assert captured["app"] is not None

    def test_launch_web_schedules_browser_open(self, monkeypatch):
        """With ``open_browser=True`` the URL is opened once, after a short delay;
        the Timer is executed eagerly so no dangling thread outlives the test."""
        import threading as threading_module
        import webbrowser as webbrowser_module

        from steam_idle_bot.webapi.server import launch_web

        opened: list[str] = []
        monkeypatch.setattr(webbrowser_module, "open", lambda url: opened.append(url) or True)
        monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: None)

        class ImmediateTimer:
            def __init__(self, interval, function, args=None, kwargs=None):
                self.function = function

            def start(self) -> None:
                self.function()

        monkeypatch.setattr(threading_module, "Timer", ImmediateTimer)
        launch_web(host="127.0.0.1", port=8123, open_browser=True)

        assert opened == ["http://127.0.0.1:8123"]


# ---------------------------------------------------------------------------
# Parity: the React settings form must cover every Settings field
# ---------------------------------------------------------------------------


def _settings_fields() -> set[str]:
    return set(Settings.model_fields.keys())


def _frontend_form_keys() -> set[str]:
    source = (ROOT / "frontend" / "src" / "views" / "SettingsView.tsx").read_text(encoding="utf-8")
    return set(re.findall(r"key: '([a-z_0-9]+)'", source))


def test_frontend_form_covers_every_settings_field() -> None:
    assert _settings_fields() - _frontend_form_keys() == set()


def test_settings_dto_exposes_every_field(client: TestClient, hermetic_env) -> None:
    client.put("/api/settings", json={"username": "someone", "password": "secret"})
    dto = client.get("/api/settings").json()["settings"]
    assert _settings_fields() - set(dto.keys()) == set()
