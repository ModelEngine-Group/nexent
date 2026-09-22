"""
User management API endpoints
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Request
from http import HTTPStatus
from starlette.responses import JSONResponse

from consts.model import (
    UserListRequest, UserUpdateRequest
)
from services.audit_service import (
    AUDIT_RESULT_FAILURE,
    AUDIT_RESULT_SUCCESS,
    reason_from_exception,
    record_security_event,
)
from consts.exceptions import (
    ForbiddenError,
    NotFoundException,
    TenantResourceLimitError,
    UnauthorizedError,
    tenant_resource_limit_error_payload,
)
from services.user_service import (
    delete_user_and_cleanup, get_users_for_requester, update_user_for_requester
)
from database.user_tenant_db import get_user_tenant_by_user_id
from utils.auth_utils import get_current_user_context, get_current_user_id

logger = logging.getLogger("user_app")
router = APIRouter(prefix="/users", tags=["users"])


@router.post("/list")
async def get_users_endpoint(
    request: UserListRequest,
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    """
    Get users belonging to a specific tenant with pagination

    Args:
        request: User list request with tenant_id, optional page, and page_size.
                If page and page_size are not provided, returns all data.

    Returns:
        JSONResponse: List of users in the tenant (paginated or all)
    """
    try:
        _, requester_tenant_id, requester_role = get_current_user_context(authorization)
        filter_kwargs = {
            "search": request.search,
            "roles": request.roles,
            "group_ids": request.group_ids,
        }
        filter_kwargs = {key: value for key, value in filter_kwargs.items() if value}
        result = get_users_for_requester(
            request.tenant_id,
            request.page,
            request.page_size,
            request.sort_by,
            request.sort_order,
            **filter_kwargs,
            requester_tenant_id=requester_tenant_id,
            requester_role=requester_role,
        )

        # Build response content
        content = {
            "message": "Users retrieved successfully",
            "data": result["users"],
            "total": result["total"]
        }

        # Add pagination info only if pagination was used
        if request.page is not None and request.page_size is not None:
            content["pagination"] = {
                "page": request.page,
                "page_size": request.page_size,
                "total": result["total"],
                "total_pages": result.get("total_pages", (result["total"] + request.page_size - 1) // request.page_size)
            }

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=content
        )
    except UnauthorizedError as exc:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except ForbiddenError as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc))
    except Exception as exc:
        logger.error(f"Unexpected error retrieving users for tenant {request.tenant_id}: {str(exc)}")
        # Include the actual error message for debugging
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve users: {str(exc)}"
        )


@router.put("/{user_id}")
async def update_user_endpoint(
    user_id: str,
    request: UserUpdateRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    """
    Update user information

    Args:
        user_id: User identifier
        request: User update request containing role
        http_request: FastAPI request object for audit context
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Updated user information
    """
    current_user_id, requester_tenant_id = None, None
    try:
        # Get current user ID from token for access control
        current_user_id, requester_tenant_id, requester_role = get_current_user_context(authorization)

        # Update user
        updated_user = await update_user_for_requester(
            user_id,
            request.model_dump(),
            updated_by=current_user_id,
            requester_tenant_id=requester_tenant_id,
            requester_role=requester_role,
        )

        logger.info(f"Updated user {user_id} by user {current_user_id}")
        changes = {key: value for key, value in request.model_dump().items() if value is not None}
        if changes.get("email"):
            changes["email"] = str(changes["email"])
        record_security_event("user_update", AUDIT_RESULT_SUCCESS, request=http_request,
                          user_id=current_user_id, tenant_id=requester_tenant_id,
                          details={"target_user_id": user_id, "changes": changes})

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "User updated successfully",
                "data": updated_user
            }
        )

    except UnauthorizedError as exc:
        record_security_event("user_update", AUDIT_RESULT_FAILURE, request=http_request,
                          user_id=current_user_id, tenant_id=requester_tenant_id,
                          reason=reason_from_exception(exc),
                          details={"target_user_id": user_id})
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except ForbiddenError as exc:
        record_security_event("user_update", AUDIT_RESULT_FAILURE, request=http_request,
                          user_id=current_user_id, tenant_id=requester_tenant_id,
                          reason=reason_from_exception(exc),
                          details={"target_user_id": user_id})
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc))
    except NotFoundException as exc:
        record_security_event("user_update", AUDIT_RESULT_FAILURE, request=http_request,
                          user_id=current_user_id, tenant_id=requester_tenant_id,
                          reason=reason_from_exception(exc),
                          details={"target_user_id": user_id})
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except TenantResourceLimitError as exc:
        logger.warning("User update rejected by resource limit: %s", exc)
        return JSONResponse(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            content=tenant_resource_limit_error_payload(exc),
        )
    except ValueError as exc:
        logger.warning(f"User update validation error for user {user_id}: {str(exc)}")
        record_security_event("user_update", AUDIT_RESULT_FAILURE, request=http_request,
                          user_id=current_user_id, tenant_id=requester_tenant_id,
                          reason=reason_from_exception(exc),
                          details={"target_user_id": user_id})
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error updating user {user_id}: {str(exc)}")
        record_security_event("user_update", AUDIT_RESULT_FAILURE, request=http_request,
                          user_id=current_user_id, tenant_id=requester_tenant_id,
                          reason=reason_from_exception(exc),
                          details={"target_user_id": user_id})
        # Include the actual error message for debugging
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user: {str(exc)}"
        )


@router.delete("/{user_id}")
async def delete_user_endpoint(
    user_id: str,
    http_request: Request,
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    """
    Permanently delete user and all related data.

    This performs complete cleanup including:
    - Soft-delete user-tenant relationship and groups
    - Soft-delete memory configs and conversations
    - Clear user-level memories
    - Permanently delete user from Supabase

    Args:
        user_id: User identifier
        http_request: FastAPI request object for audit context
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Success status
    """
    current_user_id = None
    try:
        # Get current user ID from token for access control
        current_user_id, _ = get_current_user_id(authorization)

        # Get user tenant ID for cleanup operations
        user_tenant = get_user_tenant_by_user_id(user_id)
        if not user_tenant:
            raise ValueError(f"User {user_id} not found")

        tenant_id = user_tenant["tenant_id"]

        # Perform complete user cleanup
        await delete_user_and_cleanup(user_id, tenant_id)

        logger.info(f"Permanently deleted user {user_id} by admin {current_user_id}")
        record_security_event("user_delete", AUDIT_RESULT_SUCCESS, request=http_request,
                          user_id=current_user_id,
                          details={"target_user_id": user_id, "target_tenant_id": tenant_id})

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "User deleted successfully"
            }
        )

    except ValueError as exc:
        logger.warning(f"User deletion validation error for user {user_id}: {str(exc)}")
        record_security_event("user_delete", AUDIT_RESULT_FAILURE, request=http_request,
                          user_id=current_user_id, reason=reason_from_exception(exc),
                          details={"target_user_id": user_id})
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error deleting user {user_id}: {str(exc)}")
        record_security_event("user_delete", AUDIT_RESULT_FAILURE, request=http_request,
                          user_id=current_user_id, reason=reason_from_exception(exc),
                          details={"target_user_id": user_id})
        # Include the actual error message for debugging
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete user: {str(exc)}"
        )
