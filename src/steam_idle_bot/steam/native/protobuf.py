"""Minimal protobuf wire-format codec for the handful of Steam messages we use.

The native backend deliberately avoids the ``protobuf`` package: the legacy
``steam`` library pins it below 4 (with open advisories), and protoc-generated
modules would tie this backend to that pin. Steam messages are plain proto2
messages, so a schema-driven encoder/decoder of ~150 lines covers everything
needed. Unknown fields are skipped on decode, which keeps the codec tolerant
of fields Valve adds later.

A schema maps a field name to ``(field_number, field_type)``. Supported types:
``int32``, ``int64``, ``uint32``, ``uint64``, ``bool``, ``enum``, ``fixed32``,
``fixed64``, ``float``, ``string``, ``bytes``, a nested ``Schema``, or
``Repeated(<type>)`` for repeated (non-packed on encode, either on decode)
fields.
"""

from __future__ import annotations

__all__ = ["Repeated", "Schema", "ProtobufDecodeError", "decode", "encode"]

import struct
from dataclasses import dataclass
from typing import Any

_WIRE_VARINT = 0
_WIRE_FIXED64 = 1
_WIRE_LENGTH = 2
_WIRE_FIXED32 = 5

_VARINT_TYPES = frozenset({"int32", "int64", "uint32", "uint64", "bool", "enum"})
_MASK64 = (1 << 64) - 1


class ProtobufDecodeError(ValueError):
    """Raised when a buffer is not a well-formed protobuf message."""


@dataclass(frozen=True)
class Repeated:
    """Marks a repeated field of the wrapped type."""

    item_type: FieldType


@dataclass(frozen=True)
class Schema:
    """A protobuf message layout: ``{name: (number, type)}``."""

    name: str
    fields: dict[str, tuple[int, FieldType]]

    def by_number(self) -> dict[int, tuple[str, FieldType]]:
        return {number: (name, field_type) for name, (number, field_type) in self.fields.items()}


FieldType = str | Schema | Repeated


# ---------------------------------------------------------------------------
# Varints
# ---------------------------------------------------------------------------


def _encode_varint(value: int) -> bytes:
    value &= _MASK64  # negative ints are sent as 10-byte two's complement
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise ProtobufDecodeError("truncated varint")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result & _MASK64, pos
        shift += 7
        if shift >= 70:
            raise ProtobufDecodeError("varint too long")


def _to_signed(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------


def _encode_scalar(number: int, field_type: FieldType, value: Any) -> bytes:
    if isinstance(field_type, Schema):
        payload = encode(field_type, value)
        return _encode_varint(number << 3 | _WIRE_LENGTH) + _encode_varint(len(payload)) + payload
    if field_type == "uint32":
        # Valve stores negative enums (e.g. EOSType) in uint32 fields as 32-bit two's complement.
        return _encode_varint(number << 3 | _WIRE_VARINT) + _encode_varint(int(value) & 0xFFFFFFFF)
    if field_type in _VARINT_TYPES:
        return _encode_varint(number << 3 | _WIRE_VARINT) + _encode_varint(int(value))
    if field_type == "fixed64":
        return _encode_varint(number << 3 | _WIRE_FIXED64) + struct.pack("<Q", int(value) & _MASK64)
    if field_type == "fixed32":
        return _encode_varint(number << 3 | _WIRE_FIXED32) + struct.pack("<I", int(value) & 0xFFFFFFFF)
    if field_type == "float":
        return _encode_varint(number << 3 | _WIRE_FIXED32) + struct.pack("<f", float(value))
    if field_type in ("string", "bytes"):
        payload = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        return _encode_varint(number << 3 | _WIRE_LENGTH) + _encode_varint(len(payload)) + payload
    raise TypeError(f"unsupported protobuf field type: {field_type!r}")


def encode(schema: Schema, values: dict[str, Any]) -> bytes:
    """Serialize *values* (fields set to ``None`` are omitted) with *schema*."""
    out = bytearray()
    for name, value in values.items():
        if value is None:
            continue
        try:
            number, field_type = schema.fields[name]
        except KeyError:
            raise KeyError(f"{schema.name} has no field {name!r}") from None
        if isinstance(field_type, Repeated):
            for item in value:
                out += _encode_scalar(number, field_type.item_type, item)
        else:
            out += _encode_scalar(number, field_type, value)
    return bytes(out)


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------


def _convert_varint(field_type: FieldType, raw: int) -> Any:
    if field_type == "bool":
        return raw != 0
    if field_type == "int32" or field_type == "enum":
        return _to_signed(raw, 32)
    if field_type == "int64":
        return _to_signed(raw, 64)
    if field_type == "uint32":
        return raw & 0xFFFFFFFF
    return raw


def _decode_length_delimited(field_type: FieldType, payload: bytes) -> Any:
    if isinstance(field_type, Schema):
        return decode(field_type, payload)
    if field_type == "string":
        return payload.decode("utf-8", errors="replace")
    if field_type == "bytes":
        return payload
    raise ProtobufDecodeError(f"length-delimited data for scalar type {field_type!r}")


def _unpack_packed(item_type: FieldType, payload: bytes) -> list[Any]:
    values: list[Any] = []
    pos = 0
    while pos < len(payload):
        if item_type in _VARINT_TYPES:
            raw, pos = _decode_varint(payload, pos)
            values.append(_convert_varint(item_type, raw))
        elif item_type in ("fixed32", "float"):
            values.append(struct.unpack_from("<f" if item_type == "float" else "<I", payload, pos)[0])
            pos += 4
        elif item_type == "fixed64":
            values.append(struct.unpack_from("<Q", payload, pos)[0])
            pos += 8
        else:
            raise ProtobufDecodeError(f"cannot unpack packed {item_type!r}")
    return values


def decode(schema: Schema, data: bytes) -> dict[str, Any]:
    """Parse *data* with *schema*; unknown fields are skipped."""
    fields = schema.by_number()
    result: dict[str, Any] = {}
    pos = 0
    length = len(data)
    while pos < length:
        key, pos = _decode_varint(data, pos)
        number, wire_type = key >> 3, key & 0x7
        if number == 0:
            raise ProtobufDecodeError("field number 0")

        if wire_type == _WIRE_VARINT:
            raw: Any
            raw, pos = _decode_varint(data, pos)
        elif wire_type == _WIRE_FIXED64:
            if pos + 8 > length:
                raise ProtobufDecodeError("truncated fixed64")
            raw = data[pos : pos + 8]
            pos += 8
        elif wire_type == _WIRE_LENGTH:
            size, pos = _decode_varint(data, pos)
            if pos + size > length:
                raise ProtobufDecodeError("truncated length-delimited field")
            raw = data[pos : pos + size]
            pos += size
        elif wire_type == _WIRE_FIXED32:
            if pos + 4 > length:
                raise ProtobufDecodeError("truncated fixed32")
            raw = data[pos : pos + 4]
            pos += 4
        else:
            raise ProtobufDecodeError(f"unsupported wire type {wire_type}")

        if number not in fields:
            continue
        name, field_type = fields[number]
        repeated = isinstance(field_type, Repeated)
        item_type = field_type.item_type if isinstance(field_type, Repeated) else field_type

        if repeated and wire_type == _WIRE_LENGTH and not isinstance(item_type, Schema) and item_type not in ("string", "bytes"):
            result.setdefault(name, []).extend(_unpack_packed(item_type, raw))
            continue

        if wire_type == _WIRE_VARINT:
            value = _convert_varint(item_type, raw)
        elif wire_type == _WIRE_FIXED64:
            value = struct.unpack("<d" if item_type == "double" else "<Q", raw)[0]
        elif wire_type == _WIRE_FIXED32:
            value = struct.unpack("<f" if item_type == "float" else "<I", raw)[0]
        else:
            value = _decode_length_delimited(item_type, raw)

        if repeated:
            result.setdefault(name, []).append(value)
        else:
            result[name] = value
    return result
