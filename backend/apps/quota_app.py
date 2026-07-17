"""
Quota management API endpoints.

Provides tenant-level and platform-level quota configuration and usage tracking.
"""

import logging
from http import HTTPStatus
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Path, Query
from fastapi.responses import JSONResponse

from consts.const import ASSET_OWNER_ROLE, ASSET_OWNER_TENANT_ID
from consts.exceptions import QuotaExceededError
from database.user_tenant_db import get_user_tenant_by_user_id
from services.quota_service import QuotaService
from utils.auth_utils import get_current_user_id

logger = logging.getLogger(__name__)

# Tenant-level quota router
tenant_quota_router = APIRouter(prefix="/tenants")

# Platform-level quota router
platform_quota_router = APIRouter(prefix="/platform/quota")


# ── Role Helpers ────────────────────────────────────────────────────────

def _get_user_role(authorization: Optional[str]) -> str:
    """Extract user role from the authorization token."""
    if not authorization:
        return "USER"
    try:
        user_id, _ = get_current_user_id(authorization)
        user_info = get_user_tenant_by_user_id(user_id)
        return (user_info.get("user_role") or "USER").upper() if user_info else "USER"
    except Exception:
        return "USER"


def _require_admin_or_su(authorization: Optional[str]) -> str:
    """Require ADMIN, SU, or ASSET_OWNER role. Returns the role string."""
    role = _get_user_role(authorization)
    if role not in ("SU", "ADMIN", "ASSET_OWNER"):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="This operation requires ADMIN, SU, or ASSET_OWNER role",
        )
    return role


def _require_su_or_asset_owner(authorization: Optional[str]) -> str:
    """Require SU or ASSET_OWNER role. Returns the role string."""
    role = _get_user_role(authorization)
    if role not in ("SU", "ASSET_OWNER"):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="This operation requires SU or ASSET_OWNER role",
        )
    return role


def _get_manageable_index_names(tenant_id: str, user_id: str) -> set[str]:
    """Return KB index names the current user can manage."""
    from services.vectordatabase_service import (
        ElasticSearchService,
        get_vector_db_core,
    )

    result = ElasticSearchService.list_indices(
        pattern="*",
        include_stats=False,
        target_tenant_id=tenant_id,
        user_id=user_id,
        vdb_core=get_vector_db_core(),
    )
    if not isinstance(result, dict):
        return set()
    permissions = result.get("index_permissions", {})
    return {
        index_name
        for index_name, permission in permissions.items()
        if permission in ("EDIT", "CREATOR")
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tenant-Level Quota Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@tenant_quota_router.get("/{tenant_id}/quota")
def get_tenant_quota(
    tenant_id: str = Path(..., description="Tenant ID"),
    authorization: Optional[str] = Header(None),
):
    """
    Get tenant quota configuration and summary.
    Accessible to any authenticated tenant user.
    """
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        # Use auth tenant_id if accessing own tenant; SU can see any
        role = _get_user_role(authorization)
        if role not in ("SU", "ASSET_OWNER") and tenant_id != auth_tenant_id:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="Cannot access quota config for another tenant",
            )

        service = QuotaService(tenant_id, user_id)
        hard_limit = service.get_hard_limit()
        warning_config = service.get_warning_config()
        summary = service.get_quota_summary()

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                **hard_limit,
                **warning_config,
                "summary": summary,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting tenant quota for %s", tenant_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error getting quota config: {str(exc)}",
        )


@tenant_quota_router.put("/{tenant_id}/quota")
def update_tenant_quota(
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
        role = _require_admin_or_su(authorization)

        # Non-SU users can only modify their own tenant
        if role not in ("SU", "ASSET_OWNER") and tenant_id != auth_tenant_id:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="Cannot modify quota config for another tenant",
            )

        service = QuotaService(tenant_id, user_id)

        # Apply hard limit
        hard_limit_gb = payload.get("hard_limit_gb")
        hard_limit_mb = payload.get("hard_limit_mb")

        if hard_limit_gb is not None or hard_limit_mb is not None:
            # Check if hard limit is editable (task 9.6)
            hard_limit_info = service.get_hard_limit()
            if not hard_limit_info.get("hard_limit_editable", True):
                # Only allow SU to modify SU-set limits
                if role not in ("SU", "ASSET_OWNER"):
                    raise HTTPException(
                        status_code=HTTPStatus.FORBIDDEN,
                        detail="Tenant hard quota is managed by the platform administrator",
                    )

            # SU sets tenant hard limit → mark as non-editable for tenant admin
            if role in ("SU", "ASSET_OWNER"):
                QuotaService.set_tenant_hard_limit(
                    tenant_id,
                    limit_gb=hard_limit_gb,
                    limit_mb=hard_limit_mb,
                    su_user_id=user_id,
                )
            else:
                service.set_hard_limit(
                    limit_gb=hard_limit_gb,
                    limit_mb=hard_limit_mb,
                )

        # Apply warning config
        warning_enabled = payload.get("warning_enabled")
        warning_pct = payload.get("warning_threshold_pct")
        critical_pct = payload.get("critical_threshold_pct")

        if any(v is not None for v in [warning_enabled, warning_pct, critical_pct]):
            try:
                service.set_warning_config(
                    enabled=warning_enabled,
                    warning_pct=warning_pct,
                    critical_pct=critical_pct,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)
                )

        # Return updated config
        updated_hard_limit = service.get_hard_limit()
        updated_warning = service.get_warning_config()

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                **updated_hard_limit,
                **updated_warning,
                "message": "Quota configuration updated successfully",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error updating tenant quota for %s", tenant_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error updating quota config: {str(exc)}",
        )


@tenant_quota_router.delete("/{tenant_id}/quota")
def delete_tenant_quota(
    tenant_id: str = Path(..., description="Tenant ID"),
    authorization: Optional[str] = Header(None),
):
    """
    Remove all tenant quota configuration.
    Restricted to ADMIN, SU, and ASSET_OWNER roles.
    """
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        role = _require_admin_or_su(authorization)

        if role not in ("SU", "ASSET_OWNER") and tenant_id != auth_tenant_id:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="Cannot modify quota config for another tenant",
            )

        service = QuotaService(tenant_id, user_id)
        service.delete_hard_limit()

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Quota configuration removed successfully"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error deleting tenant quota for %s", tenant_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error deleting quota config: {str(exc)}",
        )


@tenant_quota_router.get("/{tenant_id}/quota/usage")
def get_tenant_quota_usage(
    tenant_id: str = Path(..., description="Tenant ID"),
    force_refresh: bool = Query(False, description="Bypass cache and recompute usage"),
    detail: bool = Query(False, description="Include per-KB breakdown"),
    authorization: Optional[str] = Header(None),
):
    """
    Get tenant storage usage with optional per-KB breakdown.
    Accessible to any authenticated tenant user.
    """
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        role = _get_user_role(authorization)
        if role not in ("SU", "ASSET_OWNER") and tenant_id != auth_tenant_id:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="Cannot access usage data for another tenant",
            )

        service = QuotaService(tenant_id, user_id)
        usage = service.get_usage(force_refresh=force_refresh, detail=detail)
        if detail and role in ("USER", "DEV"):
            manageable_index_names = _get_manageable_index_names(
                tenant_id, user_id
            )
            usage["breakdown"] = [
                item
                for item in usage.get("breakdown", [])
                if item.get("index_name") in manageable_index_names
            ]

        return JSONResponse(status_code=HTTPStatus.OK, content=usage)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting usage for tenant %s", tenant_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error getting usage data: {str(exc)}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Platform-Level Quota Endpoints (SU/ASSET_OWNER only)
# ═══════════════════════════════════════════════════════════════════════════


@platform_quota_router.get("/overview")
def get_platform_overview(
    authorization: Optional[str] = Header(None),
):
    """
    Get platform-level storage overview: all tenants' quotas and usage.
    Restricted to SU and ASSET_OWNER roles.
    """
    try:
        _require_su_or_asset_owner(authorization)
        user_id, _ = get_current_user_id(authorization)

        overview = QuotaService.get_platform_overview(ASSET_OWNER_TENANT_ID)
        return JSONResponse(status_code=HTTPStatus.OK, content=overview)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting platform overview")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error getting platform overview: {str(exc)}",
        )


@platform_quota_router.put("/capacity")
def set_platform_capacity(
    payload: Dict[str, Any] = Body(..., description="Capacity payload"),
    authorization: Optional[str] = Header(None),
):
    """
    Set platform-wide declared storage capacity.
    Restricted to SU and ASSET_OWNER roles.
    """
    try:
        _require_su_or_asset_owner(authorization)
        user_id, _ = get_current_user_id(authorization)

        capacity_gb = payload.get("capacity_gb")
        result = QuotaService.set_platform_capacity(
            capacity_gb, ASSET_OWNER_TENANT_ID, user_id
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={**result, "message": "Platform capacity updated successfully"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error setting platform capacity")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error setting platform capacity: {str(exc)}",
        )


@platform_quota_router.delete("/capacity")
def delete_platform_capacity(
    authorization: Optional[str] = Header(None),
):
    """
    Remove platform capacity declaration.
    Restricted to SU and ASSET_OWNER roles.
    """
    try:
        _require_su_or_asset_owner(authorization)
        user_id, _ = get_current_user_id(authorization)

        QuotaService.set_platform_capacity(None, ASSET_OWNER_TENANT_ID, user_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Platform capacity removed successfully"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error deleting platform capacity")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error deleting platform capacity: {str(exc)}",
        )


@platform_quota_router.put("/tenants/{tenant_id}")
def set_tenant_hard_quota(
    tenant_id: str = Path(..., description="Target tenant ID"),
    payload: Dict[str, Any] = Body(..., description="Quota payload"),
    authorization: Optional[str] = Header(None),
):
    """
    SU sets a hard quota on a target tenant.
    Restricted to SU and ASSET_OWNER roles.
    """
    try:
        _require_su_or_asset_owner(authorization)
        user_id, _ = get_current_user_id(authorization)

        hard_limit_gb = payload.get("hard_limit_gb")
        hard_limit_mb = payload.get("hard_limit_mb")
        result = QuotaService.set_tenant_hard_limit(
            tenant_id,
            limit_gb=hard_limit_gb,
            limit_mb=hard_limit_mb,
            su_user_id=user_id,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                **result,
                "tenant_id": tenant_id,
                "message": "Tenant hard quota updated successfully",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error setting tenant hard quota for %s", tenant_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error setting tenant hard quota: {str(exc)}",
        )


@platform_quota_router.delete("/tenants/{tenant_id}")
def delete_tenant_hard_quota(
    tenant_id: str = Path(..., description="Target tenant ID"),
    authorization: Optional[str] = Header(None),
):
    """
    SU removes a tenant's hard quota.
    Restricted to SU and ASSET_OWNER roles.
    """
    try:
        _require_su_or_asset_owner(authorization)
        user_id, _ = get_current_user_id(authorization)

        QuotaService.delete_tenant_hard_limit(tenant_id, user_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "tenant_id": tenant_id,
                "message": "Tenant hard quota removed successfully",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error deleting tenant hard quota for %s", tenant_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error deleting tenant hard quota: {str(exc)}",
        )
