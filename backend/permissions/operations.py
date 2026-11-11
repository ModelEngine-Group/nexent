# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Action-specific operations scope; never expands ordinary business scope."""

from fastapi import HTTPException

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


def resource_read_tenant(request) -> str | None:
    """Return the tenant authorized for an operations resource read."""
    return getattr(request.state, "resource_read_tenant", None) if request is not None else None
