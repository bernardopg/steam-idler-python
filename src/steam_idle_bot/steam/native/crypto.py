"""RSA password encryption for Steam's ``IAuthenticationService``.

Steam hands out a per-account RSA public key (hex modulus/exponent) and expects
the password encrypted with RSAES-PKCS1-v1_5, base64-encoded. That is a single
modular exponentiation over a padded block, so it is implemented here with the
standard library instead of adding a crypto dependency. Only *encryption* with
a public key happens client-side, so there is no private-key handling and no
padding oracle to worry about.
"""

from __future__ import annotations

__all__ = ["encrypt_password"]

import base64
import secrets


def _nonzero_random_bytes(length: int) -> bytes:
    out = bytearray()
    while len(out) < length:
        out.extend(byte for byte in secrets.token_bytes(length - len(out)) if byte)
    return bytes(out)


def encrypt_password(password: str, modulus_hex: str, exponent_hex: str) -> str:
    """Return ``base64(RSAES-PKCS1-v1_5(password))`` for Steam's RSA key."""
    try:
        modulus = int(modulus_hex, 16)
        exponent = int(exponent_hex, 16)
    except (TypeError, ValueError) as exc:
        raise ValueError("Steam returned a malformed RSA public key") from exc
    if modulus <= 0 or exponent <= 1:
        raise ValueError("Steam returned an invalid RSA public key")

    key_length = (modulus.bit_length() + 7) // 8
    message = password.encode("utf-8")
    if len(message) > key_length - 11:
        raise ValueError("password is too long for Steam's RSA key")

    # EM = 0x00 || 0x02 || PS (non-zero random, >= 8 bytes) || 0x00 || M   (RFC 8017 §7.2.1)
    padding = _nonzero_random_bytes(key_length - len(message) - 3)
    block = b"\x00\x02" + padding + b"\x00" + message
    cipher = pow(int.from_bytes(block, "big"), exponent, modulus)
    return base64.b64encode(cipher.to_bytes(key_length, "big")).decode("ascii")
