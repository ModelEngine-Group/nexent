# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Action-specific operations scope; never expands ordinary business scope."""

from fastapi import HTTPException, Request

from contracts.errors.exceptions import TokenExpiredError, UnauthorizedError
from gateway.authentication.auth import get_current_user_context
from permissions.models import CurrentUser
from permissions.rbac import has_permission

ACTIONS = ("read", "create", "update", "delete")


def operations_scope(user, tenant_id=None, permission="ops.dashboard:read"):
    roles = user.effective_roles
    if not has_permission(roles, permission) or not set(roles) & {"OPS", "SU"}:
        raise HTTPException(status_code=403, detail="Operations permission required")
    if "SU" in roles:
        return tenant_id
    if tenant_id is not None and tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="Operations are limited to your tenant")
    return user.tenant_id


def authorization_metadata(user):
    operations_scope(user)
    return {
        "scope": "all_tenants" if "SU" in user.effective_roles else "current_tenant",
        "tenant_id": user.tenant_id,
        "permissions": {
            module: [action for action in ACTIONS if has_permission(user.effective_roles, f"ops.{module}:{action}")]
            for module in ("dashboard", "configuration")
        },
    }


def resource_read_tenant(request: Request | None, *, shared: bool = False) -> str | None:
    """Resolve the tenant for a route that offers inventory reads."""
    authorization = request.headers.get("authorization") if request is not None else None
    if not authorization:
        return None
    try:
        _, tenant_id, roles = get_current_user_context(authorization)
    except (UnauthorizedError, TokenExpiredError):
        return None

    if {"ADMIN", "SU"}.intersection(roles) or not has_permission(roles, "resource.inventory:read"):
        return None
    targets = request.query_params.getlist("tenant_id")
    if shared and len(roles) > 1 and not any(targets):
        return None
    if not tenant_id or any(target and target != tenant_id for target in targets):
        raise HTTPException(status_code=403, detail="Resource reads are limited to your tenant")
    return tenant_id


def tenant_scope(user: CurrentUser, requested_tenant: str | None = None) -> str | None:
    """Resolve a resource tenant with the same rule for every account."""
    if "SU" in user.effective_roles:
        return requested_tenant
    if not user.tenant_id or (requested_tenant is not None and requested_tenant != user.tenant_id):
        raise HTTPException(status_code=403, detail="Resource reads are limited to your tenant")
    return user.tenant_id
