"""End-to-end tests of NativeSteamClient against the scripted fake CM."""

from __future__ import annotations

import time
from urllib.parse import unquote

import pytest
from _native_fakes import STEAM_ID, FakeSteam, refresh_token

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.native import NativeSteamClient
from steam_idle_bot.steam.native import messages as m
from steam_idle_bot.steam.native.protobuf import decode
from steam_idle_bot.steam.native.session_store import NativeSessionStore
from steam_idle_bot.utils.exceptions import ConfigurationError, SteamAuthenticationError, SteamConnectionError


@pytest.fixture
def rsa_key():
    rsa = pytest.importorskip("Cryptodome.PublicKey.RSA")
    return rsa.generate(2048)


def make_client(tmp_path, steam: FakeSteam, codes: list[str | None] | None = None, **settings) -> NativeSteamClient:
    config = Settings(username="SteamUser", password=steam.password, idling_backend="native", native_session_path=str(tmp_path / "session.json"), **settings)
    client = NativeSteamClient(config, connection_factory=steam.connection, sleep_fn=lambda seconds: None)
    pending = list(codes or [])
    client.prompts = []  # type: ignore[attr-defined]

    def provider(is_2fa: bool, mismatch: bool) -> str | None:
        client.prompts.append((is_2fa, mismatch))  # type: ignore[attr-defined]
        return pending.pop(0) if pending else None

    client.auth_code_provider = provider
    return client


def wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_first_login_with_mobile_code_saves_session_then_reuses_it(tmp_path, rsa_key):
    steam = FakeSteam(rsa_key=rsa_key)
    client = make_client(tmp_path, steam, codes=["ab12c"])
    assert client.initialize() is True
    assert client.login() is True

    assert steam.decrypted_passwords == ["hunter2"]  # RSA round trip through the real codec
    assert steam.submitted_codes == ["AB12C"]  # normalized to upper case
    assert client.prompts == [(True, False)]
    assert client.is_connected()
    assert client.steam_id == str(STEAM_ID)
    assert client.username == "SteamUser"
    assert steam.logon_tokens == [steam.issued_refresh_token]

    logon = next(p for p in steam.sent if p.emsg == m.EMsg.ClientLogon)
    body = decode(m.CLIENT_LOGON, logon.body)
    assert "account_name" not in body and body["should_remember_password"] is True
    assert body["machine_id"] == m.machine_id_for("steamuser")
    assert logon.header["steamid"] == STEAM_ID

    store = NativeSessionStore(tmp_path / "session.json")
    saved = store.get("steamuser")
    assert saved is not None and saved.refresh_token == steam.issued_refresh_token and saved.guard_data == "GUARD.TOKEN"
    client.logout()
    assert not client.is_connected()

    # Second run: no password, no Steam Guard prompt.
    second_steam = FakeSteam(rsa_key=rsa_key)
    second = make_client(tmp_path, second_steam)
    assert second.login() is True
    assert second.prompts == []
    assert "Authentication.BeginAuthSessionViaCredentials#1" not in second_steam.service_calls()
    assert second_steam.logon_tokens == [steam.issued_refresh_token]
    second.logout()


def test_wrong_code_is_retried_with_mismatch_flag(tmp_path):
    steam = FakeSteam()
    client = make_client(tmp_path, steam, codes=["WRONG", "AB12C"])
    assert client.login() is True
    assert client.prompts == [(True, False), (True, True)]
    assert steam.submitted_codes == ["WRONG", "AB12C"]
    client.logout()


def test_three_wrong_codes_stop_to_avoid_throttle(tmp_path):
    steam = FakeSteam()
    client = make_client(tmp_path, steam, codes=["X", "Y", "Z"])
    with pytest.raises(SteamAuthenticationError, match="rejected 3 times"):
        client.login()


def test_email_code_flow(tmp_path):
    steam = FakeSteam(confirmations=[m.EAuthSessionGuardType.EmailCode, m.EAuthSessionGuardType.EmailConfirmation])
    client = make_client(tmp_path, steam, codes=["WRONG", "AB12C"])
    assert client.login() is True
    assert client.prompts == [(False, False), (False, True)]
    client.logout()


def test_cancelled_code_raises_cancel_error(tmp_path):
    client = make_client(tmp_path, FakeSteam(), codes=[""])
    with pytest.raises(SteamAuthenticationError, match="cancelled"):
        client.login()
    assert not client.is_connected()


def test_in_app_approval_polls_without_prompting(tmp_path, caplog):
    caplog.set_level("INFO", logger="steam_idle_bot")
    steam = FakeSteam(confirmations=[m.EAuthSessionGuardType.DeviceConfirmation], polls_before_approval=3)
    client = make_client(tmp_path, steam)
    assert client.login() is True
    assert client.prompts == []
    assert steam.service_calls().count("Authentication.PollAuthSessionStatus#1") == 4
    assert "Approve this login in the Steam Mobile app" in caplog.text
    client.logout()


@pytest.mark.parametrize("kind", [m.EAuthSessionGuardType.NoGuard, m.EAuthSessionGuardType.MachineToken])
def test_no_guard_or_machine_token_skips_prompt(tmp_path, kind):
    steam = FakeSteam(confirmations=[kind])
    client = make_client(tmp_path, steam)
    assert client.login() is True and client.prompts == []
    client.logout()


def test_stored_guard_data_is_sent_with_next_password_login(tmp_path):
    NativeSessionStore(tmp_path / "session.json").save("steamuser", STEAM_ID, "not-a-jwt", "MACHINE.GUARD")
    steam = FakeSteam(confirmations=[m.EAuthSessionGuardType.MachineToken])
    client = make_client(tmp_path, steam)
    assert client.login() is True
    begin = next(p for p in steam.sent if p.header.get("target_job_name") == "Authentication.BeginAuthSessionViaCredentials#1")
    assert decode(m.AUTH_BEGIN_REQUEST, begin.body)["guard_data"] == "MACHINE.GUARD"
    client.logout()


def test_unsupported_confirmation_type_fails(tmp_path):
    client = make_client(tmp_path, FakeSteam(confirmations=[m.EAuthSessionGuardType.LegacyMachineAuth]))
    with pytest.raises(SteamAuthenticationError, match="unsupported confirmation"):
        client.login()


def test_wrong_password_explains_and_does_not_retry(tmp_path, rsa_key):
    steam = FakeSteam(rsa_key=rsa_key)
    steam.password = "the-real-one"
    config_password_client = make_client(tmp_path, FakeSteam(rsa_key=rsa_key))  # password hunter2
    config_password_client._connection_factory = steam.connection
    with pytest.raises(SteamAuthenticationError, match="rejected the username or password") as excinfo:
        config_password_client.login()
    assert "InvalidPassword" in str(excinfo.value)
    assert steam.service_calls().count("Authentication.BeginAuthSessionViaCredentials#1") == 1


def test_rate_limited_begin_is_reported(tmp_path):
    client = make_client(tmp_path, FakeSteam(begin_eresult=m.EResult.RateLimitExceeded))
    with pytest.raises(SteamAuthenticationError, match="Too many login attempts"):
        client.login()


def test_rejected_saved_token_falls_back_to_password_login(tmp_path, caplog):
    old_token = refresh_token(days=100)
    NativeSessionStore(tmp_path / "session.json").save("steamuser", STEAM_ID, old_token)
    steam = FakeSteam(logon_results=[m.EResult.AccessDenied])
    client = make_client(tmp_path, steam, codes=["AB12C"])
    assert client.login() is True
    assert steam.logon_tokens == [old_token, steam.issued_refresh_token]
    assert "Saved Steam session was rejected" in caplog.text
    assert NativeSessionStore(tmp_path / "session.json").get("steamuser").refresh_token == steam.issued_refresh_token
    client.logout()


def test_expired_saved_token_is_dropped_before_logon(tmp_path):
    NativeSessionStore(tmp_path / "session.json").save("steamuser", STEAM_ID, refresh_token(days=0.01))
    steam = FakeSteam()
    client = make_client(tmp_path, steam, codes=["AB12C"])
    assert client.login() is True
    assert steam.logon_tokens == [steam.issued_refresh_token]
    client.logout()


def test_try_another_cm_retries_then_gives_up(tmp_path):
    NativeSessionStore(tmp_path / "session.json").save("steamuser", STEAM_ID, refresh_token())
    steam = FakeSteam(logon_results=[m.EResult.TryAnotherCM])
    client = make_client(tmp_path, steam)
    assert client.login() is True
    assert len(steam.logon_tokens) == 2
    client.logout()

    stubborn = FakeSteam(logon_results=[m.EResult.ServiceUnavailable] * 3)
    client = make_client(tmp_path, stubborn)
    assert client.login() is False  # connection-level failure is reported as False, like the python backend


def test_banned_account_logon_is_fatal(tmp_path):
    NativeSessionStore(tmp_path / "session.json").save("steamuser", STEAM_ID, refresh_token())
    client = make_client(tmp_path, FakeSteam(logon_results=[m.EResult.Banned]))
    with pytest.raises(SteamAuthenticationError, match="banned"):
        client.login()


def test_missing_credentials_and_unreachable_steam(tmp_path):
    client = make_client(tmp_path, FakeSteam())
    client.settings.password = ""
    with pytest.raises(ConfigurationError):
        client.login()

    down = FakeSteam(unreachable_endpoints={"cm1.example:443", "cm2.example:443"})
    assert make_client(tmp_path, down).login() is False


def test_login_interrupted_returns_false(tmp_path):
    client = make_client(tmp_path, FakeSteam())

    def interrupt(is_2fa, mismatch):
        raise KeyboardInterrupt

    client.auth_code_provider = interrupt
    assert client.login() is False


def test_refresh_token_is_renewed_when_close_to_expiry(tmp_path, caplog):
    caplog.set_level("INFO", logger="steam_idle_bot")
    NativeSessionStore(tmp_path / "session.json").save("steamuser", STEAM_ID, refresh_token(days=10))
    renewed = refresh_token(days=200)
    steam = FakeSteam(renewed_refresh_token=renewed)
    client = make_client(tmp_path, steam)
    assert client.login() is True
    assert NativeSessionStore(tmp_path / "session.json").get("steamuser").refresh_token == renewed
    assert "Renewed the saved Steam session" in caplog.text
    client.logout()


# ---------------------------------------------------------------------------
# Idling, events, web session
# ---------------------------------------------------------------------------


@pytest.fixture
def logged_in(tmp_path):
    NativeSessionStore(tmp_path / "session.json").save("steamuser", STEAM_ID, refresh_token())
    steam = FakeSteam()
    client = make_client(tmp_path, steam)
    assert client.login() is True
    yield client, steam
    client.logout()


def test_start_idling_dedupes_and_caps_at_32(logged_in):
    client, steam = logged_in
    assert client.start_idling([570, 730, 570] + list(range(1, 40))) is True
    played = steam.games_played[-1]
    assert played[:2] == [570, 730] and len(played) == 32
    assert client.refresh_games([440]) is True
    assert steam.games_played[-1] == [440]
    assert client.stop_idling() is True
    assert steam.games_played[-1] == []


def test_start_idling_requires_connection(tmp_path):
    client = make_client(tmp_path, FakeSteam())
    with pytest.raises(SteamConnectionError):
        client.start_idling([570])
    assert client.stop_idling() is False


def test_playing_session_block_and_resume(logged_in, caplog):
    caplog.set_level("INFO", logger="steam_idle_bot")
    client, steam = logged_in
    client.start_idling([570])
    steam.push_event(m.EMsg.ClientPlayingSessionState, m.PLAYING_SESSION_STATE, {"playing_blocked": True, "playing_app": 440})
    assert wait_until(lambda: client.playing_blocked)
    assert "Another Steam session is playing a game (app 440)" in caplog.text
    sent_before = len(steam.games_played)

    client.start_idling([570, 730])  # still accepted while blocked; warns again
    steam.push_event(m.EMsg.ClientPlayingSessionState, m.PLAYING_SESSION_STATE, {"playing_blocked": False})
    assert wait_until(lambda: not client.playing_blocked)
    assert wait_until(lambda: steam.games_played[-1] == [570, 730] and len(steam.games_played) >= sent_before + 2)
    assert "resuming idling of 2 games" in caplog.text


def test_logged_off_by_steam_marks_disconnected_and_reconnects(logged_in, caplog):
    client, steam = logged_in
    steam.push_event(m.EMsg.ClientLoggedOff, m.CLIENT_LOGGED_OFF, {"eresult": int(m.EResult.LogonSessionReplaced)})
    assert wait_until(lambda: not client.is_connected())
    assert "LogonSessionReplaced (34)" in caplog.text
    assert client.reconnect() is True
    assert client.is_connected()
    assert len(steam.logon_tokens) == 2


def test_server_disconnect_is_detected(logged_in, caplog):
    client, steam = logged_in
    steam.sockets[-1].close()
    assert wait_until(lambda: not client.is_connected())
    assert "Disconnected from Steam CM" in caplog.text


def test_reconnect_failure_returns_false(logged_in):
    client, steam = logged_in
    steam.unreachable_endpoints = {"cm1.example:443", "cm2.example:443"}
    assert client.reconnect() is False


def test_web_session_is_minted_from_the_login(logged_in):
    client, steam = logged_in
    session = client.get_web_session(cookies={"steamLoginSecure": "stale"})
    cookie = session.cookies.get("steamLoginSecure", domain="steamcommunity.com")
    assert unquote(cookie) == f"{STEAM_ID}||{steam.access_token}"
    assert session.cookies.get("sessionid", domain="steamcommunity.com")
    generate = next(p for p in steam.sent if p.header.get("target_job_name") == "Authentication.GenerateAccessTokenForApp#1")
    assert generate.emsg == m.EMsg.ServiceMethodCallFromClient
    assert generate.header["client_sessionid"] == 4242


def test_web_session_falls_back_to_configured_cookies(tmp_path):
    client = make_client(tmp_path, FakeSteam())  # never logged in
    session = client.get_web_session(cookies={"steamLoginSecure": "configured"})
    assert session.cookies.get("steamLoginSecure", domain="steamcommunity.com") == "configured"
    assert client.get_web_session() is None


def test_refresh_web_session_only_when_stale(logged_in):
    client, steam = logged_in
    assert client.refresh_web_session_if_stale() is None  # nothing minted yet
    client.get_web_session()
    assert client.refresh_web_session_if_stale() is None  # fresh
    client._web_session_minted_at = time.time() - 7 * 3600
    steam.access_token = "NEW.ACCESS"
    session = client.refresh_web_session_if_stale()
    assert unquote(session.cookies.get("steamLoginSecure", domain="steamcommunity.com")).endswith("||NEW.ACCESS")


def test_terminal_prompt_wording(monkeypatch):
    prompts = []
    monkeypatch.setattr("builtins.input", lambda text: prompts.append(text) or "CODE")
    assert NativeSteamClient._prompt_for_auth_code(True, False) == "CODE"
    NativeSteamClient._prompt_for_auth_code(False, True)
    assert prompts == ["Enter the Steam Mobile (2FA) code: ", "Incorrect code. Enter a new e-mail Steam Guard code: "]


def test_initialize_reports_missing_websockets(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("websockets"):
            raise ImportError("no websockets")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert make_client(tmp_path, FakeSteam()).initialize() is False


@pytest.mark.parametrize("system, expected", [("Windows", m.OS_TYPE_WIN11), ("Darwin", m.OS_TYPE_MACOS_UNKNOWN), ("Linux", m.OS_TYPE_LINUX_UNKNOWN)])
def test_os_type_detection(monkeypatch, system, expected):
    from steam_idle_bot.steam.native import client as client_module

    monkeypatch.setattr(client_module.platform, "system", lambda: system)
    assert client_module._local_os_type() == expected


# ---------------------------------------------------------------------------
# Edge cases of the auth flow and logon
# ---------------------------------------------------------------------------


def _connected(steam: FakeSteam):
    connection = steam.connection()
    connection.connect()
    return connection


def test_auth_poll_times_out_and_can_be_cancelled():
    from steam_idle_bot.steam.native.auth import authenticate_with_credentials

    steam = FakeSteam(confirmations=[m.EAuthSessionGuardType.DeviceConfirmation], polls_before_approval=10**6)
    connection = _connected(steam)
    with pytest.raises(SteamAuthenticationError, match="Timed out"):
        authenticate_with_credentials(connection, "u", "hunter2", code_provider=lambda *a: None, sleep=lambda s: None, poll_timeout=0)
    with pytest.raises(SteamAuthenticationError, match="Login cancelled"):
        authenticate_with_credentials(connection, "u", "hunter2", code_provider=lambda *a: None, sleep=lambda s: None, should_stop=lambda: True)
    connection.close()


def test_auth_follows_new_client_id_and_reports_unexpected_code_errors():
    from steam_idle_bot.steam.native import auth
    from steam_idle_bot.steam.native.cm import ServiceResponse

    steam = FakeSteam(confirmations=[m.EAuthSessionGuardType.NoGuard], polls_before_approval=1)
    connection = _connected(steam)
    original = connection.call_service
    polls: list[int] = []

    def call_service(method, request_schema, request, response_schema, **kwargs):
        if method == "Authentication.PollAuthSessionStatus#1":
            polls.append(request["client_id"])
            response = original(method, request_schema, request, response_schema, **kwargs)
            if len(polls) == 1:
                response.body["new_client_id"] = 999
            return response
        if method == "Authentication.UpdateAuthSessionWithSteamGuardCode#1":
            return ServiceResponse(m.EResult.RateLimitExceeded, {})
        return original(method, request_schema, request, response_schema, **kwargs)

    connection.call_service = call_service  # type: ignore[method-assign]
    result = auth.authenticate_with_credentials(connection, "u", "hunter2", code_provider=lambda *a: "X", sleep=lambda s: None)
    assert polls == [777, 999] and result.refresh_token == steam.issued_refresh_token

    with pytest.raises(SteamAuthenticationError, match="Too many login attempts"):
        auth._submit_guard_code(connection, 1, 2, m.EAuthSessionGuardType.DeviceCode, lambda *a: "CODE")
    connection.close()


def test_auth_rejects_malformed_rsa_key():
    from steam_idle_bot.steam.native.auth import authenticate_with_credentials
    from steam_idle_bot.steam.native.cm import ServiceResponse

    connection = _connected(FakeSteam())
    connection.call_service = lambda *a, **k: ServiceResponse(m.EResult.OK, {"publickey_mod": "zz", "publickey_exp": "1"})  # type: ignore[method-assign]
    with pytest.raises(SteamAuthenticationError, match="malformed RSA"):
        authenticate_with_credentials(connection, "u", "p", code_provider=lambda *a: None)
    connection.close()


def test_explain_login_failure_unknown_code():
    from steam_idle_bot.steam.native.auth import explain_login_failure

    assert explain_login_failure(4242) == "Steam login failed (EResult 4242). [EResult 4242]"
    assert explain_login_failure(m.EResult.Expired, "detail").endswith("[Expired] detail")


def test_freshly_issued_token_rejected_stops_instead_of_looping(tmp_path):
    steam = FakeSteam(logon_results=[m.EResult.AccessDenied] * 3)
    client = make_client(tmp_path, steam, codes=["AB12C"] * 3)
    with pytest.raises(SteamAuthenticationError, match="password login is required"):
        client.login()
    assert steam.service_calls().count("Authentication.BeginAuthSessionViaCredentials#1") == 1


def test_logon_without_answer_or_with_garbage(tmp_path):
    NativeSessionStore(tmp_path / "session.json").save("steamuser", STEAM_ID, refresh_token())
    silent = FakeSteam()
    silent._logon = lambda ws, packet: None  # type: ignore[method-assign]
    client = make_client(tmp_path, silent)
    import steam_idle_bot.steam.native.client as client_module

    original_timeout = client_module._LOGON_TIMEOUT_SECONDS
    client_module._LOGON_TIMEOUT_SECONDS = 0.05
    try:
        assert client.login() is False
    finally:
        client_module._LOGON_TIMEOUT_SECONDS = original_timeout

    garbage = FakeSteam()
    garbage._logon = lambda ws, packet: ws.push(m.build_packet(m.EMsg.ClientLogOnResponse, {}, m.EMPTY, {}) + b"\x0b")  # type: ignore[method-assign]
    assert make_client(tmp_path, garbage).login() is False


def test_web_session_falls_back_when_token_generation_fails(logged_in):
    client, steam = logged_in
    steam.access_token = ""  # Steam answered without a token
    assert client.get_web_session() is None

    from steam_idle_bot.steam.native.cm import ServiceResponse

    client._connection.call_service = lambda *a, **k: ServiceResponse(m.EResult.AccessDenied, {})  # type: ignore[union-attr]
    assert client._generate_access_token() is None

    def boom(*a, **k):
        raise SteamConnectionError("lost")

    client._connection.call_service = boom  # type: ignore[union-attr]
    assert client._generate_access_token() is None


def test_login_accepts_provider_argument_and_exposes_connection(tmp_path):
    steam = FakeSteam()
    client = make_client(tmp_path, steam)
    seen = []
    assert client.login(auth_code_provider=lambda is_2fa, mismatch: seen.append(is_2fa) or "AB12C") is True
    assert seen == [True]
    assert client.client is client._connection and client.client.logged_on
    slept = []
    client._sleep = slept.append
    client.sleep(1.5)
    assert slept == [1.5]
    client.logout()
    assert client.client is None


def test_games_played_send_failure_returns_false(logged_in):
    client, steam = logged_in

    def broken(*a, **k):
        raise SteamConnectionError("socket gone")

    client._connection.send = broken  # type: ignore[union-attr]
    assert client.start_idling([570]) is False
    assert client.stop_idling() is False
