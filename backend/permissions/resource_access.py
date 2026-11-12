# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only access to the tenant resource inventory."""

from fastapi import HTTPException, Request

from contracts.errors.exceptions import TokenExpiredError, UnauthorizedError
from gateway.authentication.auth import get_current_user_context
from permissions.models import CurrentUser
from permissions.rbac import has_permission
from permissions.tenant_scope import resolve_tenant_scope

INVENTORY_READ = "resource.inventory:read"


def require_inventory_scope(user: CurrentUser, tenant_id: str | None = None) -> str | None:
    """Check the inventory grant and resolve the requested tenant."""
    if not has_permission(user.effective_roles, INVENTORY_READ):
        raise HTTPException(status_code=403, detail="Operations permission required")
    return resolve_tenant_scope(
        user, tenant_id, allow_all_tenants=True, denied_detail="Operations are limited to your tenant",
    )


def resource_read_tenant(
    request: Request | None, *, shared: bool = False, user: CurrentUser | None = None,
) -> str | None:
    """Resolve the inventory view for a route that also serves ordinary resource readers."""
    if user is None:
        authorization = request.headers.get("authorization") if request is not None else None
        if not authorization:
            return None
        try:
            user_id, tenant_id, roles = get_current_user_context(authorization)
        except (UnauthorizedError, TokenExpiredError):
            return None
        user = CurrentUser(user_id, tenant_id, roles[0], roles=roles)

    roles = user.effective_roles
    if {"ADMIN", "SU"}.intersection(roles) or not has_permission(roles, INVENTORY_READ):
        return None
    targets = [target for target in request.query_params.getlist("tenant_id") if target] if request else []
    if shared and len(roles) > 1 and not targets:
        return None

    for target in targets or [None]:
        resolve_tenant_scope(user, target)
    return user.tenant_id
