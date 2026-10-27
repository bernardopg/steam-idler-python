"""WebSocket connection to a Steam Connection Manager (CM).

One :class:`CMConnection` is one TLS WebSocket to ``wss://<cm>/cmsocket/``. A
daemon reader thread parses every incoming packet (unpacking ``Multi``),
resolves pending service-method jobs by ``jobid_target`` and dispatches the
rest to registered handlers. Sends are serialized with a lock, so the bot
thread, the heartbeat thread and handlers may all send concurrently.

The transport is injectable (``connect_fn``) so tests can drive a fake CM.
"""

from __future__ import annotations

__all__ = ["CMConnection", "ServiceResponse", "fetch_cm_servers"]

import contextlib
import itertools
import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from ...utils.exceptions import SteamConnectionError
from .messages import (
    CLIENT_HELLO,
    EMPTY,
    HEARTBEAT,
    JOB_ID_NONE,
    PROTOCOL_VERSION,
    EMsg,
    EResult,
    Packet,
    PacketError,
    build_packet,
    parse_packet,
    unpack_multi,
)
from .protobuf import ProtobufDecodeError, Schema, decode

logger = logging.getLogger(__name__)

CM_DIRECTORY_URL = "https://api.steampowered.com/ISteamDirectory/GetCMListForConnect/v1/"
_MAX_FRAME_BYTES = 16 * 1024 * 1024
_SERVERS_TO_TRY = 5
_MIN_HEARTBEAT_SECONDS = 5.0


class WebSocketLike(Protocol):
    def send(self, message: bytes) -> None: ...

    def recv(self, timeout: float | None = None) -> bytes | str: ...

    def close(self) -> None: ...


ConnectFn = Callable[[str, float], WebSocketLike]
PacketHandler = Callable[[Packet], None]


@dataclass
class ServiceResponse:
    """Result of a unified service method call."""

    eresult: int
    body: dict[str, Any]
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return self.eresult == EResult.OK


@dataclass
class _PendingJob:
    event: threading.Event
    packet: Packet | None = None


def _default_connect(url: str, timeout: float) -> WebSocketLike:
    from websockets.sync.client import connect

    # Steam frames are binary protobuf; per-message deflate buys nothing.
    # legacy=True: we own the connection's lifetime (the reader thread outlives
    # this call), which is websockets' documented opt-in for that.
    return connect(url, open_timeout=timeout, close_timeout=5, max_size=_MAX_FRAME_BYTES, compression=None, user_agent_header=None, legacy=True)


def fetch_cm_servers(session: requests.Session | None = None, *, timeout: float = 10.0) -> list[str]:
    """Return WebSocket CM endpoints (``host:port``), least loaded first."""
    http = session or requests
    try:
        response = http.get(CM_DIRECTORY_URL, params={"cellid": "0", "cmtype": "websockets", "realm": "steamglobal"}, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise SteamConnectionError(f"Could not fetch the Steam CM server list: {exc}") from exc

    servers = payload.get("response", {}).get("serverlist") or []
    usable = [server for server in servers if isinstance(server, dict) and server.get("type") == "websockets" and server.get("endpoint") and server.get("realm", "steamglobal") == "steamglobal"]
    usable.sort(key=lambda server: float(server.get("wtd_load", server.get("load", 0)) or 0))
    endpoints = [str(server["endpoint"]) for server in usable]
    if not endpoints:
        raise SteamConnectionError("Steam returned an empty CM server list")
    return endpoints


class CMConnection:
    """A single WebSocket session with a Steam CM."""

    def __init__(
        self,
        *,
        connect_fn: ConnectFn | None = None,
        server_list_fn: Callable[[], list[str]] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._connect_fn = connect_fn or _default_connect
        self._server_list_fn = server_list_fn or (lambda: fetch_cm_servers(timeout=timeout))
        self._timeout = timeout
        self._ws: WebSocketLike | None = None
        self._send_lock = threading.Lock()
        self._jobs_lock = threading.Lock()
        self._jobs: dict[int, _PendingJob] = {}
        # Job ids only need to be unique per connection; start at a random point.
        self._job_ids = itertools.count(secrets.randbelow(1 << 48) + 1)
        self._handlers: dict[int, list[PacketHandler]] = {}
        self._closed = threading.Event()
        self._heartbeat_stop = threading.Event()
        self._reader: threading.Thread | None = None
        self.endpoint: str | None = None
        self.steam_id = 0
        self.session_id = 0
        self.logged_on = False
        self.on_disconnect: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._closed.is_set()

    def connect(self) -> str:
        """Connect to the first reachable CM and send ``ClientHello``."""
        servers = self._server_list_fn()[:_SERVERS_TO_TRY]
        last_error: Exception | None = None
        for endpoint in servers:
            url = f"wss://{endpoint}/cmsocket/"
            try:
                ws = self._connect_fn(url, self._timeout)
            except Exception as exc:  # noqa: BLE001 - any transport failure means "try the next CM"
                logger.debug("CM %s unreachable: %s", endpoint, exc)
                last_error = exc
                continue
            self._ws = ws
            self._closed.clear()
            self.endpoint = endpoint
            self._reader = threading.Thread(target=self._read_loop, name=f"steam-cm-reader-{endpoint}", daemon=True)
            self._reader.start()
            self.send(EMsg.ClientHello, CLIENT_HELLO, {"protocol_version": PROTOCOL_VERSION})
            logger.debug("Connected to Steam CM %s", endpoint)
            return endpoint
        raise SteamConnectionError(f"Could not connect to any Steam CM server ({last_error or 'no servers'})")

    def close(self) -> None:
        """Close the socket; pending jobs fail and handlers stop firing."""
        self._heartbeat_stop.set()
        ws = self._ws
        if ws is not None:
            with contextlib.suppress(Exception):
                ws.close()
        self._mark_closed()
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=5)

    def _mark_closed(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self.logged_on = False
        self._heartbeat_stop.set()
        with self._jobs_lock:
            for job in self._jobs.values():
                job.event.set()
        callback = self.on_disconnect
        if callback is not None:
            with contextlib.suppress(Exception):
                callback()

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def _base_header(self) -> dict[str, Any]:
        header: dict[str, Any] = {}
        if self.steam_id:
            header["steamid"] = self.steam_id
        if self.session_id:
            header["client_sessionid"] = self.session_id
        return header

    def send(self, emsg: int, schema: Schema, body: dict[str, Any], header: dict[str, Any] | None = None) -> None:
        if not self.connected or self._ws is None:
            raise SteamConnectionError("Not connected to a Steam CM")
        merged = self._base_header()
        merged.update(header or {})
        data = build_packet(emsg, merged, schema, body)
        try:
            with self._send_lock:
                self._ws.send(data)
        except Exception as exc:  # noqa: BLE001 - surface every transport error the same way
            self._mark_closed()
            raise SteamConnectionError(f"Steam CM connection lost while sending: {exc}") from exc

    def call_service(
        self,
        method: str,
        request_schema: Schema,
        request: dict[str, Any],
        response_schema: Schema,
        *,
        authed: bool = False,
        timeout: float | None = None,
    ) -> ServiceResponse:
        """Call a unified service method (e.g. ``Authentication.PollAuthSessionStatus#1``)."""
        job_id = next(self._job_ids)
        job = _PendingJob(event=threading.Event())
        with self._jobs_lock:
            self._jobs[job_id] = job
        header: dict[str, Any] = {"jobid_source": job_id, "target_job_name": method}
        emsg = EMsg.ServiceMethodCallFromClient if authed else EMsg.ServiceMethodCallFromClientNonAuthed
        if not authed:
            # Unauthenticated calls are sent anonymously, as the official client does.
            header.update({"steamid": 0, "client_sessionid": 0, "realm": 1})
        try:
            self.send(emsg, request_schema, request, header)
            if not job.event.wait(timeout or self._timeout):
                raise SteamConnectionError(f"Steam did not answer {method} in time")
        finally:
            with self._jobs_lock:
                self._jobs.pop(job_id, None)

        packet = job.packet
        if packet is None:
            raise SteamConnectionError(f"Steam CM connection closed during {method}")
        if packet.emsg == EMsg.DestJobFailed:
            return ServiceResponse(EResult.Fail, {}, "job failed at destination")
        try:
            body = decode(response_schema, packet.body) if packet.body else {}
        except ProtobufDecodeError as exc:
            raise SteamConnectionError(f"Malformed response to {method}: {exc}") from exc
        return ServiceResponse(packet.eresult, body, str(packet.header.get("error_message", "")))

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------

    def on(self, emsg: int, handler: PacketHandler) -> None:
        self._handlers.setdefault(int(emsg), []).append(handler)

    def wait_for(self, emsg: int, timeout: float, *, after_register: Callable[[], None] | None = None) -> Packet | None:
        """Block until a packet of type *emsg* arrives (or timeout/close).

        Pass the request as *after_register* when the reply may arrive
        immediately: it runs only once the listener is in place, so a fast
        reply cannot slip past it.
        """
        received: list[Packet] = []
        event = threading.Event()

        def _capture(packet: Packet) -> None:
            if not received:
                received.append(packet)
                event.set()

        self.on(emsg, _capture)
        deadline = time.monotonic() + timeout
        try:
            if after_register is not None:
                after_register()
            while not event.is_set() and not self._closed.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                event.wait(min(remaining, 0.2))
        finally:
            with contextlib.suppress(ValueError):
                self._handlers[int(emsg)].remove(_capture)
        return received[0] if received else None

    def _read_loop(self) -> None:
        ws = self._ws
        try:
            while ws is not None and not self._closed.is_set():
                data = ws.recv()
                if isinstance(data, str):
                    continue
                self.handle_frame(data)
        except Exception as exc:  # noqa: BLE001 - the socket died; report and stop
            if not self._closed.is_set():
                logger.debug("Steam CM connection closed: %s", exc)
        finally:
            self._mark_closed()

    def handle_frame(self, data: bytes) -> None:
        """Parse one frame (public for tests) and dispatch its packet(s)."""
        try:
            packet = parse_packet(data)
            if packet.emsg == EMsg.Multi:
                for inner in unpack_multi(packet.body):
                    self.handle_frame(inner)
                return
        except PacketError as exc:
            logger.warning("Ignoring malformed packet from Steam CM: %s", exc)
            return

        job_id = int(packet.header.get("jobid_target", JOB_ID_NONE))
        if job_id != JOB_ID_NONE:
            with self._jobs_lock:
                job = self._jobs.get(job_id)
            if job is not None:
                job.packet = packet
                job.event.set()
                return

        for handler in list(self._handlers.get(packet.emsg, ())):
            try:
                handler(packet)
            except Exception:  # noqa: BLE001 - a buggy handler must not kill the reader
                logger.exception("Steam CM handler for EMsg %s failed", packet.emsg)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def start_heartbeat(self, interval_seconds: float) -> None:
        """Send ``ClientHeartBeat`` every *interval_seconds* until closed."""
        self._heartbeat_stop.clear()
        interval = max(float(interval_seconds), _MIN_HEARTBEAT_SECONDS)

        def _beat() -> None:
            while not self._heartbeat_stop.wait(interval):
                try:
                    self.send(EMsg.ClientHeartBeat, HEARTBEAT, {})
                except SteamConnectionError:
                    return

        threading.Thread(target=_beat, name="steam-cm-heartbeat", daemon=True).start()

    def send_logoff(self) -> None:
        with contextlib.suppress(SteamConnectionError):
            self.send(EMsg.ClientLogOff, EMPTY, {})
