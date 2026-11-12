# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""FastAPI permission dependencies."""

from typing import Callable

from fastapi import Depends, HTTPException

from gateway.authentication.auth import authenticate
from permissions.models import CurrentUser
from permissions.rbac import has_permission


def require(permission: str, *, alternative: str | None = None) -> Callable[[CurrentUser], CurrentUser]:
    """Return a dependency that requires the given permission string."""

    def dependency(current_user: CurrentUser = Depends(authenticate)) -> CurrentUser:
        roles = current_user.effective_roles
        if not has_permission(roles, permission) and not (alternative and has_permission(roles, alternative)):
            raise HTTPException(
                status_code=403,
                detail=f"Missing required permission: {permission}",
            )
        return current_user

    return dependency
