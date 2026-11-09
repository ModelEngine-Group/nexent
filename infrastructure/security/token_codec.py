# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit-key JWT primitives; callers retain their credential-purpose policy."""

import jwt

from infrastructure.security.identity import require_key


def encode_token(claims, *, key):
    return jwt.encode(claims, require_key(key), algorithm="HS256")


def decode_session(token, *, key, issuer):
    return jwt.decode(token, require_key(key), algorithms=["HS256"], audience="authenticated", issuer=issuer,
                      options={"require": ["sub", "exp", "iat", "ver"]})


def decode_lifetime(token, *, key):
    return jwt.decode(token, require_key(key), algorithms=["HS256"],
                      options={"verify_exp": False, "verify_aud": False})


def decode_pending(token, *, key):
    return jwt.decode(token, require_key(key), algorithms=["HS256"],
                      options={"verify_exp": True, "verify_aud": False})


def logout_session_id(token):
    """Read a revocation identifier only; these claims never grant access."""
    claims = jwt.decode(token, options={"verify_signature": False})
    return str(claims["sid"]) if claims.get("sid") else None
