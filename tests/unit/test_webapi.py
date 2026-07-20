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
