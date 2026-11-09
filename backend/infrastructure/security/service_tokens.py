# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import time
from typing import Optional

import jwt

from infrastructure.security.identity import IdentityError, bearer_token

INTERNAL_RUNTIME_JWT_ISSUER = "nexent-northbound"
INTERNAL_RUNTIME_JWT_AUDIENCE = "nexent-runtime"
INTERNAL_RUNTIME_JWT_SCOPE = "northbound:runtime"
INTERNAL_RUNTIME_JWT_TTL_SECONDS = 60


def generate_internal_runtime_jwt(
    user_id: str,
    tenant_id: str,
    expires_in: int = INTERNAL_RUNTIME_JWT_TTL_SECONDS,
    *, secret=None,
) -> str:
    """Generate a short-lived token for northbound-to-runtime requests."""
    if not secret:
        raise ValueError("JWT verification is not configured")
    if not user_id or not tenant_id:
        raise ValueError("user_id and tenant_id are required")

    now = int(time.time())
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "scope": INTERNAL_RUNTIME_JWT_SCOPE,
        "iss": INTERNAL_RUNTIME_JWT_ISSUER,
        "aud": INTERNAL_RUNTIME_JWT_AUDIENCE,
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_internal_runtime_jwt(authorization: Optional[str], *, secret=None) -> tuple[str, str]:
    """Verify a northbound runtime token and return its user and tenant."""
    key = secret
    if not key:
        raise IdentityError("JWT verification is not configured")
    if not authorization or not authorization.strip():
        raise IdentityError("No authorization header provided")

    try:
        token = bearer_token(authorization)
    except IdentityError as exc:
        raise IdentityError("Invalid authorization header") from exc
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            audience=INTERNAL_RUNTIME_JWT_AUDIENCE,
            issuer=INTERNAL_RUNTIME_JWT_ISSUER,
            options={"verify_exp": True, "require": ["exp", "iat", "iss", "aud", "scope"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise IdentityError("Internal runtime token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise IdentityError("Invalid internal runtime token") from exc

    if claims.get("scope") != INTERNAL_RUNTIME_JWT_SCOPE:
        raise IdentityError("Invalid internal runtime token scope")

    user_id = claims.get("sub")
    tenant_id = claims.get("tenant_id")
    if not isinstance(user_id, str) or not user_id.strip():
        raise IdentityError("Internal runtime token is missing user identity")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise IdentityError("Internal runtime token is missing tenant identity")
    return user_id, tenant_id
