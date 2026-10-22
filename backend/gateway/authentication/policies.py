# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit credential policies returning the same authenticated identity."""

from typing import Optional

from contracts.authentication import AuthenticatedIdentity, CredentialKind
from contracts.errors.exceptions import TokenExpiredError
from gateway.authentication.credentials import extract_bearer_token


def authenticate_identity(
    authorization: Optional[str],
    kind: CredentialKind = CredentialKind.SESSION,
    request=None,
    *,
    require_role: bool = False,
) -> AuthenticatedIdentity:
    """Use the route's policy; never infer a policy from unverified claims."""
    from gateway.authentication import identity

    if kind == CredentialKind.SESSION:
        if require_role:
            user_id, tenant_id, role = identity.get_current_user_context(authorization)
        else:
            user_id, tenant_id = identity._resolve_session_user(authorization)
            role = "SPEED" if identity.IS_SPEED_MODE else ""
        return AuthenticatedIdentity(
            user_id,
            tenant_id,
            role=role,
            language=identity.get_user_language(request),
            kind=kind,
        )
    if kind == CredentialKind.API_KEY:
        valid, record = identity.validate_bearer_token(authorization)
        if not valid or not record:
            raise TokenExpiredError("Invalid or missing bearer token")
        resolved = identity.get_user_and_tenant_by_access_key(
            extract_bearer_token(authorization)
        )
        return AuthenticatedIdentity(
            resolved.get("user_id") or "",
            resolved.get("tenant_id") or "",
            token_id=resolved.get("token_id"),
            language=identity.get_user_language(request),
            kind=kind,
        )
    if kind == CredentialKind.INTERNAL:
        from gateway.authentication.internal import verify_internal_runtime_jwt

        user_id, tenant_id = verify_internal_runtime_jwt(authorization)
        return AuthenticatedIdentity(user_id, tenant_id, kind=kind)
    raise ValueError("Unsupported authentication policy")
