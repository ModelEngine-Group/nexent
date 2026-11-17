# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorize system configuration through the shared operations permission model."""

from fastapi import HTTPException
from permissions.operations import operations_scope


def authorize_operations(user, permission="ops.configuration:read"):
    """Return the actor ID after enforcing the requested operations permission."""
    operations_scope(user, None, permission)
    return user.user_id


def authorize_configuration_write(user):
    """Restrict platform-wide writes to SU with the explicit update grant."""
    authorize_operations(user, "ops.configuration:update")
    if "SU" not in user.effective_roles:
        raise HTTPException(
            status_code=403, detail="Super administrator role required"
        )
    return user.user_id
