"""
Invitation management API endpoints
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from http import HTTPStatus
from starlette.responses import JSONResponse

from consts.model import (
    InvitationCreateRequest, InvitationUpdateRequest, InvitationListRequest
)
from consts.exceptions import NotFoundException, ValidationError, UnauthorizedError, DuplicateError
from services.invitation_service import (
    create_invitation_code, update_invitation_code, get_invitation_by_code,
    check_invitation_available, use_invitation_code, update_invitation_code_status,
    get_invitations_list, delete_invitation_code
)
from database.user_tenant_db import get_user_tenant_by_user_id
from utils.auth_utils import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.post("/list")
async def list_invitations_endpoint(
    request: InvitationListRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    List invitation codes with pagination

    Args:
        request: Invitation list request with pagination parameters
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Paginated list of invitation codes
    """
    try:
        # Get current user ID from token
        user_id, _ = get_current_user_id(authorization)

        # Get invitations list
        result = get_invitations_list(
            tenant_id=request.tenant_id,
            page=request.page,
            page_size=request.page_size,
            user_id=user_id,
            sort_by=request.sort_by,
            sort_order=request.sort_order
        )

        logger.info(f"User {user_id} retrieved invitation list (tenant: {request.tenant_id or 'all'}, page: {request.page}, size: {request.page_size})")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Invitation codes retrieved successfully",
                "data": result
            }
        )

    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized invitation list access attempt: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error retrieving invitation list: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve invitation codes"
        )


@router.post("")
async def create_invitation_endpoint(
    request: InvitationCreateRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Create a new invitation code

    Args:
        request: Invitation creation request
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Created invitation information
    """
    try:
        # Get current user ID from token
        user_id, _ = get_current_user_id(authorization)

        # Validate tenant_id from request
        tenant_id = request.tenant_id

        # Preprocess request parameters to handle empty values
        invitation_code = request.invitation_code if request.invitation_code else None
        group_ids = request.group_ids if request.group_ids else None
        expiry_date = request.expiry_date if request.expiry_date else None

        # Create invitation code
        invitation_info = create_invitation_code(
            tenant_id=tenant_id,
            code_type=request.code_type,
            invitation_code=invitation_code,
            group_ids=group_ids,
            capacity=request.capacity,
            expiry_date=expiry_date,
            user_id=user_id
        )

        logger.info(f"Created invitation code {invitation_info['invitation_code']} (type: {request.code_type}) for tenant {tenant_id} by user {user_id}")

        return JSONResponse(
            status_code=HTTPStatus.CREATED,
            content={
                "message": "Invitation code created successfully",
                "data": invitation_info
            }
        )

    except ValueError as exc:
        logger.warning(f"Invalid invitation creation parameters: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except DuplicateError as exc:
        logger.warning(f"Duplicate invitation code: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=str(exc)
        )
    except NotFoundException as exc:
        logger.warning(f"User not found during invitation creation: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized invitation creation attempt: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error during invitation creation: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to create invitation code"
        )


@router.put("/{invitation_code}")
async def update_invitation_endpoint(
    invitation_code: str,
    request: InvitationUpdateRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Update invitation code information

    Args:
        invitation_code: Invitation code
        request: Invitation update request
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Success status
    """
    try:
        # Get current user ID from token
        user_id, _ = get_current_user_id(authorization)

        # Get invitation info to find invitation_id
        invitation_info = get_invitation_by_code(invitation_code)
        if not invitation_info:
            raise NotFoundException(f"Invitation code {invitation_code} not found")

        invitation_id = invitation_info["invitation_id"]

        # Prepare updates dict
        updates = {}
        if request.capacity is not None:
            updates["capacity"] = request.capacity
        if request.expiry_date is not None:
            updates["expiry_date"] = request.expiry_date
        if request.group_ids is not None:
            updates["group_ids"] = request.group_ids

        if not updates:
            raise ValidationError("No valid fields provided for update")

        # Update invitation
        success = update_invitation_code(
            invitation_id=invitation_id,
            updates=updates,
            user_id=user_id
        )

        if not success:
            raise ValidationError("Failed to update invitation code")

        logger.info(f"Updated invitation code {invitation_code} by user {user_id}")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Invitation code updated successfully"
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Invitation not found for update: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except ValidationError as exc:
        logger.warning(f"Invitation update validation error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized invitation update attempt: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        import traceback
        logger.error(f"Unexpected error during invitation update: {str(exc)}")
        logger.error(f"Exception type: {type(exc).__name__}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update invitation code"
        )


@router.get("/{invitation_code}")
async def get_invitation_endpoint(invitation_code: str) -> JSONResponse:
    """
    Get invitation information by code

    Args:
        invitation_code: Invitation code

    Returns:
        JSONResponse: Invitation information
    """
    try:
        # Get invitation info
        invitation_info = get_invitation_by_code(invitation_code)

        if not invitation_info:
            raise NotFoundException(f"Invitation code {invitation_code} not found")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Invitation code retrieved successfully",
                "data": invitation_info
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Invitation code not found: {invitation_code}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error retrieving invitation code {invitation_code}: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve invitation code"
        )


@router.get("/{invitation_code}/check")
async def check_invitation_code_endpoint(invitation_code: str) -> JSONResponse:
    """
    Check if invitation code already exists

    Args:
        invitation_code: Invitation code to check

    Returns:
        JSONResponse: Check result with exists flag
    """
    try:
        invitation_info = get_invitation_by_code(invitation_code)
        exists = invitation_info is not None

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Invitation code check completed",
                "data": {
                    "invitation_code": invitation_code,
                    "exists": exists
                }
            }
        )

    except Exception as exc:
        logger.error(f"Unexpected error checking invitation code {invitation_code}: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to check invitation code"
        )


@router.delete("/{invitation_code}")
async def delete_invitation_endpoint(
    invitation_code: str,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Delete invitation code

    Args:
        invitation_code: Invitation code to delete
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Success status
    """
    try:
        # Get current user ID from token
        user_id, _ = get_current_user_id(authorization)

        # Get invitation info to find invitation_id
        invitation_info = get_invitation_by_code(invitation_code)
        if not invitation_info:
            raise NotFoundException(f"Invitation code {invitation_code} not found")

        invitation_id = invitation_info["invitation_id"]

        # Delete invitation code
        success = delete_invitation_code(
            invitation_id=invitation_id,
            user_id=user_id
        )

        if not success:
            raise ValidationError("Failed to delete invitation code")

        logger.info(f"Deleted invitation code {invitation_code} by user {user_id}")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Invitation code deleted successfully"
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Invitation not found for deletion: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except ValidationError as exc:
        logger.warning(f"Invitation deletion validation error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized invitation deletion attempt: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error during invitation deletion: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to delete invitation code"
        )


@router.get("/{invitation_code}/available")
async def check_invitation_available_endpoint(invitation_code: str) -> JSONResponse:
    """
    Check if invitation code is available for use

    Args:
        invitation_code: Invitation code to check

    Returns:
        JSONResponse: Availability status
    """
    try:
        # Check availability
        is_available = check_invitation_available(invitation_code)

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Invitation availability checked successfully",
                "data": {
                    "invitation_code": invitation_code,
                    "available": is_available
                }
            }
        )

    except Exception as exc:
        logger.error(f"Unexpected error checking invitation availability: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to check invitation availability"
        )


@router.post("/{invitation_code}/use")
async def use_invitation_endpoint(
    invitation_code: str,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Use an invitation code

    Args:
        invitation_code: Invitation code to use
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Usage result
    """
    try:
        # Get current user ID from token
        current_user_id, _ = get_current_user_id(authorization)

        # Users can use invitation codes for themselves

        # Use invitation code
        usage_result = use_invitation_code(
            invitation_code=invitation_code,
            user_id=current_user_id
        )

        logger.info(f"User {current_user_id} used invitation code {invitation_code}")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Invitation code used successfully",
                "data": usage_result
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Invitation code not available: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized invitation usage attempt: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error using invitation code: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to use invitation code"
        )


@router.post("/{invitation_code}/update-status")
async def update_invitation_status_endpoint(invitation_code: str) -> JSONResponse:
    """
    Update invitation code status based on expiry and usage

    Args:
        invitation_code: Invitation code
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Status update result
    """
    try:
        # Get invitation info to find invitation_id
        invitation_info = get_invitation_by_code(invitation_code)
        if not invitation_info:
            raise NotFoundException(f"Invitation code {invitation_code} not found")

        invitation_id = invitation_info["invitation_id"]

        # Update status
        status_updated = update_invitation_code_status(invitation_id)

        message = "Invitation status updated" if status_updated else "Invitation status unchanged"

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": message,
                "data": {
                    "invitation_code": invitation_code,
                    "status_updated": status_updated
                }
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Invitation not found for status update: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error updating invitation status: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update invitation status"
        )
