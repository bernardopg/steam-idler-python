"""CMConnection transport behaviour and the refresh-token session store."""

from __future__ import annotations

import json
import os
import threading
import time
from unittest.mock import MagicMock

import pytest
import requests
from _native_fakes import FakeSteam, refresh_token

from steam_idle_bot.steam.native import messages as m
from steam_idle_bot.steam.native.cm import CMConnection, fetch_cm_servers
from steam_idle_bot.steam.native.session_store import NativeSessionStore, refresh_token_problem
from steam_idle_bot.utils.exceptions import SteamConnectionError

# ---------------------------------------------------------------------------
# CM directory
# ---------------------------------------------------------------------------


def _directory_response(servers):
    response = MagicMock()
    response.json.return_value = {"response": {"serverlist": servers, "success": True}}
    return response


def test_fetch_cm_servers_filters_and_sorts_by_load():
    http = MagicMock()
    http.get.return_value = _directory_response(
        [
            {"endpoint": "busy:443", "type": "websockets", "realm": "steamglobal", "wtd_load": 80},
            {"endpoint": "tcp:27017", "type": "netfilter", "realm": "steamglobal", "wtd_load": 1},
            {"endpoint": "china:443", "type": "websockets", "realm": "steamchina", "wtd_load": 1},
            {"endpoint": "idle:443", "type": "websockets", "realm": "steamglobal", "wtd_load": 5},
            "garbage",
        ]
    )
    assert fetch_cm_servers(http) == ["idle:443", "busy:443"]
    assert http.get.call_args.kwargs["params"]["cmtype"] == "websockets"


def test_fetch_cm_servers_errors():
    http = MagicMock()
    http.get.side_effect = requests.ConnectionError("offline")
    with pytest.raises(SteamConnectionError, match="server list"):
        fetch_cm_servers(http)
    http.get.side_effect = None
    http.get.return_value = _directory_response([])
    with pytest.raises(SteamConnectionError, match="empty"):
        fetch_cm_servers(http)


# ---------------------------------------------------------------------------
# CMConnection
# ---------------------------------------------------------------------------


def test_connect_skips_unreachable_cm_and_sends_hello():
    steam = FakeSteam(unreachable_endpoints={"cm1.example:443"})
    connection = steam.connection()
    assert connection.connect() == "cm2.example:443"
    assert steam.sent_emsgs() == [m.EMsg.ClientHello]
    assert m.decode_jwt_claims  # module import sanity
    connection.close()
    assert not connection.connected


def test_connect_fails_when_every_cm_is_down():
    steam = FakeSteam(unreachable_endpoints={"cm1.example:443", "cm2.example:443"})
    with pytest.raises(SteamConnectionError, match="any Steam CM"):
        steam.connection().connect()


@pytest.mark.parametrize("wrap_in_multi", [False, True])
def test_call_service_routes_response_by_job_id(wrap_in_multi):
    steam = FakeSteam(wrap_in_multi=wrap_in_multi)
    connection = steam.connection()
    connection.connect()
    response = connection.call_service("Authentication.GetPasswordRSAPublicKey#1", m.AUTH_GET_RSA_REQUEST, {"account_name": "x"}, m.AUTH_GET_RSA_RESPONSE)
    assert response.ok and response.body["publickey_exp"] == "010001"
    request = steam.sent[-1]
    assert request.emsg == m.EMsg.ServiceMethodCallFromClientNonAuthed
    assert request.header["realm"] == 1 and request.header["steamid"] == 0
    connection.close()


def test_authed_call_carries_session_identity():
    steam = FakeSteam()
    connection = steam.connection()
    connection.connect()
    connection.steam_id, connection.session_id = 76561198000000001, 99
    connection.call_service("Authentication.GenerateAccessTokenForApp#1", m.AUTH_GENERATE_TOKEN_REQUEST, {}, m.AUTH_GENERATE_TOKEN_RESPONSE, authed=True)
    request = steam.sent[-1]
    assert request.emsg == m.EMsg.ServiceMethodCallFromClient
    assert (request.header["steamid"], request.header["client_sessionid"]) == (76561198000000001, 99)
    connection.close()


def test_unknown_method_returns_dest_job_failed_as_fail():
    steam = FakeSteam()
    connection = steam.connection()
    connection.connect()
    response = connection.call_service("Nope.Nothing#1", m.EMPTY, {}, m.EMPTY)
    assert response.eresult == m.EResult.Fail and not response.ok
    connection.close()


def test_call_service_times_out_and_fails_on_close():
    steam = FakeSteam()
    steam._service = lambda ws, packet: None  # server never answers
    connection = steam.connection()
    connection.connect()
    with pytest.raises(SteamConnectionError, match="in time"):
        connection.call_service("Authentication.PollAuthSessionStatus#1", m.EMPTY, {}, m.EMPTY, timeout=0.05)

    threading.Timer(0.05, connection.close).start()
    with pytest.raises(SteamConnectionError, match="closed"):
        connection.call_service("Authentication.PollAuthSessionStatus#1", m.EMPTY, {}, m.EMPTY, timeout=2)


def test_send_when_disconnected_raises_and_server_close_triggers_callback():
    steam = FakeSteam()
    connection = steam.connection()
    with pytest.raises(SteamConnectionError, match="Not connected"):
        connection.send(m.EMsg.ClientHello, m.CLIENT_HELLO, {})

    connection.connect()
    disconnected = threading.Event()
    connection.on_disconnect = disconnected.set
    connection.logged_on = True
    steam.sockets[-1].close()  # server hangs up
    assert disconnected.wait(2)
    assert not connection.connected and not connection.logged_on


def test_handlers_survive_errors_and_malformed_frames(caplog):
    steam = FakeSteam()
    connection = steam.connection()
    connection.connect()
    seen: list[int] = []
    connection.on(m.EMsg.ClientLoggedOff, lambda packet: 1 / 0)
    connection.on(m.EMsg.ClientLoggedOff, lambda packet: seen.append(packet.emsg))
    connection.handle_frame(b"\x00")  # malformed: logged and ignored
    steam.push_event(m.EMsg.ClientLoggedOff, m.CLIENT_LOGGED_OFF, {"eresult": 6})
    deadline = time.monotonic() + 2
    while not seen and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen == [m.EMsg.ClientLoggedOff]
    assert "malformed packet" in caplog.text
    assert connection.connected
    connection.close()


def test_wait_for_times_out_and_returns_none():
    steam = FakeSteam()
    connection = steam.connection()
    connection.connect()
    assert connection.wait_for(m.EMsg.ClientLogOnResponse, 0.05) is None
    connection.close()


def test_heartbeat_sends_until_closed(monkeypatch):
    monkeypatch.setattr("steam_idle_bot.steam.native.cm._MIN_HEARTBEAT_SECONDS", 0.01)
    steam = FakeSteam()
    connection = steam.connection()
    connection.connect()
    connection.start_heartbeat(0)
    deadline = time.monotonic() + 2
    while steam.sent_emsgs().count(m.EMsg.ClientHeartBeat) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert steam.sent_emsgs().count(m.EMsg.ClientHeartBeat) >= 2
    connection.close()
    beats = steam.sent_emsgs().count(m.EMsg.ClientHeartBeat)
    time.sleep(0.05)
    assert steam.sent_emsgs().count(m.EMsg.ClientHeartBeat) == beats


def test_default_connect_uses_binary_settings(monkeypatch):
    captured = {}

    def fake_connect(url, **kwargs):
        captured.update(kwargs, url=url)
        return MagicMock()

    monkeypatch.setattr("websockets.sync.client.connect", fake_connect)
    from steam_idle_bot.steam.native.cm import _default_connect

    _default_connect("wss://cm/cmsocket/", 3)
    assert captured["url"] == "wss://cm/cmsocket/"
    assert captured["compression"] is None and captured["open_timeout"] == 3
    assert captured["legacy"] is True  # we own the connection lifetime; no deprecation warning
    assert captured["max_size"] >= 16 * 1024 * 1024


def test_cmconnection_default_server_list_uses_directory(monkeypatch):
    calls = []
    monkeypatch.setattr("steam_idle_bot.steam.native.cm.fetch_cm_servers", lambda timeout: calls.append(timeout) or ["x:1"])
    connection = CMConnection(connect_fn=lambda url, timeout: (_ for _ in ()).throw(OSError("down")), timeout=4)
    with pytest.raises(SteamConnectionError):
        connection.connect()
    assert calls == [4]


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------


def test_store_round_trip_is_private_and_keyed_case_insensitively(tmp_path):
    store = NativeSessionStore(tmp_path / "nested" / "session.json")
    assert store.get("User") is None
    token = refresh_token()
    store.save("User", 76561198000000001, token, "GUARD")
    assert (os.stat(store.path).st_mode & 0o777) == 0o600

    session = store.get("user")
    assert session is not None
    assert (session.account_name, session.steam_id, session.refresh_token, session.guard_data) == ("user", 76561198000000001, token, "GUARD")
    assert session.expires_at and session.expires_at > time.time()

    store.save("USER", 76561198000000001, refresh_token(days=100))  # no guard passed: previous kept
    assert store.get_guard_data("user") == "GUARD"

    store.forget_token("user")
    assert store.get("user") is None
    assert store.get_guard_data("user") == "GUARD"  # machine token survives
    store.forget_token("user")  # idempotent
    store.forget_token("someone-else")


def test_store_tolerates_corrupt_files_and_tightens_permissions(tmp_path, caplog):
    path = tmp_path / "session.json"
    path.write_text("{not json", encoding="utf-8")
    os.chmod(path, 0o644)
    store = NativeSessionStore(path)
    assert store.get("x") is None
    assert (os.stat(path).st_mode & 0o777) == 0o600
    assert "readable by other users" in caplog.text
    assert "unreadable" in caplog.text

    path.write_text(json.dumps({"accounts": {"x": {"steam_id": "abc", "refresh_token": 5}}}), encoding="utf-8")
    assert store.get("x") is None
    path.write_text(json.dumps(["wrong shape"]), encoding="utf-8")
    assert store.get("x") is None and store.get_guard_data("x") is None


def test_refresh_token_problem():
    assert refresh_token_problem(refresh_token()) is None
    assert refresh_token_problem("garbage") == "not a JWT"
    assert refresh_token_problem(refresh_token(aud=["web"])) == "token is not valid for the Steam client"
    assert refresh_token_problem(refresh_token(days=0.01)) == "token expired"
    from _native_fakes import make_jwt

    assert refresh_token_problem(make_jwt({"aud": "client", "sub": "abc"})) == "token has no SteamID"
    assert refresh_token_problem(make_jwt({"aud": "client", "sub": "1"})) is None
