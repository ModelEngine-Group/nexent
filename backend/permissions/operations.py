# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorization for the operations dashboard and system configuration."""

from fastapi import HTTPException

from permissions.rbac import has_permission
from permissions.tenant_scope import resolve_tenant_scope

ACTIONS = ("read", "create", "update", "delete")


def operations_scope(user, tenant_id=None, permission="ops.dashboard:read"):
    roles = user.effective_roles
    if not has_permission(roles, permission) or not set(roles) & {"OPS", "SU"}:
        raise HTTPException(status_code=403, detail="Operations permission required")
    return resolve_tenant_scope(
        user, tenant_id, allow_all_tenants=True, denied_detail="Operations are limited to your tenant",
    )


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
