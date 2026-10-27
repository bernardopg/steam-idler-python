"""Persistent store for native-backend refresh tokens and Steam Guard data.

A Steam refresh token logs into the account for months without the password
or a Steam Guard code, so it is stored like the password: in a JSON file
written atomically with owner-only permissions (0600), never logged. Deleting
the file (or revoking the device under Steam > Account > Authorized devices)
forces a fresh password + Steam Guard login.
"""

from __future__ import annotations

__all__ = ["NativeSessionStore", "StoredSession"]

import contextlib
import json
import logging
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...config.settings import write_private_text
from .messages import decode_jwt_claims

logger = logging.getLogger(__name__)

_FORMAT_VERSION = 1
# Treat tokens that expire this soon as unusable; logon would fail mid-run.
_MIN_REMAINING_SECONDS = 3600


@dataclass(frozen=True)
class StoredSession:
    account_name: str
    steam_id: int
    refresh_token: str
    guard_data: str | None = None

    @property
    def expires_at(self) -> int | None:
        with contextlib.suppress(ValueError):
            exp = decode_jwt_claims(self.refresh_token).get("exp")
            return int(exp) if exp is not None else None
        return None


def refresh_token_problem(token: str, *, now: float | None = None) -> str | None:
    """Return why *token* cannot be used for a client logon, or None if usable."""
    try:
        claims = decode_jwt_claims(token)
    except ValueError:
        return "not a JWT"
    audience = claims.get("aud") or []
    if isinstance(audience, str):
        audience = [audience]
    if "client" not in audience:
        return "token is not valid for the Steam client"
    exp = claims.get("exp")
    current = time.time() if now is None else now
    if exp is not None and int(exp) - current < _MIN_REMAINING_SECONDS:
        return "token expired"
    if not str(claims.get("sub", "")).isdigit():
        return "token has no SteamID"
    return None


class NativeSessionStore:
    """JSON file of ``{account_name: {steam_id, refresh_token, guard_data}}``."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        self._tighten_permissions()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Ignoring unreadable native session file %s (%s); a fresh login will be required", self.path, exc)
            return {}
        accounts = data.get("accounts") if isinstance(data, dict) else None
        return accounts if isinstance(accounts, dict) else {}

    def _write(self, accounts: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _FORMAT_VERSION, "accounts": accounts}
        write_private_text(self.path, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def _tighten_permissions(self) -> None:
        """Fix a token file that is readable by other users (e.g. copied by hand)."""
        with contextlib.suppress(OSError):
            mode = stat.S_IMODE(self.path.stat().st_mode)
            if mode & 0o077:
                os.chmod(self.path, 0o600)
                logger.warning("Native session file %s was readable by other users; permissions reset to 0600", self.path)

    @staticmethod
    def _key(account_name: str) -> str:
        return account_name.strip().lower()

    def get(self, account_name: str) -> StoredSession | None:
        entry = self._read().get(self._key(account_name))
        if not isinstance(entry, dict):
            return None
        token = entry.get("refresh_token")
        steam_id = str(entry.get("steam_id") or "")
        if not isinstance(token, str) or not steam_id.isdigit():
            return None
        guard = entry.get("guard_data")
        return StoredSession(self._key(account_name), int(steam_id), token, guard if isinstance(guard, str) else None)

    def get_guard_data(self, account_name: str) -> str | None:
        """Steam Guard machine token, kept even after the refresh token is dropped."""
        entry = self._read().get(self._key(account_name))
        guard = entry.get("guard_data") if isinstance(entry, dict) else None
        return guard if isinstance(guard, str) and guard else None

    def save(self, account_name: str, steam_id: int, refresh_token: str, guard_data: str | None = None) -> None:
        accounts = self._read()
        key = self._key(account_name)
        existing = accounts.get(key)
        previous: dict[str, Any] = existing if isinstance(existing, dict) else {}
        accounts[key] = {
            "steam_id": str(steam_id),
            "refresh_token": refresh_token,
            "guard_data": guard_data or previous.get("guard_data"),
            "updated_at": int(time.time()),
        }
        self._write(accounts)

    def forget_token(self, account_name: str) -> None:
        """Drop the refresh token but keep the Steam Guard machine token."""
        accounts = self._read()
        entry = accounts.get(self._key(account_name))
        if not isinstance(entry, dict) or "refresh_token" not in entry:
            return
        entry.pop("refresh_token", None)
        self._write(accounts)
