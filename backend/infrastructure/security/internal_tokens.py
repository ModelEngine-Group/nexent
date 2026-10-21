# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from typing import Optional
from consts.const import SUPABASE_JWT_SECRET
from consts.exceptions import TokenExpiredError
import jwt
import time

INTERNAL_RUNTIME_JWT_ISSUER = "nexent-northbound"


INTERNAL_RUNTIME_JWT_AUDIENCE = "nexent-runtime"


INTERNAL_RUNTIME_JWT_SCOPE = "northbound:runtime"


INTERNAL_RUNTIME_JWT_TTL_SECONDS = 60


def generate_internal_runtime_jwt(
    user_id: str,
    tenant_id: str,
    expires_in: int = INTERNAL_RUNTIME_JWT_TTL_SECONDS,
) -> str:
    """Generate a short-lived token for northbound-to-runtime requests."""
    if not SUPABASE_JWT_SECRET:
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
    return jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")


def verify_internal_runtime_jwt(authorization: Optional[str]) -> tuple[str, str]:
    """Verify a northbound runtime token and return its user and tenant."""
    if not SUPABASE_JWT_SECRET:
        raise TokenExpiredError("JWT verification is not configured")
    if not authorization or not authorization.strip():
        raise TokenExpiredError("No authorization header provided")

    token = (
        authorization.replace("Bearer ", "", 1)
        if authorization.startswith("Bearer ")
        else authorization
    )
    try:
        claims = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience=INTERNAL_RUNTIME_JWT_AUDIENCE,
            issuer=INTERNAL_RUNTIME_JWT_ISSUER,
            options={"verify_exp": True},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Internal runtime token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenExpiredError("Invalid internal runtime token") from exc

    if claims.get("scope") != INTERNAL_RUNTIME_JWT_SCOPE:
        raise TokenExpiredError("Invalid internal runtime token scope")

    user_id = claims.get("sub")
    tenant_id = claims.get("tenant_id")
    if not isinstance(user_id, str) or not user_id.strip():
        raise TokenExpiredError("Internal runtime token is missing user identity")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise TokenExpiredError("Internal runtime token is missing tenant identity")
    return user_id, tenant_id
