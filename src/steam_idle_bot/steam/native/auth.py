"""Steam's modern credential login (``IAuthenticationService``) over a CM.

Flow, as the official client does it for ``EAuthTokenPlatformType.SteamClient``:

1. ``GetPasswordRSAPublicKey`` → RSA-encrypt the password.
2. ``BeginAuthSessionViaCredentials`` → which Steam Guard confirmations apply.
3. Submit an e-mail / mobile code (``UpdateAuthSessionWithSteamGuardCode``),
   or wait for an in-app approval, or nothing when a machine token or no
   guard applies.
4. ``PollAuthSessionStatus`` until Steam issues a refresh token.

The refresh token (audience ``client``) is then used as ``access_token`` in
``CMsgClientLogon``; the password is never sent again until it expires.
"""

from __future__ import annotations

__all__ = ["AuthCodeProvider", "AuthResult", "authenticate_with_credentials", "explain_login_failure"]

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from ...utils.exceptions import SteamAuthenticationError
from .cm import CMConnection, ServiceResponse
from .crypto import encrypt_password
from .messages import (
    AUTH_BEGIN_REQUEST,
    AUTH_BEGIN_RESPONSE,
    AUTH_GET_RSA_REQUEST,
    AUTH_GET_RSA_RESPONSE,
    AUTH_POLL_REQUEST,
    AUTH_POLL_RESPONSE,
    AUTH_UPDATE_GUARD_REQUEST,
    EMPTY,
    OS_TYPE_WIN11,
    PLATFORM_STEAM_CLIENT,
    SESSION_PERSISTENT,
    EAuthSessionGuardType,
    EResult,
    machine_id_for,
)

logger = logging.getLogger(__name__)

# (is_2fa, code_mismatch) -> code, or None/"" to cancel. Same contract as the
# python backend, so the CLI prompt and the web UI dialog work unchanged.
AuthCodeProvider = Callable[[bool, bool], str | None]

DEVICE_FRIENDLY_NAME = "Steam Idle Bot"
_MAX_CODE_ATTEMPTS = 3
_DEFAULT_POLL_INTERVAL = 5.0
_POLL_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class AuthResult:
    account_name: str
    steam_id: int
    refresh_token: str
    guard_data: str | None


def explain_login_failure(eresult: int, error_message: str = "") -> str:
    """Human explanation for a failed login/auth step."""
    hints: dict[int, str] = {
        EResult.InvalidPassword: "Steam rejected the username or password. Check USERNAME/PASSWORD; repeated failures trigger a temporary login throttle.",
        EResult.RateLimitExceeded: "Too many login attempts from this IP. Wait about 30 minutes before trying again.",
        EResult.AccountLoginDeniedThrottle: "Steam is throttling logins for this account. Wait about 30 minutes before trying again.",
        EResult.AccountDisabled: "This Steam account is disabled.",
        EResult.Banned: "This Steam account or IP is banned from logging in.",
        EResult.InvalidLoginAuthCode: "The e-mail Steam Guard code was rejected.",
        EResult.TwoFactorCodeMismatch: "The Steam Mobile code was rejected.",
        EResult.ExpiredLoginAuthCode: "The Steam Guard code expired; request a new one.",
        EResult.Expired: "The login session expired before it was confirmed.",
        EResult.ServiceUnavailable: "Steam's login service is temporarily unavailable.",
    }
    try:
        name = EResult(eresult).name
    except ValueError:
        name = f"EResult {eresult}"
    detail = hints.get(eresult, f"Steam login failed ({name}).")
    return f"{detail} [{name}]" + (f" {error_message}" if error_message else "")


def _require_ok(response: ServiceResponse, step: str) -> None:
    if not response.ok:
        raise SteamAuthenticationError(f"{step}: {explain_login_failure(response.eresult, response.error_message)}")


def authenticate_with_credentials(
    connection: CMConnection,
    account_name: str,
    password: str,
    *,
    code_provider: AuthCodeProvider,
    guard_data: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] = lambda: False,
    poll_timeout: float = _POLL_TIMEOUT_SECONDS,
) -> AuthResult:
    """Run the credential login and return a fresh refresh token."""
    rsa = connection.call_service("Authentication.GetPasswordRSAPublicKey#1", AUTH_GET_RSA_REQUEST, {"account_name": account_name}, AUTH_GET_RSA_RESPONSE)
    _require_ok(rsa, "Fetching Steam's RSA key")
    try:
        encrypted = encrypt_password(password, rsa.body.get("publickey_mod", ""), rsa.body.get("publickey_exp", ""))
    except ValueError as exc:
        raise SteamAuthenticationError(str(exc)) from exc

    begin = connection.call_service(
        "Authentication.BeginAuthSessionViaCredentials#1",
        AUTH_BEGIN_REQUEST,
        {
            "device_friendly_name": DEVICE_FRIENDLY_NAME,
            "account_name": account_name,
            "encrypted_password": encrypted,
            "encryption_timestamp": int(rsa.body.get("timestamp", 0)),
            "remember_login": True,
            "platform_type": PLATFORM_STEAM_CLIENT,
            "persistence": SESSION_PERSISTENT,
            "website_id": "Unknown",
            "device_details": {
                "device_friendly_name": DEVICE_FRIENDLY_NAME,
                "platform_type": PLATFORM_STEAM_CLIENT,
                "os_type": OS_TYPE_WIN11,
                "gaming_device_type": 1,
                "machine_id": machine_id_for(account_name),
            },
            "guard_data": guard_data,
        },
        AUTH_BEGIN_RESPONSE,
    )
    _require_ok(begin, "Starting the Steam login")

    client_id = int(begin.body.get("client_id", 0))
    request_id = begin.body.get("request_id", b"")
    steam_id = int(begin.body.get("steamid", 0))
    interval = float(begin.body.get("interval") or _DEFAULT_POLL_INTERVAL)
    confirmations = {int(item.get("confirmation_type", 0)) for item in begin.body.get("allowed_confirmations", [])}
    logger.debug("Steam Guard confirmations allowed: %s", sorted(confirmations))

    if confirmations & {EAuthSessionGuardType.NoGuard, EAuthSessionGuardType.MachineToken}:
        logger.info("Steam accepted this device without a new Steam Guard code")
    elif EAuthSessionGuardType.DeviceCode in confirmations:
        _submit_guard_code(connection, client_id, steam_id, EAuthSessionGuardType.DeviceCode, code_provider)
    elif EAuthSessionGuardType.EmailCode in confirmations:
        _submit_guard_code(connection, client_id, steam_id, EAuthSessionGuardType.EmailCode, code_provider)
    elif confirmations & {EAuthSessionGuardType.DeviceConfirmation, EAuthSessionGuardType.EmailConfirmation}:
        logger.warning("Approve this login in the Steam Mobile app (or the e-mail link). Waiting up to %d s...", int(poll_timeout))
    else:
        raise SteamAuthenticationError(f"Steam requires an unsupported confirmation type {sorted(confirmations)}")

    return _poll_for_tokens(connection, account_name, client_id, request_id, steam_id, interval, sleep, should_stop, poll_timeout)


def _submit_guard_code(
    connection: CMConnection,
    client_id: int,
    steam_id: int,
    code_type: EAuthSessionGuardType,
    code_provider: AuthCodeProvider,
) -> None:
    is_2fa = code_type == EAuthSessionGuardType.DeviceCode
    mismatch = False
    for _ in range(_MAX_CODE_ATTEMPTS):
        code = code_provider(is_2fa, mismatch)
        if not code or not code.strip():
            raise SteamAuthenticationError("Authentication code entry cancelled")
        response = connection.call_service(
            "Authentication.UpdateAuthSessionWithSteamGuardCode#1",
            AUTH_UPDATE_GUARD_REQUEST,
            {"client_id": client_id, "steamid": steam_id, "code": code.strip().upper(), "code_type": int(code_type)},
            EMPTY,
        )
        if response.ok or response.eresult == EResult.DuplicateRequest:
            return
        if response.eresult in (EResult.TwoFactorCodeMismatch, EResult.InvalidLoginAuthCode):
            mismatch = True
            continue
        _require_ok(response, "Submitting the Steam Guard code")
    raise SteamAuthenticationError(f"Steam Guard code rejected {_MAX_CODE_ATTEMPTS} times; stopping to avoid a login throttle")


def _poll_for_tokens(
    connection: CMConnection,
    account_name: str,
    client_id: int,
    request_id: bytes,
    steam_id: int,
    interval: float,
    sleep: Callable[[float], None],
    should_stop: Callable[[], bool],
    poll_timeout: float,
) -> AuthResult:
    deadline = time.monotonic() + poll_timeout
    while True:
        poll = connection.call_service("Authentication.PollAuthSessionStatus#1", AUTH_POLL_REQUEST, {"client_id": client_id, "request_id": request_id}, AUTH_POLL_RESPONSE)
        _require_ok(poll, "Waiting for the Steam login")
        if poll.body.get("new_client_id"):
            client_id = int(poll.body["new_client_id"])
        token = poll.body.get("refresh_token")
        if token:
            return AuthResult(
                account_name=str(poll.body.get("account_name") or account_name),
                steam_id=steam_id,
                refresh_token=str(token),
                guard_data=poll.body.get("new_guard_data") or None,
            )
        if should_stop():
            raise SteamAuthenticationError("Login cancelled")
        if time.monotonic() >= deadline:
            raise SteamAuthenticationError("Timed out waiting for the Steam login to be confirmed")
        sleep(interval)
