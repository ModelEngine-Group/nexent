# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""
Quota management API endpoints.

Provides tenant-level and platform-level quota configuration and usage tracking.
"""

import logging
from http import HTTPStatus
from typing import Any, Dict, Optional

from contracts.constants.constants import (
    PERSONAL_KB_CAPACITY_READ_PERMISSION,
    QUOTA_PAYLOAD_DESCRIPTION,
    TARGET_TENANT_ID_DESCRIPTION,
)
from contracts.errors.exceptions import (
    AppException,
    PlatformQuotaConflictError,
    TokenExpiredError,
)
from contracts.roles import has_any_role
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from management.services.knowledge_base.inventory import (
    knowledge_listing_operation,
    list_knowledge_indices,
)
from management.services.knowledge_base.personal_capacity import personal_self_capacity
from management.services.knowledge_base.personal_capacity_access import (
    PersonalQuotaDenied,
)
from management.services.knowledge_base.personal_quota_configuration import (
    InvalidPersonalQuotaPayload,
    personal_quota_configuration,
)
from management.services.knowledge_base.platform_quota import PlatformQuotaOverview
from management.services.knowledge_base.quota import QuotaService
from management.services.knowledge_base.quota_read import read_tenant_quota
from management.services.knowledge_base.quota_usage import TenantQuotaUsage
from management.services.knowledge_base.quota_write import (
    InvalidQuotaWarning,
    QuotaWriteDenied,
    write_quota,
)
from management.services.permission.identity.session import (
    authenticate,
    get_current_user_id,
)
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from permissions.depends import require
from permissions.models import CurrentUser
from permissions.tenant_scope import resolve_personal_target_tenant

from infrastructure.agentos_identity import ServicePrincipal

logger = logging.getLogger(__name__)

# Tenant-level quota router
tenant_quota_router = APIRouter(prefix="/tenants")

# Platform-level quota router
platform_quota_router = APIRouter(prefix="/platform/quota")

# Personal KB capacity router
personal_quota_router = APIRouter(prefix="/capacity/personal")


def _platform_quota_conflict_response(exc: PlatformQuotaConflictError) -> JSONResponse:
    """Serialize allocation conflicts consistently for quota clients."""
    return JSONResponse(
        status_code=HTTPStatus.CONFLICT,
        content={"error": exc.error, "message": str(exc), **exc.details},
    )


# ── Role Helpers ────────────────────────────────────────────────────────


async def _get_manageable_index_names(tenant_id, user_id, actor_tenant_id, *, context):
    result = await list_knowledge_indices(ServicePrincipal(user_id, actor_tenant_id), tenant_id, context=context)
    return {name for name, permission in result.get('index_permissions', {}).items() if permission in ('EDIT', 'CREATOR')}


# ═══════════════════════════════════════════════════════════════════════════
# Tenant-Level Quota Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@tenant_quota_router.get("/{tenant_id}/quota")
async def get_tenant_quota(
    tenant_id: str = Path(..., description="Tenant ID"),
    authorization: Optional[str] = Header(None),
):
    """
    Get tenant quota configuration and summary.
    Accessible to any authenticated tenant user.
    """
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        result = await read_tenant_quota(tenant_id, ServicePrincipal(user_id, auth_tenant_id))

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=result,
        )
    except ScopeDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN,
                            detail="Cannot access quota config for another tenant") from exc
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=f"Error getting quota config: {exc}") from None
    except Exception as exc:
        logger.exception("Error getting tenant quota for %s", tenant_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error getting quota config: {exc!s}",
        )


@tenant_quota_router.put("/{tenant_id}/quota")
async def update_tenant_quota(
    tenant_id: str = Path(..., description="Tenant ID"),
    payload: Dict[str, Any] = Body(..., description="Quota config payload"),
    authorization: Optional[str] = Header(None),
):
    """
    Update tenant quota configuration (hard limit + warning config).
    Restricted to ADMIN, SU, and ASSET_OWNER roles.
    Rejects if hard limit was set by SU (hard_limit_editable = false).
    """
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        result = await write_quota('update', tenant_id, ServicePrincipal(user_id, auth_tenant_id), payload)

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                **result,
                "message": "Quota configuration updated successfully",
            },
        )
    except InvalidQuotaWarning as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)) from exc
    except PlatformQuotaConflictError as exc:
        return _platform_quota_conflict_response(exc)
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except QuotaWriteDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc
    except ScopeDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="This operation requires current authorized membership") from exc
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error updating quota config: {exc!s}",
        )

    except Exception as exc:
        logger.exception("Error updating tenant quota for %s", tenant_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error updating quota config: {exc!s}",
        )


@tenant_quota_router.delete("/{tenant_id}/quota")
async def delete_tenant_quota(
    tenant_id: str = Path(..., description="Tenant ID"),
    authorization: Optional[str] = Header(None),
):
    """
    Remove all tenant quota configuration.
    Restricted to ADMIN, SU, and ASSET_OWNER roles.
    """
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        await write_quota('remove', tenant_id, ServicePrincipal(user_id, auth_tenant_id), {})

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Quota configuration removed successfully"},
        )
    except PlatformQuotaConflictError as exc:
        return _platform_quota_conflict_response(exc)
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except QuotaWriteDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc
    except ScopeDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="This operation requires current authorized membership") from exc
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error deleting quota config: {exc!s}",
        )

    except Exception as exc:
        logger.exception("Error deleting tenant quota for %s", tenant_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error deleting quota config: {exc!s}",
        )


@tenant_quota_router.get("/{tenant_id}/quota/usage")
async def get_tenant_quota_usage(
    tenant_id: str = Path(..., description="Tenant ID"),
    force_refresh: bool = Query(False, description="Bypass cache and recompute usage"),
    detail: bool = Query(False, description="Include per-KB breakdown"),
    authorization: Optional[str] = Header(None),
):
    """
    Get tenant storage usage with optional per-KB breakdown.
    Accessible to any authenticated tenant user.
    """
    auth_tenant_id = None
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        async with knowledge_listing_operation() as context:
            role, usage = await TenantQuotaUsage().read(tenant_id, ServicePrincipal(user_id, auth_tenant_id),
                force_refresh=force_refresh, detail=detail, context=context)
            if detail and has_any_role(role, {'USER','DEV'}):
                manageable_index_names = await _get_manageable_index_names(tenant_id, user_id, auth_tenant_id, context=context)
                usage['breakdown'] = [item for item in usage.get('breakdown', []) if item.get('index_name') in manageable_index_names]
            return JSONResponse(status_code=HTTPStatus.OK, content=usage)
    except ScopeDenied as exc:
        message = ("Cannot access usage data for another tenant" if auth_tenant_id is not None and tenant_id != auth_tenant_id
                   else "No permission to list knowledge bases")
        raise HTTPException(status_code=403, detail=message) from exc
    except (TimeoutError, DeadlineExceeded):
        return JSONResponse(status_code=504, content={"message": "Knowledge base list timed out"})
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.exception("Error getting usage for tenant %s", tenant_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error getting usage data: {exc!s}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Platform-Level Quota Endpoints (SU/ASSET_OWNER only)
# ═══════════════════════════════════════════════════════════════════════════


@platform_quota_router.get("/overview")
async def get_platform_overview(
    authorization: Optional[str] = Header(None),
):
    """
    Get platform-level storage overview: all tenants' quotas and usage.
    Restricted to SU and ASSET_OWNER roles.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        async with knowledge_listing_operation() as context:
            overview = await PlatformQuotaOverview().read(ServicePrincipal(user_id, tenant_id), context=context)
        return JSONResponse(status_code=HTTPStatus.OK, content=overview)
    except ScopeDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN,
                            detail="This operation requires SU or ASSET_OWNER role") from exc
    except (TimeoutError, DeadlineExceeded) as exc:
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            content={"message": f"Error getting platform overview: {exc}"})
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.exception("Error getting platform overview")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error getting platform overview: {exc!s}",
        )


@platform_quota_router.put("/capacity")
async def set_platform_capacity(
    payload: Dict[str, Any] = Body(..., description="Capacity payload"),
    authorization: Optional[str] = Header(None),
):
    """
    Set platform-wide declared storage capacity.
    Restricted to SU and ASSET_OWNER roles.
    """
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        result = await write_quota('capacity', None, ServicePrincipal(user_id, auth_tenant_id), payload)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={**result, "message": "Platform capacity updated successfully"},
        )
    except PlatformQuotaConflictError as exc:
        return _platform_quota_conflict_response(exc)
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except QuotaWriteDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc
    except ScopeDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="This operation requires current authorized membership") from exc
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error setting platform capacity: {exc!s}",
        )

    except Exception as exc:
        logger.exception("Error setting platform capacity")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error setting platform capacity: {exc!s}",
        )


@platform_quota_router.delete("/capacity")
async def delete_platform_capacity(
    authorization: Optional[str] = Header(None),
):
    """
    Remove platform capacity declaration.
    Restricted to SU and ASSET_OWNER roles.
    """
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        await write_quota('capacity', None, ServicePrincipal(user_id, auth_tenant_id), {})
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Platform capacity removed successfully"},
        )
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except QuotaWriteDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc
    except ScopeDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="This operation requires current authorized membership") from exc
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error deleting platform capacity: {exc!s}",
        )

    except Exception as exc:
        logger.exception("Error deleting platform capacity")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error deleting platform capacity: {exc!s}",
        )


@platform_quota_router.put("/tenants/{tenant_id}")
async def set_tenant_hard_quota(
    tenant_id: str = Path(..., description="Target tenant ID"),
    payload: Dict[str, Any] = Body(..., description="Quota payload"),
    authorization: Optional[str] = Header(None),
):
    """
    SU sets a hard quota on a target tenant.
    Restricted to SU and ASSET_OWNER roles.
    """
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        result = await write_quota('hard', tenant_id, ServicePrincipal(user_id, auth_tenant_id), payload)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                **result,
                "tenant_id": tenant_id,
                "message": "Tenant hard quota updated successfully",
            },
        )
    except PlatformQuotaConflictError as exc:
        return _platform_quota_conflict_response(exc)
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except QuotaWriteDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc
    except ScopeDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="This operation requires current authorized membership") from exc
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error setting tenant hard quota: {exc!s}",
        )

    except Exception as exc:
        logger.exception("Error setting tenant hard quota for %s", tenant_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error setting tenant hard quota: {exc!s}",
        )


@platform_quota_router.delete("/tenants/{tenant_id}")
async def delete_tenant_hard_quota(
    tenant_id: str = Path(..., description="Target tenant ID"),
    authorization: Optional[str] = Header(None),
):
    """
    SU removes a tenant's hard quota.
    Restricted to SU and ASSET_OWNER roles.
    """
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        await write_quota('remove-platform', tenant_id, ServicePrincipal(user_id, auth_tenant_id), {})
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "tenant_id": tenant_id,
                "message": "Tenant hard quota removed successfully",
            },
        )
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except QuotaWriteDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc
    except ScopeDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="This operation requires current authorized membership") from exc
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error deleting tenant hard quota: {exc!s}",
        )


# Personal KB capacity endpoints

    except Exception as exc:
        logger.exception("Error deleting tenant hard quota for %s", tenant_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error deleting tenant hard quota: {exc!s}",
        )


# Personal KB capacity endpoints


@personal_quota_router.get("/me")
async def get_personal_self_capacity(
    current_user: CurrentUser = Depends(authenticate),
):
    """Return the current user's own personal KB capacity."""
    try:
        data = await personal_self_capacity(ServicePrincipal(current_user.user_id, current_user.tenant_id))
        return JSONResponse(status_code=HTTPStatus.OK, content=data)
    except AppException:
        raise
    except HTTPException:
        raise
    except ScopeDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Cannot access personal KB capacity") from exc
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=f"Error getting personal KB capacity: {exc!s}") from None
    except Exception as exc:
        logger.exception("Error getting current user's personal KB capacity")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error getting personal KB capacity: {exc!s}",
        )


@personal_quota_router.get("/users")
def list_personal_capacity_users(
    current_user: CurrentUser = Depends(require(PERSONAL_KB_CAPACITY_READ_PERMISSION, alternative="resource.inventory:read")),
    tenant_id: Optional[str] = Query(None, description=TARGET_TENANT_ID_DESCRIPTION),
    page: int = Query(1, ge=1, description="Page number starting from 1"),
    page_size: int = Query(20, ge=1, le=100, description="Page size from 1 to 100"),
    sort_by: str = Query(
        "total_bytes",
        description=("Sort field: user_name, kb_count, total_bytes, quota_limit_bytes, usage_rate"),
    ),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    keyword: Optional[str] = Query(None, description="Filter users by user name or email"),
):
    """List personal KB storage aggregated by user."""
    try:
        if sort_by not in {
            "user_name",
            "kb_count",
            "total_bytes",
            "quota_limit_bytes",
            "usage_rate",
        }:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=("sort_by must be one of user_name, kb_count, total_bytes, quota_limit_bytes, usage_rate"),
            )
        if sort_order.lower() not in {"asc", "desc"}:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="sort_order must be asc or desc",
            )
        target_tenant_id = resolve_personal_target_tenant(current_user, tenant_id)
        service = QuotaService(target_tenant_id, current_user.user_id)
        data = service.list_personal_capacity_users(
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            keyword=keyword,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=data)
    except HTTPException:
        raise
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Error listing personal KB capacity users")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error listing personal KB capacity: {exc!s}",
        )


@personal_quota_router.get("/users/{user_id}/kbs")
def get_personal_capacity_kbs(
    user_id: str = Path(..., description="User ID"),
    current_user: CurrentUser = Depends(require(PERSONAL_KB_CAPACITY_READ_PERMISSION, alternative="resource.inventory:read")),
    tenant_id: Optional[str] = Query(None, description=TARGET_TENANT_ID_DESCRIPTION),
    page: int = Query(1, ge=1, description="Page number starting from 1"),
    page_size: int = Query(20, ge=1, le=100, description="Page size from 1 to 100"),
):
    """List a user's personal KB records with storage details."""
    try:
        target_tenant_id = resolve_personal_target_tenant(current_user, tenant_id)
        service = QuotaService(target_tenant_id, current_user.user_id)
        data = service.get_personal_kb_details(
            user_id,
            page=page,
            page_size=page_size,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=data)
    except HTTPException:
        raise
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Error getting personal KB details for user %s", user_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error getting personal KB details: {exc!s}",
        )


@personal_quota_router.get("/summary")
def get_personal_capacity_summary(
    current_user: CurrentUser = Depends(require(PERSONAL_KB_CAPACITY_READ_PERMISSION, alternative="resource.inventory:read")),
    tenant_id: Optional[str] = Query(None, description=TARGET_TENANT_ID_DESCRIPTION),
):
    """Return aggregate personal KB capacity stats for a tenant."""
    try:
        target_tenant_id = resolve_personal_target_tenant(current_user, tenant_id)
        service = QuotaService(target_tenant_id, current_user.user_id)
        data = service.get_personal_capacity_summary()
        return JSONResponse(status_code=HTTPStatus.OK, content=data)
    except HTTPException:
        raise
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Error getting personal KB capacity summary")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error getting personal KB capacity summary: {exc!s}",
        )


@personal_quota_router.put("/users/{user_id}/quota")
async def set_personal_user_quota(
    user_id: str = Path(..., description="User ID"),
    payload: Dict[str, Any] = Body(..., description=QUOTA_PAYLOAD_DESCRIPTION),
    current_user: CurrentUser = Depends(authenticate),
    tenant_id: Optional[str] = Query(None, description=TARGET_TENANT_ID_DESCRIPTION),
):
    """Set or clear a user's personal KB quota."""
    try:
        target_tenant_id = tenant_id or current_user.tenant_id
        quota_limit_bytes = payload.get("quota_limit_bytes")
        unlimited = bool(payload.get("unlimited", False))
        result = await personal_quota_configuration('user-write', target_tenant_id,
            ServicePrincipal(current_user.user_id, current_user.tenant_id),
            {'subject_user_id': user_id, 'quota_limit_bytes': quota_limit_bytes, 'unlimited': unlimited})
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AppException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except HTTPException:
        raise
    except PersonalQuotaDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc
    except ScopeDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Cannot access personal KB capacity") from exc
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=f"Error setting personal KB quota: {exc!s}") from None
    except Exception as exc:
        logger.exception("Error setting personal KB quota")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error setting personal KB quota: {exc!s}",
        )


@personal_quota_router.get("/default-quota")
async def get_personal_default_quota(
    current_user: CurrentUser = Depends(authenticate),
    tenant_id: Optional[str] = Query(None, description=TARGET_TENANT_ID_DESCRIPTION),
):
    """Get the tenant default personal KB quota."""
    try:
        target_tenant_id = tenant_id or current_user.tenant_id
        result = await personal_quota_configuration('read', target_tenant_id,
            ServicePrincipal(current_user.user_id, current_user.tenant_id))
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except HTTPException:
        raise
    except AppException:
        raise
    except InvalidPersonalQuotaPayload as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)) from exc
    except PersonalQuotaDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc
    except ScopeDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Cannot access personal KB capacity") from exc
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=f"Error getting personal KB default quota: {exc!s}") from None
    except Exception as exc:
        logger.exception("Error getting personal KB default quota")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error getting personal KB default quota: {exc!s}",
        )


@personal_quota_router.put("/default-quota")
async def set_personal_default_quota(
    payload: Dict[str, Any] = Body(..., description=QUOTA_PAYLOAD_DESCRIPTION),
    current_user: CurrentUser = Depends(authenticate),
    tenant_id: Optional[str] = Query(None, description=TARGET_TENANT_ID_DESCRIPTION),
):
    """Set or clear the tenant default personal KB quota."""
    try:
        target_tenant_id = tenant_id or current_user.tenant_id
        quota_limit_bytes = payload.get("quota_limit_bytes")
        unlimited = bool(payload.get("unlimited", False))
        result = await personal_quota_configuration('write', target_tenant_id,
            ServicePrincipal(current_user.user_id, current_user.tenant_id),
            {'quota_limit_bytes': quota_limit_bytes, 'unlimited': unlimited})
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except HTTPException:
        raise
    except AppException:
        raise
    except InvalidPersonalQuotaPayload as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)) from exc
    except PersonalQuotaDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc
    except ScopeDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Cannot access personal KB capacity") from exc
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=f"Error setting personal KB default quota: {exc!s}") from None
    except Exception as exc:
        logger.exception("Error setting personal KB default quota")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error setting personal KB default quota: {exc!s}",
        )
