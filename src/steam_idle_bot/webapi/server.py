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

The built frontend is served at /: a wheel ships it under ``webapi/static``;
a source checkout uses frontend/dist (run `npm run build` in frontend/, or
./run-web.sh, which does it on demand).

The API has no login: it is meant for the local machine only. A guard rejects
requests whose ``Host`` is not a loopback name (DNS rebinding) and mutating
requests or WebSocket handshakes coming from another origin (CSRF and
cross-site WebSocket hijacking). Secrets are masked in ``GET /api/settings``
and reused when the client sends the mask back unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.types import ASGIApp, Receive, Scope, Send

from ..config.settings import Settings, _parse_int_list
from .controller import BotController

_PACKAGED_DIST = Path(__file__).resolve().parent / "static"
_REPO_ROOT = Path(__file__).resolve().parents[3]
# Installed wheels carry the build in webapi/static; source checkouts use frontend/dist.
FRONTEND_DIST = _PACKAGED_DIST if (_PACKAGED_DIST / "index.html").is_file() else _REPO_ROOT / "frontend" / "dist"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_MASK = "********"
# Secrets other than the password: masked on GET, kept when the mask comes back.
_SECRET_FIELDS = ("steam_api_key", "steam_web_cookies")
_WS_POLL_SECONDS = 0.3
_WS_SNAPSHOT_EVERY = 4  # polls between snapshot pushes (~1.2s)


class StartRequest(BaseModel):
    dry_run: bool = False


class AuthCodeRequest(BaseModel):
    code: str


class StopAppIdsRequest(BaseModel):
    app_ids: list[int] = Field(min_length=1, max_length=64)


def _hostname(netloc: str) -> str:
    """Return the lowercase host of a ``host[:port]`` value (IPv6 brackets removed)."""
    return (urlsplit(f"//{netloc}").hostname or "").lower()


class LocalOriginGuard:
    """ASGI middleware that keeps the API reachable from the local UI only.

    - ``Host`` must name an allowed host, which defeats DNS rebinding: a page
      on ``evil.example`` that re-resolves to 127.0.0.1 still sends its own
      name as ``Host``.
    - Mutating requests and WebSocket handshakes must not come from another
      origin: a present ``Origin`` must equal the ``Host`` the request was
      sent to, and ``Sec-Fetch-Site: cross-site`` is refused.
    """

    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str]) -> None:
        self.app = app
        self.allowed_hosts = frozenset(host.lower().strip("[]") for host in allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope.get("headers", [])}
        reason = self._rejection_reason(scope, headers)
        if reason is None:
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": reason})
            return
        response = JSONResponse({"detail": reason}, status_code=403)
        await response(scope, receive, send)

    def _rejection_reason(self, scope: Scope, headers: dict[str, str]) -> str | None:
        host = headers.get("host", "")
        if _hostname(host) not in self.allowed_hosts:
            return "Host not allowed: the web UI only answers on localhost"

        needs_same_origin = scope["type"] == "websocket" or scope.get("method", "GET") not in _SAFE_METHODS
        if not needs_same_origin:
            return None
        if headers.get("sec-fetch-site") == "cross-site":
            return "Cross-site request refused"
        origin = headers.get("origin")
        if origin is not None and urlsplit(origin).netloc.lower() != host.lower():
            return "Cross-origin request refused"
        return None


def _load_current_settings() -> Settings | None:
    try:
        return Settings()
    except Exception:
        return None


def _settings_to_dto(settings: Settings) -> dict[str, Any]:
    data = settings.model_dump()
    data["password"] = _MASK if settings.password else ""
    for secret in _SECRET_FIELDS:
        data[secret] = _MASK if data.get(secret) else ""
    return data


def _coerce_settings_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Tolerate CSV strings for list fields and a masked/blank password."""
    data = dict(payload)
    for list_field in ("game_app_ids", "exclude_app_ids"):
        if isinstance(data.get(list_field), str):
            data[list_field] = _parse_int_list(data[list_field])

    current: Settings | None = None
    if data.get("password") in (None, "", _MASK):
        current = _load_current_settings()
        if current is None:
            raise HTTPException(status_code=422, detail=[{"field": "password", "message": "Password required: no saved credentials to reuse"}])
        data["password"] = current.password

    for secret in _SECRET_FIELDS:
        if data.get(secret) == _MASK:
            current = current or _load_current_settings()
            data[secret] = getattr(current, secret) if current is not None else None
    return data


def create_app(controller: BotController | None = None, *, allowed_hosts: Iterable[str] = LOOPBACK_HOSTS) -> FastAPI:
    controller = controller or BotController()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        controller.stop()

    app = FastAPI(title="Steam Idle Bot", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.controller = controller
    app.add_middleware(LocalOriginGuard, allowed_hosts=allowed_hosts)

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
                "auth_request": controller.pending_auth_payload(),
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
                    "hint": "Run `npm ci && npm run build` inside frontend/ or use ./run-web.sh",
                }
            )

    return app


def launch_web(host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = True) -> None:
    """Run the web UI server (blocking).

    The API has no authentication, so binding to a non-loopback address only
    widens who can reach the port; the Host guard still answers only to the
    bind address and loopback names.
    """
    import threading
    import webbrowser

    import uvicorn

    allowed_hosts = set(LOOPBACK_HOSTS)
    if host not in ("0.0.0.0", "::"):
        allowed_hosts.add(host)
    app = create_app(allowed_hosts=allowed_hosts)
    browse_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{browse_host}:{port}"
    print(f"Steam Idle Bot web UI: {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
