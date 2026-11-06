# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from typing import Optional
from contracts.constants.environment import JWT_SECRET
from contracts.errors.exceptions import TokenExpiredError
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
    if not JWT_SECRET:
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
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")
