# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Downstream service-token adapter with explicitly injected backend configuration."""

from contracts.constants.environment import JWT_SECRET
from contracts.errors.exceptions import TokenExpiredError
from infrastructure.security import service_tokens
from infrastructure.security.identity import IdentityError
from infrastructure.security.service_tokens import (
    INTERNAL_RUNTIME_JWT_AUDIENCE, INTERNAL_RUNTIME_JWT_ISSUER,
    INTERNAL_RUNTIME_JWT_SCOPE, INTERNAL_RUNTIME_JWT_TTL_SECONDS,
)


def generate_internal_runtime_jwt(user_id, tenant_id, expires_in=INTERNAL_RUNTIME_JWT_TTL_SECONDS):
    return service_tokens.generate_internal_runtime_jwt(user_id, tenant_id, expires_in, secret=JWT_SECRET)


def verify_internal_runtime_jwt(authorization, *, secret=None):
    try:
        return service_tokens.verify_internal_runtime_jwt(authorization, secret=JWT_SECRET if secret is None else secret)
    except IdentityError as exc:
        raise TokenExpiredError(str(exc)) from exc
