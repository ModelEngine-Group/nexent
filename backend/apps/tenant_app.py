"""
Tenant management API endpoints
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from http import HTTPStatus
from starlette.responses import JSONResponse

from consts.model import TenantCreateRequest, TenantUpdateRequest
from consts.exceptions import NotFoundException, ValidationError, UnauthorizedError
from services.tenant_service import create_tenant, get_tenant_info, get_all_tenants, update_tenant_info
from utils.auth_utils import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=None)
async def create_tenant_endpoint(
    request: TenantCreateRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Create a new tenant

    Args:
        request: Tenant creation request
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Created tenant information
    """
    try:
        # Get current user ID from token
        user_id, _ = get_current_user_id(authorization)

        # Create tenant
        tenant_info = create_tenant(
            tenant_name=request.tenant_name,
            created_by=user_id
        )

        logger.info(f"Created tenant {tenant_info['tenant_id']} by user {user_id}")

        return JSONResponse(
            status_code=HTTPStatus.CREATED,
            content={
                "message": "Tenant created successfully",
                "data": tenant_info
            }
        )

    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized tenant creation attempt: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except ValidationError as exc:
        logger.warning(f"Tenant creation validation error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error during tenant creation: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to create tenant"
        )


@router.get("/{tenant_id}")
async def get_tenant_endpoint(tenant_id: str) -> JSONResponse:
    """
    Get tenant information by tenant ID

    Args:
        tenant_id: Tenant identifier

    Returns:
        JSONResponse: Tenant information
    """
    try:
        # Get tenant info
        tenant_info = get_tenant_info(tenant_id)

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Tenant retrieved successfully",
                "data": tenant_info
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Tenant not found: {tenant_id}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error retrieving tenant {tenant_id}: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve tenant"
        )


@router.get("")
async def get_all_tenants_endpoint() -> JSONResponse:
    """
    Get all tenants

    Returns:
        JSONResponse: List of all tenants
    """
    try:
        # Get all tenants
        tenants = get_all_tenants()

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Tenants retrieved successfully",
                "data": tenants
            }
        )

    except Exception as exc:
        logger.error(f"Unexpected error retrieving tenants: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve tenants"
        )


@router.put("/{tenant_id}")
async def update_tenant_endpoint(
    tenant_id: str,
    request: TenantUpdateRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Update tenant information

    Args:
        tenant_id: Tenant identifier
        request: Tenant update request
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Updated tenant information
    """
    try:
        # Get current user ID from token
        user_id, _ = get_current_user_id(authorization)

        # Update tenant
        updated_tenant = update_tenant_info(
            tenant_id=tenant_id,
            tenant_name=request.tenant_name,
            updated_by=user_id
        )

        logger.info(f"Updated tenant {tenant_id} by user {user_id}")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Tenant updated successfully",
                "data": updated_tenant
            }
        )

    except NotFoundException as exc:
        logger.warning(f"Tenant not found for update: {tenant_id}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except ValidationError as exc:
        logger.warning(f"Tenant update validation error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized tenant update attempt: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error during tenant update: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update tenant"
        )


@router.delete("/{tenant_id}")
async def delete_tenant_endpoint(
    tenant_id: str,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """
    Delete tenant (placeholder - not yet implemented)

    Args:
        tenant_id: Tenant identifier
        authorization: Bearer token for authentication

    Returns:
        JSONResponse: Deletion result
    """
    try:
        # Get current user ID from token
        user_id, _ = get_current_user_id(authorization)

        # Note: Delete functionality is not yet implemented in the service layer
        # This will raise ValidationError as per current implementation
        raise ValidationError("Tenant deletion is not yet implemented due to complex dependencies")

    except ValidationError as exc:
        logger.warning(f"Tenant deletion not supported: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_IMPLEMENTED,
            detail=str(exc)
        )
    except UnauthorizedError as exc:
        logger.warning(f"Unauthorized tenant deletion attempt: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error(f"Unexpected error during tenant deletion: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to delete tenant"
        )
