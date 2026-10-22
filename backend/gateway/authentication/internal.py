# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Optional

import jwt
from consts.const import SUPABASE_JWT_SECRET
from contracts.errors.exceptions import TokenExpiredError
from gateway.authentication.credentials import extract_bearer_token
from infrastructure.security.internal_tokens import INTERNAL_RUNTIME_JWT_AUDIENCE, INTERNAL_RUNTIME_JWT_ISSUER, INTERNAL_RUNTIME_JWT_SCOPE


def verify_internal_runtime_jwt(authorization: Optional[str]) -> tuple[str, str]:
    """Verify a northbound runtime token and return its user and tenant."""
    if not SUPABASE_JWT_SECRET:
        raise TokenExpiredError("JWT verification is not configured")
    if not authorization or not authorization.strip():
        raise TokenExpiredError("No authorization header provided")

    token = extract_bearer_token(authorization)
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
