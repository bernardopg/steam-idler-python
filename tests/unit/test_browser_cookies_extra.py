"""Additional tests for browser cookie loading — covers uncovered paths."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from steam_idle_bot.steam.browser_cookies import (
    _decode_jwt_payload,
    is_community_token,
    load_community_cookies,
)


def _make_token(aud, sub: str = "76561198000000000", exp: float | None = None) -> str:
    header = base64.urlsafe_b64encode(b'{"typ":"JWT","alg":"EdDSA"}').decode().rstrip("=")
    body: dict = {"aud": aud, "sub": sub}
    if exp is not None:
        body["exp"] = exp
    payload_raw = json.dumps(body).encode()
    payload = base64.urlsafe_b64encode(payload_raw).decode().rstrip("=")
    return f"76561198000000000%7C%7C{header}.{payload}.signature"


# ---------------------------------------------------------------------------
# _decode_jwt_payload
# ---------------------------------------------------------------------------


class TestDecodeJwtPayload:
    def test_valid_token_with_percent_encoding(self):
        token = _make_token(["web:community"])
        result = _decode_jwt_payload(token)
        assert result is not None
        assert "aud" in result

    def test_valid_token_with_pipe_separator(self):
        header = base64.urlsafe_b64encode(b"{}").decode().rstrip("=")
        payload_raw = json.dumps({"aud": ["web:community"]}).encode()
        payload = base64.urlsafe_b64encode(payload_raw).decode().rstrip("=")
        token = f"123||{header}.{payload}.sig"
        result = _decode_jwt_payload(token)
        assert result is not None
        assert result["aud"] == ["web:community"]

    def test_no_separator_returns_none(self):
        assert _decode_jwt_payload("no-separator-here") is None

    def test_too_few_parts_after_split(self):
        header = base64.urlsafe_b64encode(b"{}").decode().rstrip("=")
        token = f"123%7C%7C{header}"
        assert _decode_jwt_payload(token) is None

    def test_invalid_base64_payload(self):
        header = base64.urlsafe_b64encode(b"{}").decode().rstrip("=")
        token = f"123%7C%7C{header}.!!!invalid-base64!!!.sig"
        assert _decode_jwt_payload(token) is None

    def test_non_json_payload(self):
        header = base64.urlsafe_b64encode(b"{}").decode().rstrip("=")
        payload = base64.urlsafe_b64encode(b"not-json").decode().rstrip("=")
        token = f"123%7C%7C{header}.{payload}.sig"
        assert _decode_jwt_payload(token) is None


# ---------------------------------------------------------------------------
# is_community_token — additional edge cases
# ---------------------------------------------------------------------------


class TestIsCommunityToken:
    def test_accepts_no_exp(self):
        token = _make_token(["web:community"])
        assert is_community_token(token) is True

    def test_rejects_garbage_token(self):
        assert is_community_token("garbage") is False

    def test_rejects_empty_string(self):
        assert is_community_token("") is False

    def test_accepts_with_steam_id_matching(self):
        token = _make_token(["web:community"], "76561198000000000")
        assert is_community_token(token, "76561198000000000") is True

    def test_rejects_with_steam_id_mismatch(self):
        token = _make_token(["web:community"], "76561198000000000")
        assert is_community_token(token, "76561199999999999") is False


# ---------------------------------------------------------------------------
# load_community_cookies — specific browser
# ---------------------------------------------------------------------------


class TestLoadCommunityCookies:
    def test_specific_browser_not_available(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "browser_cookie3":
                return MagicMock(spec=[])  # no chrome, firefox, etc.
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert load_community_cookies(browser="chrome") is None

    def test_auto_browser_with_loader_exception(self, monkeypatch):
        mock_bc3 = MagicMock()
        mock_bc3.load = MagicMock(side_effect=Exception("keyring locked"))
        mock_bc3.chrome = MagicMock(side_effect=Exception("chrome locked"))

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "browser_cookie3":
                return mock_bc3
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert load_community_cookies() is None

    def test_auto_browser_with_non_community_token(self, monkeypatch):
        mock_bc3 = MagicMock()
        cookie = SimpleNamespace(name="steamLoginSecure", value="bad-token")
        mock_bc3.load = MagicMock(return_value=[cookie])
        mock_bc3.chrome = None

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "browser_cookie3":
                return mock_bc3
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert load_community_cookies() is None

    def test_specific_browser_with_valid_cookies(self, monkeypatch):
        valid_token = _make_token(["web:community"])
        mock_bc3 = MagicMock()
        cookies = [
            SimpleNamespace(name="steamLoginSecure", value=valid_token),
            SimpleNamespace(name="sessionid", value="abc123"),
        ]
        mock_bc3.chrome = MagicMock(return_value=cookies)

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "browser_cookie3":
                return mock_bc3
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        result = load_community_cookies(browser="chrome")
        assert result is not None
        assert result["steamLoginSecure"] == valid_token
        assert result["sessionid"] == "abc123"

    def test_auto_browser_with_valid_cookies(self, monkeypatch):
        valid_token = _make_token(["web:community"])
        mock_bc3 = MagicMock()
        cookies = [
            SimpleNamespace(name="steamLoginSecure", value=valid_token),
            SimpleNamespace(name="sessionid", value="xyz"),
        ]
        # Auto mode iterates per-browser loaders (aggregate load is skipped).
        mock_bc3.chrome = MagicMock(return_value=cookies)

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "browser_cookie3":
                return mock_bc3
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        result = load_community_cookies()
        assert result is not None
        assert result["steamLoginSecure"] == valid_token

    def test_filters_unwanted_cookies(self, monkeypatch):
        valid_token = _make_token(["web:community"])
        mock_bc3 = MagicMock()
        cookies = [
            SimpleNamespace(name="steamLoginSecure", value=valid_token),
            SimpleNamespace(name="unwanted", value="nope"),
            SimpleNamespace(name="sessionid", value="abc"),
        ]
        mock_bc3.chrome = MagicMock(return_value=cookies)

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "browser_cookie3":
                return mock_bc3
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        result = load_community_cookies(browser="chrome")
        assert "unwanted" not in result
