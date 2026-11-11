# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Permission contracts and metadata; operations business CRUD is separate work."""

from fastapi import APIRouter, Depends, Query

from gateway.authentication.auth import authenticate
from ops.services.access import resource_inventory
from permissions.models import CurrentUser
from permissions.operations import authorization_metadata, operations_scope

router = APIRouter(prefix="/ops", tags=["operations access"])


@router.get("/authorization")
def authorization(user: CurrentUser = Depends(authenticate)):
    return {"data": authorization_metadata(user)}


@router.get("/resources")
def resources(
    tenant_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: CurrentUser = Depends(authenticate),
):
    return {"data": resource_inventory(user, tenant_id, page, page_size)}


@router.get("/scope")
def scope(
    tenant_id: str | None = None,
    module: str = Query("dashboard", pattern="^(dashboard|configuration)$"),
    action: str = Query("read", pattern="^(read|create|update|delete)$"),
    user: CurrentUser = Depends(authenticate),
):
    tenant = operations_scope(user, tenant_id, f"ops.{module}:{action}")
    return {"data": {"tenant_id": tenant, "scope": "all_tenants" if tenant is None else "tenant"}}
