# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant-scope authorization helpers."""

from http import HTTPStatus

from fastapi import HTTPException

from contracts.roles import has_any_role
from permissions.models import CurrentUser


def resolve_tenant_scope(
    current_user: CurrentUser,
    tenant_id: str | None = None,
    *,
    allow_all_tenants: bool = False,
    denied_detail: str = "Resource reads are limited to your tenant",
) -> str | None:
    """Limit tenant selection to the authenticated tenant unless the caller is SU."""
    if has_any_role(current_user.effective_roles, {"SU"}):
        return tenant_id if tenant_id is not None or allow_all_tenants else current_user.tenant_id
    if not current_user.tenant_id or (tenant_id is not None and tenant_id != current_user.tenant_id):
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=denied_detail)
    return current_user.tenant_id


def resolve_personal_target_tenant(current_user: CurrentUser, tenant_id: str | None) -> str:
    """Resolve the tenant used by personal KB capacity APIs."""
    target_tenant = tenant_id or current_user.tenant_id
    resolve_tenant_scope(
        current_user, target_tenant, denied_detail="Cannot access personal KB capacity for another tenant",
    )
    return target_tenant
