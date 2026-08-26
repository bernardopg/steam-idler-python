"""Additional tests for SteamClientWrapper: reconnect, web-session and login-flow branches."""

from __future__ import annotations

import builtins
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.client import SteamClientWrapper
from steam_idle_bot.utils.exceptions import SteamAuthenticationError, SteamConnectionError


def make_settings() -> Settings:
    return Settings(username="user", password="pass")


# ---------------------------------------------------------------------------
# login() success via cli_login (exercises sleep + _update_user_info + OK path)
# ---------------------------------------------------------------------------


def test_login_cli_login_full_success_path() -> None:
    """A legacy client exposing only ``cli_login`` logs in fully: sleep is
    delegated to the client, user info is read from attributes, and login
    returns True."""
    wrapper = SteamClientWrapper(make_settings())

    class CliClient:
        connected = True
        steam_id = 76561198
        username = "cli-user"
        sleep_calls: list[float] = []

        def cli_login(self, username: str, password: str) -> int:
            assert (username, password) == ("user", "pass")
            return 1

        def sleep(self, seconds: float) -> None:
            self.sleep_calls.append(seconds)

    client = CliClient()
    wrapper._client = client

    assert wrapper.login() is True
    assert client.sleep_calls == [5.0]
    assert wrapper.steam_id == "76561198"
    assert wrapper.username == "cli-user"


def test_login_flow_failure_raises_login_failed_with_login() -> None:
    """``_login_with_auth_flow`` returning False surfaces as the outer
    ``SteamAuthenticationError(\"Login failed with login()\")``."""
    wrapper = SteamClientWrapper(make_settings())

    class LoginClient:
        connected = True

        def login(self, username, password, auth_code=None, two_factor_code=None):
            return SimpleNamespace(name="InvalidPassword")  # not an auth-code case

    wrapper._client = LoginClient()

    with pytest.raises(SteamAuthenticationError, match="Login failed with login"):
        wrapper.login()


def test_login_flow_requires_initialized_client() -> None:
    wrapper = SteamClientWrapper(make_settings())
    with pytest.raises(SteamConnectionError):
        wrapper._login_with_auth_flow(None)


def test_login_flow_typeerror_with_codes_reraises() -> None:
    """A client whose ``login`` rejects the code kwargs *after* a code has been
    obtained must re-raise the TypeError instead of silently retrying."""
    wrapper = SteamClientWrapper(make_settings())

    class StrictClient:
        connected = True

        def login(self, username, password, **kwargs):
            if kwargs:
                raise TypeError("unexpected kwargs")
            return SimpleNamespace(name="AccountLoginDeniedNeedTwoFactor")

    wrapper._client = StrictClient()

    with pytest.raises(SteamAuthenticationError, match="unexpected kwargs"):
        wrapper.login(auth_code_provider=lambda is_2fa, mismatch: "12345")


def test_login_flow_email_code_retry_succeeds() -> None:
    """The email-code (non-2FA) branch: first response demands an email code,
    the retry submits it as ``auth_code`` and succeeds."""
    wrapper = SteamClientWrapper(make_settings())

    class LoginClient:
        connected = True

        def __init__(self) -> None:
            self.calls: list[dict] = []

        def sleep(self, seconds: float) -> None:
            return None

        def login(self, username, password, auth_code=None, two_factor_code=None):
            self.calls.append({"auth_code": auth_code, "two_factor_code": two_factor_code})
            if len(self.calls) == 1:
                return SimpleNamespace(name="AccountLogonDenied")
            if len(self.calls) == 2:
                return SimpleNamespace(name="InvalidLoginAuthCode")
            return SimpleNamespace(name="OK")

    client = LoginClient()
    wrapper._client = client

    provider_results: list[tuple[bool, bool]] = []

    def provider(is_2fa: bool, code_mismatch: bool) -> str:
        provider_results.append((is_2fa, code_mismatch))
        return "mail-code"

    assert wrapper.login(auth_code_provider=provider) is True
    assert provider_results == [(False, False), (False, True)]
    assert client.calls[1]["auth_code"] == "mail-code"
    assert client.calls[2]["auth_code"] == "mail-code"


def test_login_flow_two_factor_mismatch_retry_succeeds() -> None:
    """The 2FA mismatch branch: a wrong code asks again (code_mismatch=True)."""
    wrapper = SteamClientWrapper(make_settings())

    class LoginClient:
        connected = True

        def __init__(self) -> None:
            self.calls: list[dict] = []

        def sleep(self, seconds: float) -> None:
            return None

        def login(self, username, password, auth_code=None, two_factor_code=None):
            self.calls.append({"auth_code": auth_code, "two_factor_code": two_factor_code})
            if len(self.calls) == 1:
                return SimpleNamespace(name="AccountLoginDeniedNeedTwoFactor")
            if len(self.calls) == 2:
                return SimpleNamespace(name="TwoFactorCodeMismatch")
            return 1

    client = LoginClient()
    wrapper._client = client

    codes = iter(["11111", "22222"])
    provider_results: list[tuple[bool, bool]] = []

    def provider(is_2fa: bool, code_mismatch: bool) -> str:
        provider_results.append((is_2fa, code_mismatch))
        return next(codes)

    assert wrapper.login(auth_code_provider=provider) is True
    assert provider_results == [(True, False), (True, True)]
    assert client.calls[1]["two_factor_code"] == "11111"
    assert client.calls[2]["two_factor_code"] == "22222"


def test_prompt_for_auth_code_reads_from_stdin(monkeypatch) -> None:
    monkeypatch.setattr(builtins, "input", lambda prompt: captured.append(prompt) or "AB123")
    captured: list[str] = []

    assert SteamClientWrapper._prompt_for_auth_code(is_2fa=False, code_mismatch=False) == "AB123"
    assert SteamClientWrapper._prompt_for_auth_code(is_2fa=True, code_mismatch=True) == "AB123"
    assert captured == ["Enter email code: ", "Incorrect 2FA code. Enter a new code: "]


def test_prompt_helpers_return_empty_string_on_none(monkeypatch) -> None:
    wrapper = SteamClientWrapper(make_settings())
    monkeypatch.setattr(builtins, "input", lambda prompt: None)

    assert wrapper._prompt_for_2fa_code() == ""
    assert wrapper._prompt_for_email_code() == ""


# ---------------------------------------------------------------------------
# reconnect()
# ---------------------------------------------------------------------------


def test_reconnect_without_client_returns_false() -> None:
    wrapper = SteamClientWrapper(make_settings())
    assert wrapper.reconnect() is False


def test_reconnect_relogin_success_updates_user_info() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class ReloginClient:
        connected = False
        steam_id = "42"
        username = "re-user"
        relogin_calls = 0

        def relogin(self):
            type(self).relogin_calls += 1
            # Connected right after relogin, so the first poll succeeds without sleeping.
            self.connected = True
            return True

    client = ReloginClient()
    wrapper._client = client

    assert wrapper.reconnect() is True
    assert client.relogin_calls == 1
    assert wrapper.steam_id == "42"
    assert wrapper.username == "re-user"


def test_reconnect_relogin_never_connected_falls_back_to_login() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class NeverConnects:
        connected = False
        relogin_calls = 0

        def relogin(self):
            type(self).relogin_calls += 1
            return None

        def sleep(self, seconds):
            return None

        def login(self, username, password, **kwargs):
            return SimpleNamespace(name="OK")

    client = NeverConnects()
    wrapper._client = client

    assert wrapper.reconnect() is True
    assert client.relogin_calls == 1


def test_reconnect_without_relogin_delegates_to_login() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class NoReloginClient:
        connected = True
        steam_id = "7"
        username = "u"

        def sleep(self, seconds: float) -> None:
            return None

        def login(self, username, password, **kwargs):
            return SimpleNamespace(name="OK")

    wrapper._client = NoReloginClient()
    assert wrapper.reconnect() is True


def test_reconnect_swallows_exceptions() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class ExplodingClient:
        def relogin(self):
            raise RuntimeError("relogin boom")

    wrapper._client = ExplodingClient()
    assert wrapper.reconnect() is False


# ---------------------------------------------------------------------------
# stop_idling / logout edges
# ---------------------------------------------------------------------------


def test_stop_idling_without_games_played_method_returns_false() -> None:
    wrapper = SteamClientWrapper(make_settings())
    wrapper._client = type("Bare", (), {"connected": True})()
    assert wrapper.stop_idling() is False


def test_logout_without_any_disconnect_method_is_noop_true() -> None:
    wrapper = SteamClientWrapper(make_settings())
    wrapper._client = type("Bare", (), {})()
    assert wrapper.logout() is True


# ---------------------------------------------------------------------------
# get_web_session edges
# ---------------------------------------------------------------------------


def test_get_web_session_without_client_warns_and_returns_none(caplog) -> None:
    wrapper = SteamClientWrapper(make_settings())

    with caplog.at_level("WARNING", logger="steam_idle_bot.steam.client"):
        assert wrapper.get_web_session() is None
    assert "Could not create authenticated Steam web session" in caplog.text


def test_get_web_session_client_without_session_methods_returns_none() -> None:
    wrapper = SteamClientWrapper(make_settings())
    wrapper._client = type("Bare", (), {"sleep_calls": []})()

    assert wrapper.get_web_session() is None


def test_get_web_session_retries_then_gives_up_without_cookies() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class EmptyClient:
        session_attempts = 0
        cookie_attempts = 0

        def get_web_session(self):
            type(self).session_attempts += 1
            return None

        def get_web_session_cookies(self):
            type(self).cookie_attempts += 1
            return None

        def sleep(self, seconds):
            return None

    wrapper._client = EmptyClient()

    assert wrapper.get_web_session() is None
    assert EmptyClient.session_attempts == 6
    assert EmptyClient.cookie_attempts == 10


def test_get_web_session_succeeds_on_retry() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class FlakyClient:
        attempts = 0

        def get_web_session(self):
            type(self).attempts += 1
            if type(self).attempts < 3:
                return None
            return {"ok": True}

        def sleep(self, seconds):
            return None

    wrapper._client = FlakyClient()
    assert wrapper.get_web_session() == {"ok": True}
    assert FlakyClient.attempts == 3


def test_get_web_session_get_web_session_raising_falls_to_cookies() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class BrokenSessionClient:
        def get_web_session(self):
            raise RuntimeError("no session")

        def get_web_session_cookies(self):
            return {"steamLoginSecure": "tok"}

        def sleep(self, seconds):
            return None

    wrapper._client = BrokenSessionClient()
    session = wrapper.get_web_session()
    assert session is not None
    assert session.cookies.get("steamLoginSecure", domain="steamcommunity.com") == "tok"


def test_get_web_session_cookies_raising_returns_none() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class BrokenCookiesClient:
        def get_web_session(self):
            return None

        def get_web_session_cookies(self):
            raise RuntimeError("no cookies")

        def sleep(self, seconds):
            return None

    wrapper._client = BrokenCookiesClient()
    assert wrapper.get_web_session() is None


def test_build_web_session_skips_incomplete_browser_cookie_entries() -> None:
    session = SteamClientWrapper._build_web_session_from_cookies(
        [
            {"name": "steamLoginSecure", "value": "ok-token", "domain": "steamcommunity.com", "path": "/", "secure": True},
            {"name": "", "value": "no-name"},  # skipped: empty name
            {"name": "sessionid"},  # skipped: missing value
        ]
    )

    assert session.cookies.get("steamLoginSecure", domain="steamcommunity.com") == "ok-token"
    # No entry was created for the incomplete rows (any domain).
    assert not any(cookie.name == "sessionid" for cookie in session.cookies)


def test_build_web_session_generates_sessionid_when_missing() -> None:
    session = SteamClientWrapper._build_web_session_from_cookies({"steamLoginSecure": "tok"})

    community_sessionid = session.cookies.get("sessionid", domain="steamcommunity.com")
    assert community_sessionid  # a token was generated
    # Each Steam domain got the same sessionid cookie.
    assert session.cookies.get("sessionid", domain="store.steampowered.com") == community_sessionid


# ---------------------------------------------------------------------------
# get_web_session_cookies_debug
# ---------------------------------------------------------------------------


def test_web_session_cookies_debug_without_client() -> None:
    wrapper = SteamClientWrapper(make_settings())
    assert wrapper.get_web_session_cookies_debug() is None


def test_web_session_cookies_debug_not_logged_on() -> None:
    wrapper = SteamClientWrapper(make_settings())
    wrapper._client = type("LoggedOff", (), {"logged_on": False, "steam_id": "7"})()

    assert wrapper.get_web_session_cookies_debug() is None


def test_web_session_cookies_debug_success_and_errors() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class CookiesClient:
        logged_on = True
        steam_id = "7"

        def get_web_session_cookies(self):
            return {"steamLoginSecure": "tok"}

    wrapper._client = CookiesClient()
    assert wrapper.get_web_session_cookies_debug() == {"steamLoginSecure": "tok"}

    class NoMethodClient:
        logged_on = True
        steam_id = "7"

    wrapper._client = NoMethodClient()
    assert wrapper.get_web_session_cookies_debug() is None

    class ExplodingClient:
        logged_on = True
        steam_id = "7"

        def get_web_session_cookies(self):
            raise RuntimeError("boom")

    wrapper._client = ExplodingClient()
    assert wrapper.get_web_session_cookies_debug() is None


# ---------------------------------------------------------------------------
# _update_user_info branch details
# ---------------------------------------------------------------------------


def test_update_user_info_prefers_username_over_user_attr() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class BothClient:
        steam_id = "9"
        username = "plain"
        user = SimpleNamespace(username="nested")

    wrapper._client = BothClient()
    wrapper._update_user_info()
    assert wrapper.username == "plain"
    assert wrapper.steam_id == "9"


def test_update_user_info_without_any_username_source() -> None:
    wrapper = SteamClientWrapper(make_settings())
    wrapper._client = type("Bare", (), {"steam_id": "5"})()
    wrapper._update_user_info()
    assert wrapper.username is None
    assert wrapper.steam_id == "5"


def test_initialize_generic_import_failure_returns_false() -> None:
    """A non-ImportError failure while constructing SteamClient is swallowed."""
    wrapper = SteamClientWrapper(make_settings())
    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == "steam.client":
            fake_mod = type(builtins)("steam.client")
            fake_mod.SteamClient = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            return fake_mod
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_import):
        assert wrapper.initialize() is False
