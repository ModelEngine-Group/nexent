# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""FastAPI permission dependencies."""

from typing import Callable

from consts.const import IS_SPEED_MODE
from fastapi import Depends, HTTPException
from permissions.models import CurrentUser
from permissions.rbac import has_permission
from gateway.authentication.normal import authenticate






def require(permission: str) -> Callable[[CurrentUser], CurrentUser]:
    """Return a dependency that requires the given permission string."""

    def dependency(current_user: CurrentUser = Depends(authenticate)) -> CurrentUser:
        if IS_SPEED_MODE and current_user.normalized_role == "SPEED":
            # Speed mode has no role_permission_t seeds, so allow the built-in
            # SPEED account to pass through permission checks.
            return current_user
        if not has_permission(current_user.normalized_role, permission):
            raise HTTPException(
                status_code=403,
                detail=f"Missing required permission: {permission}",
            )
        return current_user

    return dependency
