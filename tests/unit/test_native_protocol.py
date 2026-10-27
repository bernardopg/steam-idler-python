"""Wire-level tests for the native backend: protobuf codec, packets, crypto, identity."""

from __future__ import annotations

import base64
import gzip
import struct

import pytest

from steam_idle_bot.steam.native import messages as m
from steam_idle_bot.steam.native.crypto import encrypt_password
from steam_idle_bot.steam.native.protobuf import ProtobufDecodeError, Repeated, Schema, decode, encode

INNER = Schema("Inner", {"name": (1, "string"), "n": (2, "uint32")})
ALL_TYPES = Schema(
    "AllTypes",
    {
        "i32": (1, "int32"),
        "i64": (2, "int64"),
        "u32": (3, "uint32"),
        "u64": (4, "uint64"),
        "flag": (5, "bool"),
        "kind": (6, "enum"),
        "f32": (7, "fixed32"),
        "f64": (8, "fixed64"),
        "real": (9, "float"),
        "text": (10, "string"),
        "blob": (11, "bytes"),
        "inner": (12, INNER),
        "items": (13, Repeated(INNER)),
        "nums": (14, Repeated("uint32")),
    },
)


# ---------------------------------------------------------------------------
# protobuf
# ---------------------------------------------------------------------------


def test_canonical_encodings_from_protobuf_docs():
    # https://protobuf.dev/programming-guides/encoding/ examples
    assert encode(Schema("T", {"a": (1, "int32")}), {"a": 150}) == b"\x08\x96\x01"
    assert encode(Schema("T", {"b": (2, "string")}), {"b": "testing"}) == b"\x12\x07testing"


def test_round_trip_every_supported_type():
    values = {
        "i32": -5,
        "i64": -(2**40),
        "u32": 4_000_000_000,
        "u64": 2**63 + 5,
        "flag": True,
        "kind": -203,
        "f32": 0xDEADBEEF,
        "f64": 76561198000000001,
        "real": 0.5,
        "text": "ação ✓",
        "blob": b"\x00\x01\xff",
        "inner": {"name": "x", "n": 3},
        "items": [{"name": "a"}, {"name": "b", "n": 2}],
        "nums": [1, 2, 300],
    }
    assert decode(ALL_TYPES, encode(ALL_TYPES, values)) == values


def test_negative_int32_uses_ten_byte_varint_and_uint32_is_masked():
    assert len(encode(Schema("T", {"a": (1, "int32")}), {"a": -1})) == 11
    encoded = encode(Schema("T", {"a": (1, "uint32")}), {"a": -203})
    assert decode(Schema("T", {"a": (1, "uint32")}), encoded) == {"a": (-203) & 0xFFFFFFFF}
    assert decode(Schema("T", {"a": (1, "int32")}), encoded) == {"a": -203}


def test_none_fields_are_omitted_and_unknown_fields_skipped():
    assert encode(ALL_TYPES, {"text": None}) == b""
    wide = encode(ALL_TYPES, {"text": "keep", "u32": 7, "f64": 1, "f32": 2, "blob": b"z"})
    narrow = Schema("Narrow", {"text": (10, "string")})
    assert decode(narrow, wide) == {"text": "keep"}


def test_packed_repeated_scalars_are_decoded():
    packed = b"\x72\x03\x01\x02\x03"  # field 14, wire type 2, payload [1, 2, 3]
    assert decode(ALL_TYPES, packed) == {"nums": [1, 2, 3]}


def test_encode_rejects_unknown_field():
    with pytest.raises(KeyError, match="no field"):
        encode(INNER, {"nope": 1})


@pytest.mark.parametrize(
    "data",
    [
        b"\x08",  # truncated varint
        b"\x12\x05ab",  # length beyond buffer
        b"\x09\x01\x02",  # truncated fixed64
        b"\x0d\x01",  # truncated fixed32
        b"\x0b",  # unsupported wire type 3 (start group)
        b"\x00\x01",  # field number 0
        b"\x08" + b"\xff" * 11,  # varint too long
    ],
)
def test_malformed_buffers_raise(data):
    with pytest.raises(ProtobufDecodeError):
        decode(ALL_TYPES, data)


# ---------------------------------------------------------------------------
# packets
# ---------------------------------------------------------------------------


def test_packet_round_trip_sets_protobuf_flag():
    frame = m.build_packet(m.EMsg.ClientHello, {"steamid": 1, "client_sessionid": -3}, m.CLIENT_HELLO, {"protocol_version": m.PROTOCOL_VERSION})
    raw_emsg, header_len = struct.unpack_from("<II", frame)
    assert raw_emsg == m.EMsg.ClientHello | 0x80000000
    packet = m.parse_packet(frame)
    assert packet.emsg == m.EMsg.ClientHello
    assert packet.header == {"steamid": 1, "client_sessionid": -3}
    assert decode(m.CLIENT_HELLO, packet.body) == {"protocol_version": m.PROTOCOL_VERSION}
    assert packet.eresult == m.EResult.Fail  # proto default when absent


@pytest.mark.parametrize(
    "frame, message",
    [
        (b"\x01\x02", "shorter"),
        (struct.pack("<II", 751, 0), "non-protobuf"),
        (struct.pack("<II", 751 | 0x80000000, 50), "truncated"),
        (struct.pack("<II", 751 | 0x80000000, 1) + b"\x0b", "bad protobuf header"),
    ],
)
def test_parse_packet_rejects_malformed_frames(frame, message):
    with pytest.raises(m.PacketError, match=message):
        m.parse_packet(frame)


def _multi(frames: list[bytes], *, gzipped: bool) -> bytes:
    payload = b"".join(struct.pack("<I", len(frame)) + frame for frame in frames)
    if gzipped:
        return encode(m.MULTI, {"size_unzipped": len(payload), "message_body": gzip.compress(payload)})
    return encode(m.MULTI, {"message_body": payload})


@pytest.mark.parametrize("gzipped", [False, True])
def test_unpack_multi(gzipped):
    frames = [m.build_packet(m.EMsg.ClientHeartBeat, {}, m.HEARTBEAT, {}), m.build_packet(m.EMsg.ClientLoggedOff, {}, m.CLIENT_LOGGED_OFF, {"eresult": 6})]
    assert m.unpack_multi(_multi(frames, gzipped=gzipped)) == frames


def test_unpack_multi_rejects_truncation_bad_gzip_and_bombs():
    with pytest.raises(m.PacketError, match="truncated Multi chunk"):
        m.unpack_multi(encode(m.MULTI, {"message_body": struct.pack("<I", 99) + b"x"}))
    with pytest.raises(m.PacketError, match="chunk length"):
        m.unpack_multi(encode(m.MULTI, {"message_body": b"\x01"}))
    with pytest.raises(m.PacketError, match="gzip"):
        m.unpack_multi(encode(m.MULTI, {"size_unzipped": 10, "message_body": b"not gzip"}))
    with pytest.raises(m.PacketError, match="too large"):
        m.unpack_multi(encode(m.MULTI, {"size_unzipped": 2**31, "message_body": b""}))
    with pytest.raises(m.PacketError, match="bad Multi"):
        m.unpack_multi(b"\x0b")
    with pytest.raises(m.PacketError, match="truncated stream"):
        m.unpack_multi(encode(m.MULTI, {"size_unzipped": 10, "message_body": gzip.compress(b"x" * 100)[:-12]}))


def test_unpack_multi_bounds_real_output_not_declared_size(monkeypatch):
    monkeypatch.setattr(m, "_MAX_MULTI_UNZIPPED", 1024)
    bomb = gzip.compress(b"\x00" * 10_000)  # lies: declares a tiny size
    with pytest.raises(m.PacketError, match="too large"):
        m.unpack_multi(encode(m.MULTI, {"size_unzipped": 10, "message_body": bomb}))


# ---------------------------------------------------------------------------
# identity helpers
# ---------------------------------------------------------------------------


def test_machine_id_matches_steam_session_layout():
    machine_id = m.machine_id_for("someone")
    assert machine_id.startswith(b"\x00MessageObject\x00\x01BB3\x00")
    assert machine_id.endswith(b"\x00\x08\x08")
    assert b"\x01FF2\x00" in machine_id and b"\x013B3\x00" in machine_id
    assert machine_id == m.machine_id_for("someone")
    assert machine_id != m.machine_id_for("other")
    # sha1("SteamUser Hash BB3 someone") as hex, as steam-session computes it
    import hashlib

    assert hashlib.sha1(b"SteamUser Hash BB3 someone").hexdigest().encode() in machine_id


def test_individual_steam_id_normalizes_instance_and_type():
    assert m.individual_steam_id(76561198000000001) == 76561198000000001
    web_instance = 76561198000000001 & ~(0xFFFFF << 32) | (4 << 32)  # same account, web instance 4
    assert m.individual_steam_id(web_instance) == 76561198000000001
    account_id = 12345
    assert m.individual_steam_id(account_id) == (1 << 56) | (1 << 52) | (1 << 32) | account_id


def test_decode_jwt_claims():
    from _native_fakes import make_jwt

    assert m.decode_jwt_claims(make_jwt({"sub": "1", "aud": ["client"]})) == {"sub": "1", "aud": ["client"]}
    with pytest.raises(ValueError):
        m.decode_jwt_claims("nope")
    with pytest.raises(ValueError):
        m.decode_jwt_claims("a." + base64.urlsafe_b64encode(b"[1]").decode() + ".c")


def test_eresult_describe():
    assert m.EResult.describe(5) == "InvalidPassword (5)"
    assert m.EResult.describe(99999) == "EResult 99999"


# ---------------------------------------------------------------------------
# RSA
# ---------------------------------------------------------------------------


def test_encrypt_password_decrypts_with_pkcs1_v15():
    rsa = pytest.importorskip("Cryptodome.PublicKey.RSA")
    from Cryptodome.Cipher import PKCS1_v1_5

    key = rsa.generate(2048)
    blobs = {encrypt_password("pässwörd 🔑", format(key.n, "x"), format(key.e, "x")) for _ in range(3)}
    assert len(blobs) == 3  # random padding: never the same ciphertext
    for blob in blobs:
        raw = base64.b64decode(blob)
        assert len(raw) == 256
        assert PKCS1_v1_5.new(key).decrypt(raw, None) == "pässwörd 🔑".encode()


def test_encrypt_password_validates_key_and_length():
    with pytest.raises(ValueError, match="malformed"):
        encrypt_password("x", "zz", "010001")
    with pytest.raises(ValueError, match="invalid"):
        encrypt_password("x", "00", "010001")
    with pytest.raises(ValueError, match="too long"):
        encrypt_password("x" * 300, "c" * 256, "010001")
