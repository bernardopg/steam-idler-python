"""FastAPI backend serving the React web UI and the bot control API.

Endpoints:
- GET  /api/status         → live snapshot (account, session, per-game stats)
- GET  /api/settings       → current Settings (password masked)
- PUT  /api/settings       → validate + persist to .env
- POST /api/bot/start      → start the bot worker ({"dry_run": bool})
- POST /api/bot/stop       → request a graceful stop
- POST /api/auth-code      → deliver a Steam Guard code ({"code": str})
- POST /api/stop-app-ids   → maintenance: stop steam-utility idles ({"app_ids": [..]})
- GET  /api/report         → last session report text
- WS   /api/ws             → init payload, then log/status/report/auth events + snapshots

The built frontend (frontend/dist) is served at /; run `pnpm build` in
frontend/ (or ./run-web.sh, which does it on demand).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from ..config.settings import Settings, _parse_int_list
from .controller import BotController

_REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DIST = _REPO_ROOT / "frontend" / "dist"

_MASK = "********"
_WS_POLL_SECONDS = 0.3
_WS_SNAPSHOT_EVERY = 4  # polls between snapshot pushes (~1.2s)


class StartRequest(BaseModel):
    dry_run: bool = False


class AuthCodeRequest(BaseModel):
    code: str


class StopAppIdsRequest(BaseModel):
    app_ids: list[int]


def _load_current_settings() -> Settings | None:
    try:
        return Settings()
    except Exception:
        return None


def _settings_to_dto(settings: Settings) -> dict[str, Any]:
    data = settings.model_dump()
    data["password"] = _MASK if settings.password else ""
    cookies = data.get("steam_web_cookies") or {}
    if isinstance(cookies, dict):
        data["steam_web_cookies"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return data


def _coerce_settings_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Tolerate CSV strings for list fields and a masked/blank password."""
    data = dict(payload)
    for list_field in ("game_app_ids", "exclude_app_ids"):
        if isinstance(data.get(list_field), str):
            data[list_field] = _parse_int_list(data[list_field])

    if data.get("password") in ("", _MASK):
        current = _load_current_settings()
        if current is None:
            raise HTTPException(status_code=422, detail="Password required: no saved credentials to reuse")
        data["password"] = current.password
    return data


def create_app(controller: BotController | None = None) -> FastAPI:
    controller = controller or BotController()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        controller.stop()

    app = FastAPI(title="Steam Idle Bot", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.controller = controller

    # ------------------------------------------------------------------
    # REST
    # ------------------------------------------------------------------

    @app.get("/api/status")
    def get_status() -> dict[str, Any]:
        return controller.snapshot()

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        settings = _load_current_settings()
        if settings is None:
            return {"configured": False, "settings": None}
        return {"configured": True, "settings": _settings_to_dto(settings)}

    @app.put("/api/settings")
    def put_settings(payload: dict[str, Any]) -> dict[str, Any]:
        data = _coerce_settings_payload(payload)
        try:
            settings = Settings(**data)
        except ValidationError as exc:
            errors = [{"field": ".".join(str(part) for part in err["loc"]), "message": err["msg"]} for err in exc.errors()]
            raise HTTPException(status_code=422, detail=errors) from exc
        target = settings.save_to_env_file(Path(".env"))
        return {"saved": True, "path": str(target)}

    @app.post("/api/bot/start")
    def start_bot(request: StartRequest) -> dict[str, Any]:
        if controller.is_running:
            raise HTTPException(status_code=409, detail="Bot is already running")
        settings = _load_current_settings()
        if settings is None:
            raise HTTPException(status_code=422, detail="Settings are incomplete; save valid credentials first")
        controller.start(settings, dry_run=request.dry_run)
        return {"started": True, "dry_run": request.dry_run}

    @app.post("/api/bot/stop")
    def stop_bot() -> dict[str, Any]:
        if not controller.is_running:
            raise HTTPException(status_code=409, detail="Bot is not running")
        controller.stop()
        return {"stopping": True}

    @app.post("/api/auth-code")
    def auth_code(request: AuthCodeRequest) -> dict[str, Any]:
        if not controller.provide_auth_code(request.code):
            raise HTTPException(status_code=409, detail="No pending Steam Guard request")
        return {"delivered": True}

    @app.post("/api/stop-app-ids")
    def stop_app_ids(request: StopAppIdsRequest) -> dict[str, Any]:
        if controller.is_running:
            raise HTTPException(status_code=409, detail="Only available when the bot is stopped")
        settings = _load_current_settings()
        if settings is None:
            raise HTTPException(status_code=422, detail="Settings are incomplete")
        from ..main import _stop_app_ids as run_stop  # deferred: heavy steam imports

        status = run_stop(settings, request.app_ids)
        return {"status": status}

    @app.get("/api/report")
    def get_report() -> dict[str, Any]:
        return {"report": controller.last_report}

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    @app.websocket("/api/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        _, cursor = controller.events_since(0)  # skip history; backlog covers logs
        await websocket.send_json(
            {
                "type": "init",
                "snapshot": controller.snapshot(),
                "logs": controller.log_backlog(),
                "report": controller.last_report,
                "auth_pending": controller.pending_auth is not None,
            }
        )
        polls = 0
        try:
            while True:
                events, cursor = controller.events_since(cursor)
                for event in events:
                    await websocket.send_json(event)
                polls += 1
                if polls % _WS_SNAPSHOT_EVERY == 0:
                    await websocket.send_json({"type": "snapshot", "snapshot": controller.snapshot()})
                await asyncio.sleep(_WS_POLL_SECONDS)
        except WebSocketDisconnect:
            pass

    # ------------------------------------------------------------------
    # Frontend
    # ------------------------------------------------------------------

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    else:

        @app.get("/")
        def frontend_missing() -> JSONResponse:
            return JSONResponse(
                {
                    "error": "Frontend not built",
                    "hint": "Run `pnpm install && pnpm build` inside frontend/ or use ./run-web.sh",
                }
            )

    return app


def launch_web(host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = True) -> None:
    """Run the web UI server (blocking)."""
    import threading
    import webbrowser

    import uvicorn

    app = create_app()
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
