# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant-scope authorization helpers."""

from http import HTTPStatus

from fastapi import HTTPException

from contracts.roles import has_any_role
from permissions.models import CurrentUser

# Temporary policy for personal KB capacity APIs. Keep this policy in the
# permission layer until cross-tenant access is represented by RBAC.
_PERSONAL_KB_CROSS_TENANT_ROLES = frozenset({'SU'})


def resolve_personal_target_tenant(
    current_user: CurrentUser, tenant_id: str | None
) -> str:
    """Resolve the tenant used by personal KB capacity APIs."""
    target_tenant_id = tenant_id or current_user.tenant_id
    if (
        target_tenant_id != current_user.tenant_id
        and not has_any_role(current_user.effective_roles, _PERSONAL_KB_CROSS_TENANT_ROLES)
    ):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Cannot access personal KB capacity for another tenant",
        )
    return target_tenant_id
