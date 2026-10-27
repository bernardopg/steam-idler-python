"""A scripted fake Steam CM speaking the real wire protocol, for native-backend tests.

``FakeSteam`` plays the server side: it parses every packet the client sends
with the production codec and answers with real binary frames (optionally
wrapped in a gzip ``Multi``), so the tests exercise framing, job routing,
authentication and logon end to end without the network.
"""

from __future__ import annotations

import base64
import gzip
import json
import queue
import struct
import time
from dataclasses import dataclass, field
from typing import Any

from steam_idle_bot.steam.native import messages as m
from steam_idle_bot.steam.native.cm import CMConnection
from steam_idle_bot.steam.native.protobuf import Schema, decode, encode

STEAM_ID = 76561198000000001
_CLOSE = object()


def make_jwt(claims: dict[str, Any]) -> str:
    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'EdDSA', 'typ': 'JWT'})}.{part(claims)}.c2lnbmF0dXJl"


def refresh_token(*, sub: int = STEAM_ID, days: float = 200, aud: list[str] | None = None) -> str:
    return make_jwt({"iss": "steam", "sub": str(sub), "aud": aud or ["client", "web", "renew", "derive"], "exp": int(time.time() + days * 86400)})


class FakeWebSocket:
    """In-memory WebSocket; ``recv`` blocks until the fake server pushes a frame."""

    def __init__(self, server: FakeSteam) -> None:
        self.server = server
        self.inbox: queue.Queue[Any] = queue.Queue()
        self.closed = False

    def send(self, message: bytes) -> None:
        if self.closed:
            raise ConnectionError("socket closed")
        self.server.handle(self, message)

    def recv(self, timeout: float | None = None) -> bytes:
        item = self.inbox.get(timeout=timeout)
        if item is _CLOSE:
            raise ConnectionError("closed by server")
        return item

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.inbox.put(_CLOSE)

    def push(self, frame: bytes) -> None:
        self.inbox.put(frame)


@dataclass
class FakeSteam:
    """Server-side script. Tweak the attributes to steer each scenario."""

    password: str = "hunter2"
    confirmations: list[int] = field(default_factory=lambda: [m.EAuthSessionGuardType.DeviceCode])
    guard_code: str = "AB12C"
    polls_before_approval: int = 0
    logon_results: list[int] = field(default_factory=list)  # consumed one per logon; default OK
    begin_eresult: int = m.EResult.OK
    rsa_key: Any = None  # Cryptodome RSA key; when None a static fake key is served
    issued_refresh_token: str = field(default_factory=refresh_token)
    renewed_refresh_token: str | None = None
    access_token: str = "ACCESS.TOKEN.VALUE"
    wrap_in_multi: bool = False
    unreachable_endpoints: set[str] = field(default_factory=set)
    # recorded traffic
    sent: list[m.Packet] = field(default_factory=list)
    games_played: list[list[int]] = field(default_factory=list)
    submitted_codes: list[str] = field(default_factory=list)
    decrypted_passwords: list[str] = field(default_factory=list)
    logon_tokens: list[str] = field(default_factory=list)
    sockets: list[FakeWebSocket] = field(default_factory=list)
    connected_endpoints: list[str] = field(default_factory=list)
    _guard_ok: bool = False
    _polls: int = 0

    # -- transport -------------------------------------------------------

    def connect(self, url: str, timeout: float) -> FakeWebSocket:
        endpoint = url.removeprefix("wss://").removesuffix("/cmsocket/")
        if endpoint in self.unreachable_endpoints:
            raise OSError(f"{endpoint} unreachable")
        self.connected_endpoints.append(endpoint)
        ws = FakeWebSocket(self)
        self.sockets.append(ws)
        return ws

    def connection(self, servers: list[str] | None = None) -> CMConnection:
        return CMConnection(connect_fn=self.connect, server_list_fn=lambda: list(servers or ["cm1.example:443", "cm2.example:443"]), timeout=2.0)

    def reply(self, ws: FakeWebSocket, emsg: int, header: dict[str, Any], schema: Schema, body: dict[str, Any]) -> None:
        frame = m.build_packet(emsg, header, schema, body)
        if self.wrap_in_multi:
            payload = struct.pack("<I", len(frame)) + frame
            multi = encode(m.MULTI, {"size_unzipped": len(payload), "message_body": gzip.compress(payload)})
            frame = m.build_packet(m.EMsg.Multi, {}, m.EMPTY, {}) + multi
        ws.push(frame)

    def push_event(self, emsg: int, schema: Schema, body: dict[str, Any], ws: FakeWebSocket | None = None) -> None:
        self.reply(ws or self.sockets[-1], emsg, {}, schema, body)

    # -- protocol --------------------------------------------------------

    def handle(self, ws: FakeWebSocket, data: bytes) -> None:
        packet = m.parse_packet(data)
        self.sent.append(packet)
        emsg = packet.emsg
        if emsg in (m.EMsg.ServiceMethodCallFromClientNonAuthed, m.EMsg.ServiceMethodCallFromClient):
            self._service(ws, packet)
        elif emsg == m.EMsg.ClientLogon:
            self._logon(ws, packet)
        elif emsg == m.EMsg.ClientGamesPlayedWithDataBlob:
            body = decode(m.CLIENT_GAMES_PLAYED, packet.body)
            self.games_played.append([int(game["game_id"]) for game in body.get("games_played", [])])

    def _respond(self, ws: FakeWebSocket, packet: m.Packet, eresult: int, schema: Schema, body: dict[str, Any]) -> None:
        self.reply(ws, m.EMsg.ServiceMethodResponse, {"jobid_target": packet.header["jobid_source"], "eresult": int(eresult)}, schema, body)

    def _service(self, ws: FakeWebSocket, packet: m.Packet) -> None:
        method = packet.header.get("target_job_name")
        if method == "Authentication.GetPasswordRSAPublicKey#1":
            modulus, exponent = (format(self.rsa_key.n, "x"), format(self.rsa_key.e, "x")) if self.rsa_key is not None else ("c" * 256, "010001")
            body = {"publickey_mod": modulus, "publickey_exp": exponent, "timestamp": 12345}
            self._respond(ws, packet, m.EResult.OK, m.AUTH_GET_RSA_RESPONSE, body)
        elif method == "Authentication.BeginAuthSessionViaCredentials#1":
            request = decode(m.AUTH_BEGIN_REQUEST, packet.body)
            if self.rsa_key is not None:
                from Cryptodome.Cipher import PKCS1_v1_5

                plain = PKCS1_v1_5.new(self.rsa_key).decrypt(base64.b64decode(request["encrypted_password"]), None)
                self.decrypted_passwords.append(plain.decode())
                if plain.decode() != self.password:
                    self._respond(ws, packet, m.EResult.InvalidPassword, m.AUTH_BEGIN_RESPONSE, {})
                    return
            self._guard_ok = not ({m.EAuthSessionGuardType.DeviceCode, m.EAuthSessionGuardType.EmailCode} & set(self.confirmations))
            body = {
                "client_id": 777,
                "request_id": b"req",
                "interval": 0.01,
                "steamid": STEAM_ID,
                "allowed_confirmations": [{"confirmation_type": int(kind)} for kind in self.confirmations],
            }
            self._respond(ws, packet, self.begin_eresult, m.AUTH_BEGIN_RESPONSE, body if self.begin_eresult == m.EResult.OK else {})
        elif method == "Authentication.UpdateAuthSessionWithSteamGuardCode#1":
            request = decode(m.AUTH_UPDATE_GUARD_REQUEST, packet.body)
            self.submitted_codes.append(request["code"])
            if request["code"] == self.guard_code:
                self._guard_ok = True
                self._respond(ws, packet, m.EResult.OK, m.EMPTY, {})
            else:
                mismatch = m.EResult.TwoFactorCodeMismatch if request["code_type"] == m.EAuthSessionGuardType.DeviceCode else m.EResult.InvalidLoginAuthCode
                self._respond(ws, packet, mismatch, m.EMPTY, {})
        elif method == "Authentication.PollAuthSessionStatus#1":
            self._polls += 1
            done = self._guard_ok and self._polls > self.polls_before_approval
            body = {"refresh_token": self.issued_refresh_token, "account_name": "steamuser", "new_guard_data": "GUARD.TOKEN"} if done else {}
            self._respond(ws, packet, m.EResult.OK, m.AUTH_POLL_RESPONSE, body)
        elif method == "Authentication.GenerateAccessTokenForApp#1":
            request = decode(m.AUTH_GENERATE_TOKEN_REQUEST, packet.body)
            body = {"access_token": self.access_token}
            if request.get("renewal_type") == m.TOKEN_RENEWAL_ALLOW and self.renewed_refresh_token:
                body["refresh_token"] = self.renewed_refresh_token
            self._respond(ws, packet, m.EResult.OK, m.AUTH_GENERATE_TOKEN_RESPONSE, body)
        else:
            self.reply(ws, m.EMsg.DestJobFailed, {"jobid_target": packet.header["jobid_source"]}, m.EMPTY, {})

    def _logon(self, ws: FakeWebSocket, packet: m.Packet) -> None:
        body = decode(m.CLIENT_LOGON, packet.body)
        self.logon_tokens.append(body.get("access_token", ""))
        eresult = self.logon_results.pop(0) if self.logon_results else m.EResult.OK
        header = {"steamid": packet.header.get("steamid", 0), "client_sessionid": 4242} if eresult == m.EResult.OK else {}
        self.reply(ws, m.EMsg.ClientLogOnResponse, header, m.CLIENT_LOGON_RESPONSE, {"eresult": int(eresult), "heartbeat_seconds": 9})

    # -- assertions helpers ---------------------------------------------

    def sent_emsgs(self) -> list[int]:
        return [packet.emsg for packet in self.sent]

    def service_calls(self) -> list[str]:
        return [str(packet.header.get("target_job_name")) for packet in self.sent if packet.header.get("target_job_name")]
