# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Pure request-bound identity protocol shared by the service boundaries."""

import hashlib
import hmac
import time
import uuid

import jwt

from infrastructure.security.policy import canonical_path, is_public_request

IDENTITY_HEADER = "x-nexent-identity"
ISSUER = "nexent-gateway"
LOOKUP_PATH = "/internal/identity/resolve"
DELEGATION_PATH = "/internal/credentials/mcp"
TTL = 30


class IdentityError(ValueError):
    """Safe authentication failure without credentials or decoded token content."""


def bearer_token(authorization):
    if not authorization:
        return None
    if not isinstance(authorization, str):
        raise IdentityError("Invalid authorization header")
    parts = authorization.strip().split()
    if not parts:
        return None
    if len(parts) == 1 and parts[0].lower() != "bearer":
        return parts[0]
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    raise IdentityError("Invalid authorization header")


def _encode(scope, audience, extras, key):
    now = int(time.time())
    return jwt.encode({"iss": ISSUER, "aud": audience, "iat": now, "exp": now + TTL,
                       "jti": str(uuid.uuid4()), "scope": scope, **extras}, require_key(key), algorithm="HS256")


def _decode(token, audience, key):
    try:
        claims = jwt.decode(token, require_key(key), algorithms=["HS256"], issuer=ISSUER,
                            audience=audience, options={"require": ["iss", "aud", "iat", "exp", "jti", "scope"]})
        if (claims["aud"] != audience or type(claims["iat"]) is not int or type(claims["exp"]) is not int
                or not 0 < claims["exp"] - claims["iat"] <= TTL):
            raise IdentityError("Invalid identity lifetime")
        return claims
    except (jwt.InvalidTokenError, TypeError, ValueError) as exc:
        raise IdentityError("Invalid Gateway signature") from exc


def _binding(method, path, query):
    return hashlib.sha256(method.encode() + b"\n" + canonical_path(path).encode() + b"\n" + query).hexdigest()


def sign_identity(identity, audience, method, path, query, *, key=None):
    if audience not in {"management", "runtime", "mcp"}:
        raise IdentityError("Unknown identity audience")
    if identity is None and not is_public_request(method, path):
        raise IdentityError("Identity is required")
    return _encode("gateway:identity" if identity else "gateway:anonymous", audience,
                   {"identity": identity, "request": _binding(method, path, query)}, key)


def verify_identity(token, audience, method, path, query, *, key=None):
    claims = _decode(token, audience, key)
    if claims.get("request") != _binding(method, path, query):
        raise IdentityError("Identity request mismatch")
    identity = claims.get("identity")
    if claims["scope"] == "gateway:anonymous" and identity is None and is_public_request(method, path):
        return None
    if claims["scope"] != "gateway:identity" or not isinstance(identity, dict):
        raise IdentityError("Invalid identity scope")
    if any(not isinstance(identity.get(field), str) or not identity[field].strip()
           for field in ("user_id", "tenant_id")):
        raise IdentityError("Missing identity")
    if identity.get("kind") not in {"session", "api_key"}:
        raise IdentityError("Invalid credential policy")
    path = canonical_path(path)
    if not is_public_request(method, path):
        expected = "api_key" if path.startswith("/nb/") else "session"
        if identity["kind"] != expected:
            raise IdentityError("Credential policy mismatch")
    return identity


def sign_lookup(body: bytes, *, key=None):
    return _encode("identity:lookup", "management-identity", {"body": hashlib.sha256(body).hexdigest()}, key)


def verify_lookup(token, body: bytes, *, key=None):
    claims = _decode(token, "management-identity", key)
    if claims["scope"] != "identity:lookup" or claims.get("body") != hashlib.sha256(body).hexdigest():
        raise IdentityError("Invalid lookup signature")


def sign_delegation(body: bytes, *, key):
    return _encode("credentials:delegate", "gateway-credentials", {"body": hashlib.sha256(body).hexdigest()}, key)


def verify_delegation(token, body: bytes, *, key):
    claims = _decode(token, "gateway-credentials", key)
    if claims["scope"] != "credentials:delegate" or claims.get("body") != hashlib.sha256(body).hexdigest():
        raise IdentityError("Invalid delegation signature")


def require_key(key):
    """Pure protocol callers must supply their service-configured key."""
    if not isinstance(key, str) or not key:
        raise IdentityError("Gateway signing is not configured")
    return key


def derive_signing_key(master: str, dedicated: str = "") -> str:
    """Preserve the v1 domain separation without reading service configuration."""
    if dedicated:
        return require_key(dedicated)
    return hmac.new(require_key(master).encode(), b"nexent/gateway-identity/v1", hashlib.sha256).hexdigest()
