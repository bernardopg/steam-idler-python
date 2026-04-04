"""Tests for Steam client wrapper behavior."""

from __future__ import annotations

import builtins
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.steam.client import SteamClientWrapper
from steam_idle_bot.utils.exceptions import (
    ConfigurationError,
    SteamAuthenticationError,
    SteamConnectionError,
)


def make_settings() -> Settings:
    return Settings(username="user", password="pass")


class FakeSteamClient:
    def __init__(self) -> None:
        self.connected = True
        self.steam_id = "7656119"
        self.username = "bot-user"
        self.played_calls: list[list[int]] = []
        self.logout_called = False
        self.disconnect_called = False
        self.sleep_calls: list[float] = []

    def cli_login(self, username: str, password: str) -> int:
        return 1

    def games_played(self, game_ids):
        self.played_calls.append(list(game_ids))

    def logout(self):
        self.logout_called = True

    def sleep(self, seconds: float):
        self.sleep_calls.append(seconds)


def test_initialize_success() -> None:
    wrapper = SteamClientWrapper(make_settings())
    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == "steam.client":
            fake_mod = ModuleType("steam.client")
            fake_mod.SteamClient = FakeSteamClient
            return fake_mod
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_import):
        assert wrapper.initialize() is True
        assert wrapper.client is not None


def test_initialize_import_error() -> None:
    wrapper = SteamClientWrapper(make_settings())
    real_import = builtins.__import__

    with patch("builtins.__import__") as import_mock:

        def _import(name, *args, **kwargs):
            if name == "steam.client":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        import_mock.side_effect = _import
        assert wrapper.initialize() is False


def test_initialize_generic_exception() -> None:
    wrapper = SteamClientWrapper(make_settings())
    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == "steam.client":
            fake_mod = ModuleType("steam.client")

            class Boom:
                def __init__(self):
                    raise RuntimeError("boom")

            fake_mod.SteamClient = Boom
            return fake_mod
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_import):
        assert wrapper.initialize() is False


def test_login_requires_initialized_client() -> None:
    wrapper = SteamClientWrapper(make_settings())
    with pytest.raises(SteamConnectionError):
        wrapper.login()


def test_login_requires_credentials() -> None:
    settings = make_settings()
    settings.username = ""
    wrapper = SteamClientWrapper(settings)
    wrapper._client = FakeSteamClient()

    with pytest.raises(ConfigurationError):
        wrapper.login()


def test_login_cli_failure_raises_auth_error() -> None:
    wrapper = SteamClientWrapper(make_settings())
    client = FakeSteamClient()
    client.cli_login = lambda **kwargs: 0  # type: ignore[method-assign]
    wrapper._client = client

    with pytest.raises(SteamAuthenticationError):
        wrapper.login()


def test_login_with_log_on_path() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class LogOnClient:
        connected = True

        def __init__(self):
            self.steam_id = "1"
            self.user = SimpleNamespace(username="name")
            self.called = False

        def log_on(self, username: str, password: str):
            self.called = True

    client = LogOnClient()
    wrapper._client = client

    assert wrapper.login() is True
    assert client.called is True
    assert wrapper.username == "name"


def test_login_with_login_path() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class LoginClient:
        connected = True

        def __init__(self):
            self.steam_id = "1"
            self.username = "u"
            self.called = False

        def login(self, username: str, password: str):
            self.called = True

    client = LoginClient()
    wrapper._client = client

    assert wrapper.login() is True
    assert client.called is True


def test_login_with_two_factor_callback() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class LoginClient:
        connected = True

        def __init__(self) -> None:
            self.steam_id = "1"
            self.username = "u"
            self.calls: list[dict[str, str | None]] = []

        def login(
            self,
            username: str,
            password: str,
            login_key=None,
            auth_code=None,
            two_factor_code=None,
            login_id=None,
        ):
            self.calls.append(
                {
                    "username": username,
                    "password": password,
                    "auth_code": auth_code,
                    "two_factor_code": two_factor_code,
                }
            )
            if len(self.calls) == 1:
                return SimpleNamespace(name="AccountLoginDeniedNeedTwoFactor")
            return SimpleNamespace(name="OK")

    client = LoginClient()
    wrapper._client = client

    provider_calls: list[tuple[bool, bool]] = []

    def provider(is_2fa: bool, code_mismatch: bool) -> str:
        provider_calls.append((is_2fa, code_mismatch))
        return "654321"

    assert wrapper.login(auth_code_provider=provider) is True
    assert provider_calls == [(True, False)]
    assert client.calls[1]["two_factor_code"] == "654321"


def test_login_with_cancelled_auth_code_raises() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class LoginClient:
        connected = True

        def login(
            self,
            username: str,
            password: str,
            login_key=None,
            auth_code=None,
            two_factor_code=None,
            login_id=None,
        ):
            return SimpleNamespace(name="AccountLogonDenied")

    wrapper._client = LoginClient()

    with pytest.raises(SteamAuthenticationError, match="cancelled"):
        wrapper.login(auth_code_provider=lambda is_2fa, code_mismatch: None)


def test_login_without_compatible_method() -> None:
    wrapper = SteamClientWrapper(make_settings())
    wrapper._client = object()

    with pytest.raises(SteamAuthenticationError):
        wrapper.login()


def test_login_keyboard_interrupt_returns_false() -> None:
    wrapper = SteamClientWrapper(make_settings())
    client = FakeSteamClient()

    def _interrupt(**kwargs):
        raise KeyboardInterrupt

    client.cli_login = _interrupt  # type: ignore[method-assign,assignment]
    wrapper._client = client

    assert wrapper.login() is False


def test_start_idling_paths() -> None:
    wrapper = SteamClientWrapper(make_settings())

    with pytest.raises(SteamConnectionError):
        wrapper.start_idling([1])

    wrapper._client = FakeSteamClient()
    wrapper._client.connected = False
    with pytest.raises(SteamConnectionError):
        wrapper.start_idling([1])

    wrapper._client.connected = True
    assert wrapper.start_idling([1, 2]) is True
    assert wrapper._client.played_calls[-1] == [1, 2]


def test_start_idling_missing_method_and_exception() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class NoMethodClient:
        connected = True

    wrapper._client = NoMethodClient()
    assert wrapper.start_idling([1]) is False

    class FailingClient(FakeSteamClient):
        def games_played(self, game_ids):
            raise RuntimeError("boom")

    wrapper._client = FailingClient()
    assert wrapper.start_idling([1]) is False


def test_stop_idling_paths() -> None:
    wrapper = SteamClientWrapper(make_settings())
    assert wrapper.stop_idling() is False

    wrapper._client = FakeSteamClient()
    assert wrapper.stop_idling() is True
    assert wrapper._client.played_calls[-1] == []

    class FailingClient(FakeSteamClient):
        def games_played(self, game_ids):
            raise RuntimeError("boom")

    wrapper._client = FailingClient()
    assert wrapper.stop_idling() is False


def test_is_connected_handles_exceptions() -> None:
    wrapper = SteamClientWrapper(make_settings())
    assert wrapper.is_connected() is False

    class WeirdClient:
        @property
        def connected(self):
            raise RuntimeError("bad")

    wrapper._client = WeirdClient()
    assert wrapper.is_connected() is False


def test_logout_paths() -> None:
    wrapper = SteamClientWrapper(make_settings())
    assert wrapper.logout() is True

    wrapper._client = FakeSteamClient()
    assert wrapper.logout() is True

    class DisconnectClient:
        def __init__(self):
            self.called = False

        def disconnect(self):
            self.called = True

    dc = DisconnectClient()
    wrapper._client = dc
    assert wrapper.logout() is True
    assert dc.called is True

    class FailingLogout:
        def logout(self):
            raise RuntimeError("boom")

    wrapper._client = FailingLogout()
    assert wrapper.logout() is False


def test_sleep_falls_back_to_time_sleep(monkeypatch) -> None:
    wrapper = SteamClientWrapper(make_settings())

    captured = []
    monkeypatch.setattr("time.sleep", lambda s: captured.append(s))
    wrapper.sleep(0.1)
    assert captured == [0.1]

    class BrokenSleepClient(FakeSteamClient):
        def sleep(self, seconds: float):
            raise RuntimeError("nope")

    wrapper._client = BrokenSleepClient()
    wrapper.sleep(0.2)
    assert captured[-1] == 0.2


def test_refresh_games_and_properties() -> None:
    wrapper = SteamClientWrapper(make_settings())
    wrapper._client = FakeSteamClient()
    wrapper._steam_id = "123"
    wrapper._username = "abc"

    assert wrapper.refresh_games([9]) is True
    assert wrapper.steam_id == "123"
    assert wrapper.username == "abc"
    assert wrapper.client is wrapper._client


def test_update_user_info_handles_exceptions() -> None:
    wrapper = SteamClientWrapper(make_settings())

    class Broken:
        @property
        def steam_id(self):
            raise RuntimeError("x")

    wrapper._client = Broken()
    wrapper._update_user_info()


def test_sleep_uses_client_sleep_when_available() -> None:
    wrapper = SteamClientWrapper(make_settings())
    wrapper._client = FakeSteamClient()
    wrapper.sleep(0.5)
    assert wrapper._client.sleep_calls == [0.5]
