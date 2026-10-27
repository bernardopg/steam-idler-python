"""Steam CM protocol constants, message schemas and packet framing.

Field numbers come from the SteamDatabase/Protobufs dumps of the official
client (``steammessages_base.proto``, ``steammessages_clientserver*.proto``,
``steammessages_auth.steamclient.proto``); EMsg/EResult values from SteamKit's
``SteamLanguage`` definitions. Only the messages this bot needs are declared.

WebSocket CM framing (TLS replaces the legacy channel encryption): every
binary frame is one packet::

    uint32 LE  emsg | 0x80000000   (protobuf flag)
    uint32 LE  header length
    bytes      CMsgProtoBufHeader
    bytes      message body

``EMsg.Multi`` bodies bundle several packets, optionally gzip-compressed,
each prefixed by its uint32 LE length.
"""

from __future__ import annotations

__all__ = [
    "EMsg",
    "EResult",
    "EAuthSessionGuardType",
    "Packet",
    "PacketError",
    "PROTOCOL_VERSION",
    "build_packet",
    "parse_packet",
    "unpack_multi",
    "machine_id_for",
    "individual_steam_id",
    "decode_jwt_claims",
]

import base64
import hashlib
import json
import struct
import zlib
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from .protobuf import ProtobufDecodeError, Repeated, Schema, decode, encode

# Protocol version announced by node-steam-user / steam-session; SteamKit uses
# 65581. Both are accepted by the CMs.
PROTOCOL_VERSION = 65580
PROTO_MASK = 0x80000000
JOB_ID_NONE = 0xFFFFFFFFFFFFFFFF
_MAX_MULTI_UNZIPPED = 64 * 1024 * 1024  # refuse absurd gzip bombs


class EMsg(IntEnum):
    Multi = 1
    DestJobFailed = 113
    ServiceMethodResponse = 147
    ServiceMethodCallFromClient = 151
    ClientHeartBeat = 703
    ClientLogOff = 706
    ClientGamesPlayed = 742
    ClientLogOnResponse = 751
    ClientLoggedOff = 757
    ClientAccountInfo = 768
    ClientGamesPlayedWithDataBlob = 5410
    ClientLogon = 5514
    ClientPlayingSessionState = 9600
    ClientKickPlayingSession = 9601
    ServiceMethodCallFromClientNonAuthed = 9804
    ClientHello = 9805


class EResult(IntEnum):
    Invalid = 0
    OK = 1
    Fail = 2
    NoConnection = 3
    InvalidPassword = 5
    LoggedInElsewhere = 6
    InvalidProtocolVer = 7
    InvalidParam = 8
    FileNotFound = 9
    Busy = 10
    AccessDenied = 15
    Timeout = 16
    Banned = 17
    ServiceUnavailable = 20
    NotLoggedOn = 21
    Pending = 22
    LimitExceeded = 25
    Revoked = 26
    Expired = 27
    DuplicateRequest = 29
    LogonSessionReplaced = 34
    ConnectFailed = 35
    HandshakeFailed = 36
    IOFailure = 37
    RemoteDisconnect = 38
    AccountDisabled = 43
    TryAnotherCM = 48
    PasswordRequiredToKickSession = 49
    AlreadyLoggedInElsewhere = 50
    Suspended = 51
    Cancelled = 52
    AccountLogonDenied = 63
    InvalidLoginAuthCode = 65
    ExpiredLoginAuthCode = 71
    AccountLogonDeniedVerifiedEmailRequired = 74
    RateLimitExceeded = 84
    AccountLoginDeniedNeedTwoFactor = 85
    AccountLoginDeniedThrottle = 87
    TwoFactorCodeMismatch = 88
    InvalidSignature = 121

    @classmethod
    def describe(cls, value: int) -> str:
        try:
            return f"{cls(value).name} ({value})"
        except ValueError:
            return f"EResult {value}"


class EAuthSessionGuardType(IntEnum):
    Unknown = 0
    NoGuard = 1  # "None" in Valve's enum
    EmailCode = 2
    DeviceCode = 3
    DeviceConfirmation = 4
    EmailConfirmation = 5
    MachineToken = 6
    LegacyMachineAuth = 7


# EAuthTokenPlatformType / ESessionPersistence / ETokenRenewalType / EOSType
PLATFORM_STEAM_CLIENT = 1
SESSION_PERSISTENT = 1
TOKEN_RENEWAL_ALLOW = 1
OS_TYPE_WIN11 = 20
OS_TYPE_LINUX_UNKNOWN = -203
OS_TYPE_MACOS_UNKNOWN = -102


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

PROTO_HEADER = Schema(
    "CMsgProtoBufHeader",
    {
        "steamid": (1, "fixed64"),
        "client_sessionid": (2, "int32"),
        "routing_appid": (3, "uint32"),
        "jobid_source": (10, "fixed64"),
        "jobid_target": (11, "fixed64"),
        "target_job_name": (12, "string"),
        "eresult": (13, "int32"),
        "error_message": (14, "string"),
        "realm": (32, "uint32"),
    },
)

MULTI = Schema("CMsgMulti", {"size_unzipped": (1, "uint32"), "message_body": (2, "bytes")})
CLIENT_HELLO = Schema("CMsgClientHello", {"protocol_version": (1, "uint32")})
HEARTBEAT = Schema("CMsgClientHeartBeat", {"send_reply": (1, "bool")})
EMPTY = Schema("Empty", {})

CLIENT_LOGON = Schema(
    "CMsgClientLogon",
    {
        "protocol_version": (1, "uint32"),
        "cell_id": (3, "uint32"),
        "last_session_id": (4, "uint32"),
        "client_language": (6, "string"),
        "client_os_type": (7, "uint32"),
        "should_remember_password": (8, "bool"),
        "machine_id": (30, "bytes"),
        "chat_mode": (33, "uint32"),
        "account_name": (50, "string"),
        "supports_rate_limit_response": (102, "bool"),
        "machine_name": (96, "string"),
        "client_instance_id": (100, "uint64"),
        "access_token": (108, "string"),
    },
)

CLIENT_LOGON_RESPONSE = Schema(
    "CMsgClientLogonResponse",
    {
        "eresult": (1, "int32"),
        "heartbeat_seconds": (3, "int32"),
        "rtime32_server_time": (5, "fixed32"),
        "cell_id": (7, "uint32"),
        "eresult_extended": (10, "int32"),
        "vanity_url": (14, "string"),
        "client_supplied_steamid": (20, "fixed64"),
        "client_instance_id": (27, "uint64"),
    },
)

CLIENT_LOGGED_OFF = Schema("CMsgClientLoggedOff", {"eresult": (1, "int32")})
CLIENT_ACCOUNT_INFO = Schema("CMsgClientAccountInfo", {"persona_name": (1, "string")})

GAME_PLAYED = Schema("CMsgClientGamesPlayed.GamePlayed", {"game_id": (2, "fixed64"), "game_extra_info": (7, "string")})
CLIENT_GAMES_PLAYED = Schema(
    "CMsgClientGamesPlayed",
    {"games_played": (1, Repeated(GAME_PLAYED)), "client_os_type": (2, "uint32")},
)
PLAYING_SESSION_STATE = Schema("CMsgClientPlayingSessionState", {"playing_blocked": (2, "bool"), "playing_app": (3, "uint32")})

# --- IAuthenticationService ------------------------------------------------

AUTH_GET_RSA_REQUEST = Schema("CAuthentication_GetPasswordRSAPublicKey_Request", {"account_name": (1, "string")})
AUTH_GET_RSA_RESPONSE = Schema(
    "CAuthentication_GetPasswordRSAPublicKey_Response",
    {"publickey_mod": (1, "string"), "publickey_exp": (2, "string"), "timestamp": (3, "uint64")},
)
AUTH_DEVICE_DETAILS = Schema(
    "CAuthentication_DeviceDetails",
    {
        "device_friendly_name": (1, "string"),
        "platform_type": (2, "enum"),
        "os_type": (3, "int32"),
        "gaming_device_type": (4, "uint32"),
        "machine_id": (6, "bytes"),
    },
)
AUTH_BEGIN_REQUEST = Schema(
    "CAuthentication_BeginAuthSessionViaCredentials_Request",
    {
        "device_friendly_name": (1, "string"),
        "account_name": (2, "string"),
        "encrypted_password": (3, "string"),
        "encryption_timestamp": (4, "uint64"),
        "remember_login": (5, "bool"),
        "platform_type": (6, "enum"),
        "persistence": (7, "enum"),
        "website_id": (8, "string"),
        "device_details": (9, AUTH_DEVICE_DETAILS),
        "guard_data": (10, "string"),
        "language": (11, "uint32"),
    },
)
AUTH_ALLOWED_CONFIRMATION = Schema(
    "CAuthentication_AllowedConfirmation",
    {"confirmation_type": (1, "enum"), "associated_message": (2, "string")},
)
AUTH_BEGIN_RESPONSE = Schema(
    "CAuthentication_BeginAuthSessionViaCredentials_Response",
    {
        "client_id": (1, "uint64"),
        "request_id": (2, "bytes"),
        "interval": (3, "float"),
        "allowed_confirmations": (4, Repeated(AUTH_ALLOWED_CONFIRMATION)),
        "steamid": (5, "uint64"),
        "weak_token": (6, "string"),
        "agreement_session_url": (7, "string"),
        "extended_error_message": (8, "string"),
    },
)
AUTH_POLL_REQUEST = Schema(
    "CAuthentication_PollAuthSessionStatus_Request",
    {"client_id": (1, "uint64"), "request_id": (2, "bytes")},
)
AUTH_POLL_RESPONSE = Schema(
    "CAuthentication_PollAuthSessionStatus_Response",
    {
        "new_client_id": (1, "uint64"),
        "new_challenge_url": (2, "string"),
        "refresh_token": (3, "string"),
        "access_token": (4, "string"),
        "had_remote_interaction": (5, "bool"),
        "account_name": (6, "string"),
        "new_guard_data": (7, "string"),
    },
)
AUTH_UPDATE_GUARD_REQUEST = Schema(
    "CAuthentication_UpdateAuthSessionWithSteamGuardCode_Request",
    {"client_id": (1, "uint64"), "steamid": (2, "fixed64"), "code": (3, "string"), "code_type": (4, "enum")},
)
AUTH_GENERATE_TOKEN_REQUEST = Schema(
    "CAuthentication_AccessToken_GenerateForApp_Request",
    {"refresh_token": (1, "string"), "steamid": (2, "fixed64"), "renewal_type": (3, "enum")},
)
AUTH_GENERATE_TOKEN_RESPONSE = Schema(
    "CAuthentication_AccessToken_GenerateForApp_Response",
    {"access_token": (1, "string"), "refresh_token": (2, "string")},
)


# ---------------------------------------------------------------------------
# Packets
# ---------------------------------------------------------------------------


class PacketError(ValueError):
    """Raised for malformed CM packets."""


@dataclass
class Packet:
    emsg: int
    header: dict[str, Any] = field(default_factory=dict)
    body: bytes = b""

    @property
    def eresult(self) -> int:
        return int(self.header.get("eresult", EResult.Fail))


def build_packet(emsg: int, header: dict[str, Any], body_schema: Schema, body: dict[str, Any]) -> bytes:
    """Serialize one protobuf CM packet."""
    header_bytes = encode(PROTO_HEADER, header)
    return struct.pack("<II", (int(emsg) | PROTO_MASK) & 0xFFFFFFFF, len(header_bytes)) + header_bytes + encode(body_schema, body)


def parse_packet(data: bytes) -> Packet:
    """Parse one CM packet. Non-protobuf (legacy) packets are rejected."""
    if len(data) < 8:
        raise PacketError("packet shorter than its fixed header")
    raw_emsg, header_length = struct.unpack_from("<II", data, 0)
    if not raw_emsg & PROTO_MASK:
        raise PacketError(f"unexpected non-protobuf message {raw_emsg}")
    if 8 + header_length > len(data):
        raise PacketError("truncated protobuf header")
    try:
        header = decode(PROTO_HEADER, data[8 : 8 + header_length])
    except ProtobufDecodeError as exc:
        raise PacketError(f"bad protobuf header: {exc}") from exc
    return Packet(emsg=raw_emsg & ~PROTO_MASK, header=header, body=data[8 + header_length :])


def _gunzip_bounded(data: bytes, limit: int) -> bytes:
    """Gunzip *data*, refusing output beyond *limit* whatever the header claims."""
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = inflater.decompress(data, limit + 1)
    except zlib.error as exc:
        raise PacketError(f"bad gzip in Multi: {exc}") from exc
    if len(out) > limit or inflater.unconsumed_tail:
        raise PacketError("Multi payload too large")
    if not inflater.eof:
        raise PacketError("bad gzip in Multi: truncated stream")
    return out


def unpack_multi(body: bytes) -> list[bytes]:
    """Split an ``EMsg.Multi`` body into its inner packets."""
    try:
        multi = decode(MULTI, body)
    except ProtobufDecodeError as exc:
        raise PacketError(f"bad Multi body: {exc}") from exc
    payload = multi.get("message_body", b"")
    if multi.get("size_unzipped"):
        if multi["size_unzipped"] > _MAX_MULTI_UNZIPPED:
            raise PacketError("Multi payload too large")
        payload = _gunzip_bounded(payload, _MAX_MULTI_UNZIPPED)

    packets: list[bytes] = []
    pos = 0
    while pos < len(payload):
        if pos + 4 > len(payload):
            raise PacketError("truncated Multi chunk length")
        (size,) = struct.unpack_from("<I", payload, pos)
        pos += 4
        if pos + size > len(payload):
            raise PacketError("truncated Multi chunk")
        packets.append(payload[pos : pos + size])
        pos += size
    return packets


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------


def machine_id_for(account_name: str) -> bytes:
    """Deterministic per-account machine id, as the official client sends it.

    Binary KeyValues ``MessageObject{BB3, FF2, 3B3}`` of SHA-1 hex digests (the
    same construction as steam-session's ``createMachineId``). A stable id
    keeps Steam from treating every run as a brand-new device.
    """

    def kv_string(text: str) -> bytes:
        return text.encode("utf-8") + b"\x00"

    out = b"\x00" + kv_string("MessageObject")
    for key in ("BB3", "FF2", "3B3"):
        digest = hashlib.sha1(f"SteamUser Hash {key} {account_name}".encode()).hexdigest()  # noqa: S324 - identifier, not security
        out += b"\x01" + kv_string(key) + kv_string(digest)
    return out + b"\x08\x08"


def individual_steam_id(steam_id: int) -> int:
    """Normalize a SteamID64 to a desktop-instance individual account id."""
    account_id = steam_id & 0xFFFFFFFF
    universe = (steam_id >> 56) or 1
    return (universe << 56) | (1 << 52) | (1 << 32) | account_id


def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Return a JWT's claims WITHOUT verifying it (we only read sub/aud/exp).

    The signature cannot be checked client-side; Steam validates the token on
    use. This is only for local bookkeeping (expiry, account, audience).
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as exc:
        raise ValueError("not a JWT") from exc
    if not isinstance(claims, dict):
        raise ValueError("JWT claims are not an object")
    return claims
