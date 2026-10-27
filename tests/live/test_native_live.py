"""Opt-in checks of the native backend against the real Steam network.

Skipped unless ``STEAM_IDLE_LIVE_TESTS=1``. They use no account: an anonymous
CM logon and an unauthenticated ``IAuthenticationService`` call are enough to
prove the transport, framing, protobuf codec and job routing still match what
Valve's servers speak. Run them after protocol changes:

    STEAM_IDLE_LIVE_TESTS=1 uv run pytest -q tests/live
"""

from __future__ import annotations

import os
import time

import pytest

from steam_idle_bot.steam.native import messages as m
from steam_idle_bot.steam.native.cm import CMConnection, fetch_cm_servers
from steam_idle_bot.steam.native.crypto import encrypt_password
from steam_idle_bot.steam.native.protobuf import decode

pytestmark = pytest.mark.skipif(os.environ.get("STEAM_IDLE_LIVE_TESTS") != "1", reason="set STEAM_IDLE_LIVE_TESTS=1 to hit the real Steam network")

ANONYMOUS_USER_STEAM_ID = (1 << 56) | (10 << 52)  # universe Public, type AnonUser


@pytest.fixture
def connection():
    conn = CMConnection(timeout=15)
    conn.connect()
    yield conn
    conn.close()


def test_directory_lists_websocket_cms():
    servers = fetch_cm_servers()
    assert servers and all(":" in server for server in servers)


def test_rsa_key_service_call(connection):
    response = connection.call_service("Authentication.GetPasswordRSAPublicKey#1", m.AUTH_GET_RSA_REQUEST, {"account_name": "steamidlebotprobe"}, m.AUTH_GET_RSA_RESPONSE)
    assert response.ok
    assert len(response.body["publickey_mod"]) >= 256 and response.body["timestamp"] > 0
    assert encrypt_password("probe", response.body["publickey_mod"], response.body["publickey_exp"])


def test_anonymous_logon_and_heartbeat(connection):
    request = {"protocol_version": m.PROTOCOL_VERSION, "client_os_type": m.OS_TYPE_LINUX_UNKNOWN, "client_language": "english", "machine_id": m.machine_id_for("anonymous")}
    packet = connection.wait_for(
        m.EMsg.ClientLogOnResponse,
        20,
        after_register=lambda: connection.send(m.EMsg.ClientLogon, m.CLIENT_LOGON, request, {"steamid": ANONYMOUS_USER_STEAM_ID, "client_sessionid": 0}),
    )
    assert packet is not None
    response = decode(m.CLIENT_LOGON_RESPONSE, packet.body)
    assert response["eresult"] == m.EResult.OK
    connection.steam_id = packet.header["steamid"]
    connection.session_id = packet.header["client_sessionid"]
    connection.logged_on = True
    connection.start_heartbeat(response.get("heartbeat_seconds", 9))
    time.sleep(1)
    assert connection.connected
    connection.send_logoff()
