"""Tests for browser cookie community-token validation."""

from __future__ import annotations

import base64
import json

from steam_idle_bot.steam.browser_cookies import is_community_token, load_community_cookies


def _make_token(aud, sub: str, steam_id: str = "76561198000000000") -> str:
    header = base64.urlsafe_b64encode(b'{"typ":"JWT","alg":"EdDSA"}').decode().rstrip("=")
    payload_raw = json.dumps({"aud": aud, "sub": sub}).encode()
    payload = base64.urlsafe_b64encode(payload_raw).decode().rstrip("=")
    return f"{steam_id}%7C%7C{header}.{payload}.signature"


def test_is_community_token_accepts_community_audience() -> None:
    token = _make_token(["web:community"], "76561198000000000")
    assert is_community_token(token, "76561198000000000") is True


def test_is_community_token_rejects_store_audience() -> None:
    token = _make_token(["web:store"], "76561198000000000")
    assert is_community_token(token, "76561198000000000") is False


def test_is_community_token_rejects_wrong_account() -> None:
    token = _make_token(["web:community"], "76561198000000000")
    assert is_community_token(token, "76561199999999999") is False


def test_is_community_token_ignores_account_when_not_given() -> None:
    token = _make_token(["web:community"], "76561198000000000")
    assert is_community_token(token, None) is True


def test_is_community_token_handles_garbage() -> None:
    assert is_community_token("not-a-token", "123") is False


def test_load_community_cookies_without_browser_cookie3(monkeypatch) -> None:
    # Simulate the dependency being unavailable: import fails -> None, no crash.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "browser_cookie3":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert load_community_cookies("123") is None
