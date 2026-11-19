# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""FastAPI permission dependencies."""

from typing import Callable

from fastapi import Depends, Header, HTTPException

from management.services.permission.identity.session import authenticate
from permissions.models import CurrentUser
from permissions.casdoor_policy import permission_override, policy_scope, staged_actions
from permissions.rbac import has_permission


def require(permission: str, *, alternative: str | None = None) -> Callable[[CurrentUser], CurrentUser]:
    """Return a dependency that requires the given permission string."""

    def dependency(current_user: CurrentUser = Depends(authenticate)) -> CurrentUser:
        roles = current_user.effective_roles
        allowed = permission_override(current_user.user_id, roles, permission)
        if allowed is None:
            allowed = has_permission(roles, permission) or bool(alternative and has_permission(roles, alternative))
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Missing required permission: {permission}",
            )
        return current_user

    return dependency


def require_managed(permission: str) -> Callable[..., None]:
    """Enforce an opt-in Casdoor action alongside the route's existing authorization."""

    def dependency(authorization: str | None = Header(None)) -> None:
        if permission not in staged_actions() or not policy_scope():
            return
        current_user = authenticate(authorization=authorization, _credentials=None)
        if permission_override(current_user.user_id, current_user.effective_roles, permission) is False:
            raise HTTPException(status_code=403, detail=f"Missing required permission: {permission}")

    return dependency
