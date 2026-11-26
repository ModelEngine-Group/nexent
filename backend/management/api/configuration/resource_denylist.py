# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant administrators' resource denylist endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from contracts.resource_denylist import TenantDenylistUpdate
from management.services.configuration.resource_denylist import DenylistConflict, read_denylist, update_denylist
from management.services.permission.identity.session import authenticate
from permissions.models import CurrentUser

router = APIRouter(prefix="/resource_denylist")


def require_tenant_administrator(user: CurrentUser = Depends(authenticate)):
    if not user.tenant_id or not {"ADMIN", "SU"}.intersection(user.effective_roles):
        raise HTTPException(status_code=403, detail="Tenant administrator role required")
    return user


@router.get("")
def get_tenant_denylist(user: CurrentUser = Depends(require_tenant_administrator)):
    return read_denylist(user.tenant_id)


@router.put("")
def put_tenant_denylist(payload: TenantDenylistUpdate, user: CurrentUser = Depends(require_tenant_administrator)):
    try:
        return update_denylist(payload, user.user_id, user.tenant_id)
    except DenylistConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
