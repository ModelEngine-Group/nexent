"""
Group management API endpoints
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from http import HTTPStatus
from starlette.responses import JSONResponse

from consts.model import (
    GroupCreateRequest, GroupUpdateRequest,
    GroupUserRequest, GroupListRequest, SetDefaultGroupRequest,
    GroupMembersUpdateRequest
)
from consts.exceptions import NotFoundException, ValidationError, UnauthorizedError
from services.group_service import (
    create_group, get_group_info, update_group, delete_group,
    add_user_to_single_group, remove_user_from_single_group, get_group_users,
    add_user_to_groups, get_tenant_default_group_id, set_tenant_default_group_id,
    get_groups_by_tenant, update_group_members
)
from services.tenant_service import get_tenant_info
from utils.auth_utils import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/groups", tags=["groups"])


@router.post("", response_model=None)
async def create_group_endpoint(
    request: GroupCreateRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Create a new group

    Args:
        request: Group creation request
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Created group information
    """
    try:
        # Get current user ID from token
        user_id, _ = get_current_user_id(authorization)

        # Create group
        group_info = create_group(
            tenant_id=request.tenant_id,
            group_name=request.group_name,
            group_description=request.group_description,
            user_id=user_id
        )

        logger.info(f"Created group '{request.group_name}' in tenant {request.tenant_id} by user {user_id}")

        return JSONResponse(
            status_code=HTTPStatus.CREATED,
            content={
                "message": "Group created successfully",
                "data": group_info
            }
        )

    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized group creation attempt: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except ValidationError as exc:
        logger.warning(f"Group creation validation error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error during group creation: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to create group"
        )


@router.get("/{group_id}")
async def get_group_endpoint(group_id: int) -> JSONResponse:
    """
    Get group information by group ID

    Args:
        group_id: Group identifier
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Group information
    """
    try:
        # Get group info
        group_info = get_group_info(group_id)

        if not group_info:
            raise NotFoundException(f"Group {group_id} not found")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Group retrieved successfully",
                "data": group_info
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Group not found: {group_id}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error retrieving group {group_id}: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve group"
        )


@router.post("/list")
async def get_groups_endpoint(
    request: GroupListRequest,
) -> JSONResponse:
    """
    Search groups for a specific tenant with pagination

    Args:
        request: Group search request with tenant_id, page, and page_size

    Returns:
        JSONResponse: Paginated list of groups for the tenant
    """
    try:
        # Validate tenant exists
        get_tenant_info(request.tenant_id)
        # Get groups under given tenant with pagination and sorting
        result = get_groups_by_tenant(
            tenant_id=request.tenant_id,
            page=request.page,
            page_size=request.page_size,
            sort_by=request.sort_by,
            sort_order=request.sort_order
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Groups retrieved successfully",
                "data": result["groups"],
                "pagination": {
                    "page": request.page,
                    "page_size": request.page_size,
                    "total": result["total"],
                    "total_pages": (result["total"] + request.page_size - 1) // request.page_size
                }
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Tenant not found: {request.tenant_id}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error retrieving groups: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve groups"
        )


@router.put("/{group_id}")
async def update_group_endpoint(
    group_id: int,
    request: GroupUpdateRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Update group information

    Args:
        group_id: Group identifier
        request: Group update request
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Success status
    """
    try:
        # Get current user ID from token
        user_id, _ = get_current_user_id(authorization)

        # Prepare updates dict
        updates = {}
        if request.group_name is not None:
            updates["group_name"] = request.group_name
        if request.group_description is not None:
            updates["group_description"] = request.group_description

        if not updates:
            raise ValidationError("No valid fields provided for update")

        # Update group
        success = update_group(
            group_id=group_id,
            updates=updates,
            user_id=user_id
        )

        if not success:
            raise ValidationError("Failed to update group")

        logger.info(f"Updated group {group_id} by user {user_id}")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Group updated successfully"
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Group not found for update: {group_id}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except ValidationError as exc:
        logger.warning(f"Group update validation error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized group update attempt: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error during group update: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update group"
        )


@router.delete("/{group_id}")
async def delete_group_endpoint(
    group_id: int,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Delete group

    Args:
        group_id: Group identifier
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Success status
    """
    try:
        # Get current user ID from token
        user_id, _ = get_current_user_id(authorization)

        # Delete group
        success = delete_group(
            group_id=group_id,
            user_id=user_id
        )

        if not success:
            raise ValidationError("Failed to delete group")

        logger.info(f"Deleted group {group_id} by user {user_id}")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Group deleted successfully"
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Group not found for deletion: {group_id}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except ValidationError as exc:
        logger.warning(f"Group deletion validation error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized group deletion attempt: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error during group deletion: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to delete group"
        )


@router.post("/{group_id}/members")
async def add_user_to_group_endpoint(
    group_id: int,
    request: GroupUserRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Add user to group

    Args:
        group_id: Group identifier
        request: User addition request containing user_id
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Group membership result
    """
    try:
        # Validate request - only user_id should be provided in body
        if request.group_ids is not None:
            raise ValidationError("group_ids should not be provided for single group operation")

        # Get current user ID from token
        current_user_id, _ = get_current_user_id(authorization)

        # Add user to group
        result = add_user_to_single_group(
            group_id=group_id,
            user_id=request.user_id,
            current_user_id=current_user_id
        )

        logger.info(f"Added user {request.user_id} to group {group_id} by user {current_user_id}")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "User added to group successfully",
                "data": result
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Group or user not found: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except ValidationError as exc:
        logger.warning(f"Group membership validation error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized group membership modification: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error adding user to group: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to add user to group"
        )


@router.delete("/{group_id}/members/{user_id}")
async def remove_user_from_group_endpoint(
    group_id: int,
    user_id: str,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Remove user from group

    Args:
        group_id: Group identifier
        user_id: User identifier
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Success status
    """
    try:
        # Get current user ID from token
        current_user_id, _ = get_current_user_id(authorization)

        # Remove user from group
        success = remove_user_from_single_group(
            group_id=group_id,
            user_id=user_id,
            current_user_id=current_user_id
        )

        if not success:
            raise ValidationError("Failed to remove user from group")

        logger.info(f"Removed user {user_id} from group {group_id} by user {current_user_id}")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "User removed from group successfully"
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Group or user not found: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except ValidationError as exc:
        logger.warning(f"Group membership removal validation error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized group membership modification: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error removing user from group: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to remove user from group"
        )


@router.get("/{group_id}/members")
async def get_group_users_endpoint(group_id: int) -> JSONResponse:
    """
    Get all users in a group

    Args:
        group_id: Group identifier
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: List of group users
    """
    try:
        # Get group users
        users = get_group_users(group_id)

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Group users retrieved successfully",
                "data": users
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Group not found: {group_id}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error retrieving group users: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve group users"
        )


@router.put("/{group_id}/members")
async def update_group_members_endpoint(
    group_id: int,
    request: GroupMembersUpdateRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Update group members by setting the exact list of users.

    Args:
        group_id: Group identifier
        request: Request containing the list of user IDs to set as group members
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Update results with counts
    """
    try:
        # Get current user ID from token
        current_user_id, _ = get_current_user_id(authorization)

        # Update group members
        result = update_group_members(
            group_id=group_id,
            user_ids=request.user_ids,
            current_user_id=current_user_id
        )

        logger.info(f"Updated group {group_id} members by user {current_user_id}: {result}")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Group members updated successfully",
                "data": result
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Group not found for member update: {group_id}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except ValidationError as exc:
        logger.warning(f"Group members update validation error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized group members update attempt: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error during group members update: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update group members"
        )


@router.post("/members/batch")
async def add_user_to_groups_endpoint(
    request: GroupUserRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Add user to multiple groups (batch operation)

    Args:
        request: Batch user addition request containing user_id and group_ids
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Batch operation results
    """
    try:
        # Validate request for batch operation
        if request.group_ids is None or len(request.group_ids) == 0:
            raise ValidationError("group_ids is required for batch operations")

        # Get current user ID from token
        current_user_id, _ = get_current_user_id(authorization)

        # Add user to multiple groups
        results = add_user_to_groups(
            user_id=request.user_id,
            group_ids=request.group_ids,
            current_user_id=current_user_id
        )

        logger.info(f"Batch added user {request.user_id} to {len(request.group_ids)} groups by user {current_user_id}")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Batch user addition completed",
                "data": results
            }
        )

    except ValidationError as exc:
        logger.warning(f"Batch user addition validation error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized batch group membership modification: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error in batch user addition: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to add user to groups"
        )


@router.get("/tenants/{tenant_id}/default")
async def get_tenant_default_group_endpoint(tenant_id: str) -> JSONResponse:
    """
    Get tenant's default group ID

    Args:
        tenant_id: Tenant identifier
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Default group ID
    """
    try:
        # Get default group ID
        default_group_id = get_tenant_default_group_id(tenant_id)

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Default group ID retrieved successfully",
                "data": {
                    "tenant_id": tenant_id,
                    "default_group_id": default_group_id
                }
            }
        )

    except Exception as exc:
        logger.error(f"Unexpected error retrieving default group for tenant {tenant_id}: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve default group"
        )


@router.put("/tenants/{tenant_id}/default")
async def set_tenant_default_group_endpoint(
    tenant_id: str,
    request: SetDefaultGroupRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Set tenant's default group ID

    Args:
        tenant_id: Tenant identifier
        request: Request containing the default group ID to set
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Success status
    """
    try:
        # Get current user ID from token
        user_id, _ = get_current_user_id(authorization)

        # Set default group ID
        success = set_tenant_default_group_id(
            tenant_id=tenant_id,
            group_id=request.default_group_id,
            updated_by=user_id
        )

        if not success:
            raise ValidationError("Failed to set default group")

        logger.info(f"Set default group {request.default_group_id} for tenant {tenant_id} by user {user_id}")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Default group set successfully",
                "data": {
                    "tenant_id": tenant_id,
                    "default_group_id": request.default_group_id
                }
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Tenant or group not found: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except ValidationError as exc:
        logger.warning(f"Validation error setting default group: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized attempt to set default group: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error setting default group for tenant {tenant_id}: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to set default group"
        )
