"""
Invitation service for managing invitation codes and records.
"""
import logging
import random
import string
from datetime import datetime
from typing import Optional, Dict, Any, List

from database.invitation_db import (
    query_invitation_by_code,
    query_invitation_by_id,
    add_invitation,
    modify_invitation,
    add_invitation_record,
    count_invitation_usage,
    query_invitations_with_pagination,
    remove_invitation
)
from database.user_tenant_db import get_user_tenant_by_user_id
from database.group_db import query_group_ids_by_user
from consts.exceptions import NotFoundException, UnauthorizedError, DuplicateError
from services.group_service import get_tenant_default_group_id
from utils.str_utils import convert_string_to_list

logger = logging.getLogger(__name__)


def create_invitation_code(
    tenant_id: str,
    code_type: str,
    invitation_code: Optional[str] = None,
    group_ids: Optional[List[int]] = None,
    capacity: int = 1,
    expiry_date: Optional[str] = None,
    status: str = "IN_USE",
    user_id: str = None
) -> Dict[str, Any]:
    """
    Create a new invitation code with business logic.

    Args:
        tenant_id (str): Tenant ID
        code_type (str): Invitation code type (ADMIN_INVITE, DEV_INVITE, USER_INVITE)
        invitation_code (Optional[str]): Invitation code, auto-generated if None
        group_ids (Optional[List[int]]): Associated group IDs
        capacity (int): Invitation code capacity
        expiry_date (Optional[str]): Expiry date
        status (str): Status
        user_id (str): Current user ID

    Returns:
        Dict[str, Any]: Created invitation code information

    Raises:
        NotFoundException: When user not found
        UnauthorizedError: When user doesn't have permission
        ValueError: When code_type is invalid
    """
    # Validate code_type
    valid_code_types = ["ADMIN_INVITE", "DEV_INVITE", "USER_INVITE"]
    if code_type not in valid_code_types:
        raise ValueError(f"Invalid code_type: {code_type}. Must be one of {valid_code_types}")

    # Get user information
    user_info = get_user_tenant_by_user_id(user_id)
    if not user_info:
        raise NotFoundException(f"User {user_id} not found")

    user_role = user_info.get("user_role", "USER")

    # Check permission based on code_type
    if code_type == "ADMIN_INVITE" and user_role not in ["SU"]:
        raise UnauthorizedError(f"User role {user_role} not authorized to create ADMIN_INVITE codes")
    elif code_type in ["DEV_INVITE", "USER_INVITE"] and user_role not in ["SU", "ADMIN"]:
        raise UnauthorizedError(f"User role {user_role} not authorized to create {code_type} codes")

    # Set default group_ids based on code_type if not provided
    if group_ids is None:
        if code_type == "ADMIN_INVITE":
            # For admin invites, try to use tenant default group, fallback to empty list
            default_group_id = get_tenant_default_group_id(tenant_id)
            group_ids = [default_group_id] if default_group_id else []
        elif code_type in ["DEV_INVITE", "USER_INVITE"]:
            group_ids = query_group_ids_by_user(user_id)
        else:
            group_ids = []

    # Generate invitation code if not provided
    if not invitation_code:
        invitation_code = _generate_unique_invitation_code()
    else:
        # Change to upper case by default
        invitation_code = invitation_code.upper()

    # Check if invitation code already exists
    if query_invitation_by_code(invitation_code):
        raise DuplicateError(f"Invitation code '{invitation_code}' already exists")

    # Create invitation (status will be set automatically)
    invitation_id = add_invitation(
        tenant_id=tenant_id,
        invitation_code=invitation_code,
        code_type=code_type,
        group_ids=group_ids,
        capacity=capacity,
        expiry_date=expiry_date,
        status=status,
        created_by=user_id
    )

    # Automatically update status based on expiry date and capacity
    update_invitation_code_status(invitation_id)

    logger.info(f"Created invitation code {invitation_code} (type: {code_type}) for tenant {tenant_id} by user {user_id}")

    # Get the final invitation info with correct status
    invitation_info = query_invitation_by_id(invitation_id)
    normalized_info = _normalize_invitation_data(invitation_info) if invitation_info else None

    return {
        "invitation_id": invitation_id,
        "invitation_code": invitation_code,
        "code_type": code_type,
        "group_ids": group_ids,
        "capacity": capacity,
        "expiry_date": expiry_date,
        "status": normalized_info.get("status", "IN_USE") if normalized_info else "IN_USE"
    }


def update_invitation_code(
    invitation_id: int,
    updates: Dict[str, Any],
    user_id: str
) -> bool:
    """
    Update invitation code information.

    Args:
        invitation_id (int): Invitation ID
        updates (Dict[str, Any]): Fields to update
        user_id (str): Current user ID

    Returns:
        bool: Whether update was successful

    Raises:
        UnauthorizedError: When user doesn't have permission
    """
    # Check user permission
    user_info = get_user_tenant_by_user_id(user_id)
    if not user_info:
        raise UnauthorizedError(f"User {user_id} not found")

    user_role = user_info.get("user_role", "USER")
    if user_role not in ["SU", "ADMIN"]:
        raise UnauthorizedError(f"User role {user_role} not authorized to update invitation codes")

    # Update invitation code
    success = modify_invitation(
        invitation_id=invitation_id,
        updates=updates,
        updated_by=user_id
    )

    if success:
        logger.info(f"Updated invitation code {invitation_id} by user {user_id}")
        # Automatically update status after successful update
        update_invitation_code_status(invitation_id)

    return success


def delete_invitation_code(invitation_id: int, user_id: str) -> bool:
    """
    Delete invitation code (soft delete).

    Args:
        invitation_id (int): Invitation ID to delete
        user_id (str): Current user ID for permission checks

    Returns:
        bool: Whether deletion was successful

    Raises:
        UnauthorizedError: When user doesn't have permission to delete
        NotFoundException: When invitation not found
    """
    # Check user permission
    user_info = get_user_tenant_by_user_id(user_id)
    if not user_info:
        raise UnauthorizedError(f"User {user_id} not found")

    user_role = user_info.get("user_role", "USER")
    if user_role not in ["SU", "ADMIN"]:
        raise UnauthorizedError(
            f"User role {user_role} not authorized to delete invitation codes")

    # Check if invitation exists
    invitation_info = query_invitation_by_id(invitation_id)
    if not invitation_info:
        raise NotFoundException(f"Invitation {invitation_id} not found")

    # Delete invitation code
    success = remove_invitation(
        invitation_id=invitation_id, updated_by=user_id)

    if success:
        logger.info(
            f"Deleted invitation code {invitation_id} by user {user_id}")

    return success


def _normalize_invitation_data(invitation_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize invitation data types for consistent API responses.

    Args:
        invitation_data: Raw invitation data from database

    Returns:
        Normalized invitation data with correct types
    """
    if not invitation_data:
        return invitation_data

    # Create a copy to avoid modifying the original
    normalized = invitation_data.copy()

    # Convert datetime objects to ISO format strings
    for key, value in normalized.items():
        if isinstance(value, datetime):
            normalized[key] = value.isoformat()

    # Ensure correct data types
    if "invitation_id" in normalized:
        normalized["invitation_id"] = int(normalized["invitation_id"])
    if "capacity" in normalized:
        normalized["capacity"] = int(normalized["capacity"])
    if "group_ids" in normalized:
        # Convert group_ids string back to list
        group_ids_value = normalized["group_ids"]
        if isinstance(group_ids_value, str):
            normalized["group_ids"] = convert_string_to_list(group_ids_value)
        elif group_ids_value is None:
            normalized["group_ids"] = []

    return normalized


def get_invitation_by_code(invitation_code: str) -> Optional[Dict[str, Any]]:
    """
    Get invitation code information by code.

    Args:
        invitation_code (str): Invitation code

    Returns:
        Optional[Dict[str, Any]]: Invitation code information or None if not found
    """
    invitation_data = query_invitation_by_code(invitation_code)
    if invitation_data:
        # Calculate current status to ensure expiry and capacity checks are current
        invitation_data = _calculate_current_status(invitation_data)
    return _normalize_invitation_data(invitation_data) if invitation_data else None


def _calculate_current_status(invitation_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate the current status of an invitation based on expiry and usage.

    Args:
        invitation_data: Raw invitation data from database

    Returns:
        Updated invitation data with current status
    """
    if not invitation_data:
        return invitation_data

    invitation_id = invitation_data.get("invitation_id")
    if not invitation_id:
        return invitation_data

    current_time = datetime.now()
    expiry_date = invitation_data.get("expiry_date")
    capacity = int(invitation_data.get("capacity", 1))

    # Get usage count
    usage_count = count_invitation_usage(invitation_id)
    current_status = invitation_data.get("status", "IN_USE")

    new_status = current_status

    # Check expiry
    if expiry_date:
        try:
            if isinstance(expiry_date, datetime):
                expiry_datetime = expiry_date
            else:
                expiry_datetime = datetime.fromisoformat(
                    str(expiry_date).replace('Z', '+00:00'))
            # Treat same date as not expired - only expire when current date is strictly after expiry date
            if current_time.date() > expiry_datetime.date():
                new_status = "EXPIRE"
        except (ValueError, AttributeError, TypeError):
            logger.warning(f"Invalid expiry_date format for invitation {invitation_id}: {expiry_date}")

    # Check capacity
    if usage_count >= capacity:
        new_status = "RUN_OUT"

    # Update status in the data dict
    invitation_data["status"] = new_status
    return invitation_data


def check_invitation_available(invitation_code: str) -> bool:
    """
    Check if invitation is available for use.

    Args:
        invitation_code (str): Invitation code

    Returns:
        bool: Whether the code is available
    """
    invitation = query_invitation_by_code(invitation_code)
    if not invitation:
        return False

    # Check status
    if invitation.get("status") != "IN_USE":
        return False

    # Check capacity
    usage_count = count_invitation_usage(invitation["invitation_id"])
    return usage_count < invitation["capacity"]


def use_invitation_code(
    invitation_code: str,
    user_id: str
) -> Dict[str, Any]:
    """
    Use an invitation code by creating a usage record.
    
    Args:
        invitation_code (str): Invitation code to use
        user_id (str): User ID using the code

    Returns:
        Dict[str, Any]: Invitation usage result including code_type

    Raises:
        NotFoundException: When invitation code not found or not available
    """
    # Check if invitation is available
    if not check_invitation_available(invitation_code):
        raise NotFoundException(f"Invitation code {invitation_code} is not available")

    # Get invitation code details
    invitation_info = query_invitation_by_code(invitation_code)
    if not invitation_info:
        raise NotFoundException(f"Invitation code {invitation_code} not found")

    # Create usage record
    record_id = add_invitation_record(
        invitation_id=invitation_info["invitation_id"],
        user_id=user_id,
        created_by=user_id
    )

    # Update invitation status
    update_invitation_code_status(invitation_info["invitation_id"])

    logger.info(f"User {user_id} used invitation code {invitation_code}")

    return {
        "invitation_record_id": record_id,
        "invitation_code": invitation_code,
        "user_id": user_id,
        "invitation_id": invitation_info["invitation_id"],
        "code_type": invitation_info["code_type"],
        "group_ids": invitation_info["group_ids"]
    }


def update_invitation_code_status(invitation_id: int) -> bool:
    """
    Update invitation code status based on expiry date and usage count.

    Args:
        invitation_id (int): Invitation ID

    Returns:
        bool: Whether status was updated
    """
    # Get invitation code details
    invitation_info = query_invitation_by_id(invitation_id)
    if not invitation_info:
        return False

    current_time = datetime.now()
    expiry_date = invitation_info.get("expiry_date")
    capacity = int(invitation_info["capacity"])

    usage_count = count_invitation_usage(invitation_id)
    current_status = invitation_info["status"]

    # Determine new status based on current conditions
    # Priority: EXPIRE > RUN_OUT > IN_USE
    new_status = "IN_USE"

    # Check expiry first (highest priority)
    if expiry_date:
        try:
            if isinstance(expiry_date, datetime):
                expiry_datetime = expiry_date
            else:
                expiry_datetime = datetime.fromisoformat(
                    str(expiry_date).replace('Z', '+00:00'))
            # Treat same date as not expired - only expire when current date is strictly after expiry date
            if current_time.date() > expiry_datetime.date():
                new_status = "EXPIRE"
        except (ValueError, AttributeError, TypeError):
            logger.warning(f"Invalid expiry_date format for invitation {invitation_id}: {expiry_date}")

    # Check capacity if not expired
    if new_status == "IN_USE" and usage_count >= capacity:
        new_status = "RUN_OUT"

    # Update status if changed
    if new_status != current_status:
        modify_invitation(
            invitation_id=invitation_id,
            updates={"status": new_status},
            updated_by="system"
        )
        logger.info(f"Updated invitation code {invitation_id} status to {new_status}")
        return True

    return False


def _generate_unique_invitation_code(length: int = 6) -> str:
    """
    Generate a unique invitation code.

    Args:
        length (int): Code length

    Returns:
        str: Unique invitation code
    """
    max_attempts = 100  # Prevent infinite loop
    attempts = 0

    while attempts < max_attempts:
        # Generate random code with letters and digits
        code = ''.join(random.choices(string.ascii_letters + string.digits, k=length))

        # Check uniqueness
        if not query_invitation_by_code(code):
            return code.upper()

        attempts += 1

    raise RuntimeError(f"Failed to generate unique invitation code after {max_attempts} attempts")


def get_invitations_list(
    tenant_id: Optional[str],
    page: int,
    page_size: int,
    user_id: str,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get invitations list with pagination and permission checks.

    Args:
        tenant_id (Optional[str]): Tenant ID to filter by, None for all tenants
        page (int): Page number
        page_size (int): Number of items per page
        user_id (str): Current user ID for permission checks
        sort_by (Optional[str]): Sort field
        sort_order (Optional[str]): Sort order ('asc' or 'desc')

    Returns:
        Dict[str, Any]: Paginated invitation list result

    Raises:
        UnauthorizedError: When user doesn't have permission to view the requested data
    """
    # Get user information for permission checks
    user_info = get_user_tenant_by_user_id(user_id)
    if not user_info:
        raise UnauthorizedError(f"User {user_id} not found")

    user_role = user_info.get("user_role", "USER")

    # Permission logic:
    # - If tenant_id is provided: ADMIN or SU can view that tenant's invitations
    # - If tenant_id is not provided: Only SU can view all invitations
    if tenant_id:
        # If tenant_id is specified, user must be ADMIN/SU
        if user_role not in ["SU", "ADMIN"]:
            raise UnauthorizedError(
                f"User role {user_role} not authorized to view invitation lists")
    else:
        # If no tenant_id specified, only SU can view all invitations
        if user_role not in ["SU"]:
            raise UnauthorizedError(
                f"User role {user_role} not authorized to view all tenant invitations")

    # Query invitations with pagination
    result = query_invitations_with_pagination(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order
    )

    logger.info(
        f"User {user_id} queried invitations list (tenant: {tenant_id or 'all'}, page: {page}, size: {page_size})")

    # Normalize each invitation item in the list
    if result and "items" in result:
        result["items"] = [_normalize_invitation_data(item) for item in result["items"]]

    return result
