# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Sign individual AgentOS calls with a key separate from user credentials."""

import hashlib
import hmac
import time
from dataclasses import dataclass

import jwt

from contracts.agentos import AgentOSOperation
from contracts.constants import environment

_ISSUER = "nexent-management"
_AUDIENCE = "nexent-runtime-agentos"
_TTL_SECONDS = 30


class AgentOSIdentityError(ValueError):
    """An invalid AgentOS credential, without request details."""


@dataclass(frozen=True)
class ServicePrincipal:
    user_id: str
    tenant_id: str

    def __post_init__(self):
        for value in (self.user_id, self.tenant_id):
            if not isinstance(value, str) or not value.strip():
                raise AgentOSIdentityError("AgentOS requires a user and tenant")


def _signing_key() -> bytes:
    secret = environment.JWT_SECRET
    if not secret:
        raise AgentOSIdentityError("AgentOS signing is not configured")
    return hmac.digest(secret.encode(), b"nexent/agentos/v1/management-to-runtime", "sha256")


def sign_call(operation: AgentOSOperation, body: bytes, principal: ServicePrincipal) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "iat": now,
            "exp": now + _TTL_SECONDS,
            "sub": principal.user_id,
            "tenant": principal.tenant_id,
            "operation": operation.value,
            "body": hashlib.sha256(body).hexdigest(),
        },
        _signing_key(),
        algorithm="HS256",
    )


def verify_call(token: str, operation: AgentOSOperation, body: bytes) -> ServicePrincipal:
    try:
        claims = jwt.decode(
            token,
            _signing_key(),
            algorithms=["HS256"],
            audience=_AUDIENCE,
            issuer=_ISSUER,
            options={
                "strict_aud": True,
                "require": ["iss", "aud", "iat", "exp", "sub", "tenant", "operation", "body"],
            },
        )
        issued, expires = claims["iat"], claims["exp"]
        if (
            type(issued) is not int
            or type(expires) is not int
            or not 0 < expires - issued <= _TTL_SECONDS
            or claims["operation"] != operation.value
            or not isinstance(claims["body"], str)
            or not hmac.compare_digest(claims["body"], hashlib.sha256(body).hexdigest())
        ):
            raise AgentOSIdentityError("Invalid AgentOS credential")
        return ServicePrincipal(claims["sub"], claims["tenant"])
    except (jwt.InvalidTokenError, TypeError, ValueError) as exc:
        raise AgentOSIdentityError("Invalid AgentOS credential") from exc
