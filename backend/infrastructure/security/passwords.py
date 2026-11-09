# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Native password hashing and explicitly bounded legacy bcrypt verification."""

import base64
import hashlib
import hmac
import re
import secrets

import bcrypt

_BCRYPT = re.compile(r"^\$2[aby]\$(0[4-9]|1[0-6])\$[./A-Za-z0-9]{53}$")
_MAX_PASSWORD_BYTES = 1024


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if not raw or len(raw) > _MAX_PASSWORD_BYTES:
        raise ValueError("Password must contain between 1 and 1024 UTF-8 bytes")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(raw, salt=salt, n=16384, r=8, p=1, dklen=32)
    return (
        "scrypt$16384$8$1$"
        + base64.b64encode(salt).decode()
        + "$"
        + base64.b64encode(digest).decode()
    )


def password_scheme(encoded: str) -> str:
    if _BCRYPT.fullmatch(encoded or ""):
        return "bcrypt"
    if (encoded or "").startswith("scrypt$16384$8$1$"):
        parts = encoded.split("$")
        if len(parts) == 6:
            try:
                if (
                    len(base64.b64decode(parts[4], validate=True)) == 16
                    and len(base64.b64decode(parts[5], validate=True)) == 32
                ):
                    return "scrypt"
            except ValueError:
                pass
    raise ValueError("Unsupported password hash format")


def verify_password(password: str, encoded: str) -> bool:
    raw = password.encode("utf-8")
    if not raw or len(raw) > _MAX_PASSWORD_BYTES:
        return False
    try:
        if password_scheme(encoded) == "bcrypt":
            # Historical bcrypt credentials used the first 72 bytes.
            return bcrypt.checkpw(raw[:72], encoded.encode("ascii"))
        parts = encoded.split("$")
        digest = hashlib.scrypt(
            raw, salt=base64.b64decode(parts[4]), n=16384, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(digest, base64.b64decode(parts[5]))
    except (ValueError, TypeError, UnicodeError):
        return False
