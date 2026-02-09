"""
User management API endpoints
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from http import HTTPStatus
from starlette.responses import JSONResponse

from consts.model import (
    UserListRequest, UserUpdateRequest
)
from services.user_service import (
    get_users, update_user, delete_user_and_cleanup
)
from database.user_tenant_db import get_user_tenant_by_user_id
from utils.auth_utils import get_current_user_id

logger = logging.getLogger("user_app")
router = APIRouter(prefix="/users", tags=["users"])


@router.post("/list")
async def get_users_endpoint(
    request: UserListRequest,
) -> JSONResponse:
    """
    Get users belonging to a specific tenant with pagination

    Args:
        request: User list request with tenant_id, page, and page_size

    Returns:
        JSONResponse: Paginated list of users in the tenant
    """
    try:
        # Get tenant users with pagination and sorting
        result = get_users(request.tenant_id, request.page, request.page_size,
                          request.sort_by, request.sort_order)

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Users retrieved successfully",
                "data": result["users"],
                "pagination": {
                    "page": request.page,
                    "page_size": request.page_size,
                    "total": result["total"],
                    "total_pages": result["total_pages"]
                }
            }
        )
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
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Update user information

    Args:
        user_id: User identifier
        request: User update request containing role
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Updated user information
    """
    try:
        # Get current user ID from token for access control
        current_user_id, _ = get_current_user_id(authorization)

        # Update user
        updated_user = await update_user(user_id, request.model_dump(), current_user_id)

        logger.info(f"Updated user {user_id} by user {current_user_id}")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "User updated successfully",
                "data": updated_user
            }
        )

    except ValueError as exc:
        logger.warning(f"User update validation error for user {user_id}: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error updating user {user_id}: {str(exc)}")
        # Include the actual error message for debugging
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user: {str(exc)}"
        )


@router.delete("/{user_id}")
async def delete_user_endpoint(
    user_id: str,
    authorization: Optional[str] = Header(None)
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
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Success status
    """
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

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "User deleted successfully"
            }
        )

    except ValueError as exc:
        logger.warning(f"User deletion validation error for user {user_id}: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error deleting user {user_id}: {str(exc)}")
        # Include the actual error message for debugging
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete user: {str(exc)}"
        )

