# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""
Invitation service for managing invitation codes and records.
"""

import logging
import random
import string
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from contracts.constants.constants import (
    ASSET_OWNER_INVITE_CODE_TYPE,
    ASSET_OWNER_TENANT_ID,
)
from contracts.errors.exceptions import (
    DuplicateError,
    ForbiddenError,
    IncorrectInviteCodeException,
    NotFoundException,
    UnauthorizedError,
)
from contracts.roles import (
    has_any_role,
    invitation_roles,
    normalize_roles,
    roles_from_record,
)
from management.db.client import get_db_session
from management.db.identity.group import query_group_ids_by_user, query_groups
from management.db.identity.invitation import (
    add_invitation,
    count_invitation_usage,
    modify_invitation,
    query_invitation_by_code,
    query_invitation_by_id,
    query_invitations_with_pagination,
    remove_invitation,
)
from management.db.identity.roles import lock_tenants, locked_members
from management.db.identity.user_tenant import get_user_tenant_by_user_id
from management.db.models import TenantInvitationCode, TenantInvitationRecord
from management.services.permission.asset_owner import require_asset_owner_enabled
from management.services.permission.identity.groups import get_tenant_default_group_id
from management.services.permission.identity.registration import (
    invitation_usage,
    locked_invitation,
)
from management.utils.serialization import convert_string_to_list

logger = logging.getLogger(__name__)


def create_invitation_code(
    tenant_id: str,
    code_type: Optional[str] = None,
    invitation_code: Optional[str] = None,
    group_ids: Optional[List[int]] = None,
    capacity: int = 1,
    expiry_date: Optional[str] = None,
    status: str = "IN_USE",
    user_id: str = None,
    roles=None,
) -> Dict[str, Any]:
    """Create a fixed grant using the same ordinary role policy as user editing."""
    actor = get_user_tenant_by_user_id(user_id)
    if not actor:
        raise UnauthorizedError("User not found")
    actor_roles = roles_from_record(actor)
    if not has_any_role(actor_roles, {"SU", "ADMIN"}):
        raise ForbiddenError("Not authorized to create invitations")
    special = code_type == ASSET_OWNER_INVITE_CODE_TYPE
    if special:
        require_asset_owner_enabled()
        if not has_any_role(actor_roles, {"SU"}):
            raise UnauthorizedError("Asset owner invitations require platform administration")
        assigned = ("ASSET_OWNER",)
        if roles is not None and normalize_roles(roles) != assigned:
            raise ValueError("Invitation role and type conflict")
        tenant_id, group_ids = ASSET_OWNER_TENANT_ID, []
    else:
        assigned = invitation_roles({"roles": roles, "code_type": code_type})
        normalize_roles(assigned, ordinary_only=True)
        if not has_any_role(actor_roles, {"SU"}) and tenant_id != actor["tenant_id"]:
            raise ForbiddenError("Cannot invite users into another tenant")
        if roles is not None and code_type and code_type != "TENANT_INVITE":
            if invitation_roles({"code_type": code_type}) != assigned:
                raise ValueError("Invitation role and type conflict")
        code_type = {("ADMIN",): "ADMIN_INVITE", ("DEV",): "DEV_INVITE", ("USER",): "USER_INVITE"}.get(
            assigned, "TENANT_INVITE"
        )
    if capacity < 1:
        raise ValueError("Invitation capacity must be positive")
    if group_ids is None:
        if "ADMIN" in assigned:
            default_group = get_tenant_default_group_id(tenant_id)
            group_ids = [default_group] if default_group else []
        else:
            group_ids = query_group_ids_by_user(user_id) if not special and tenant_id == actor["tenant_id"] else []
    if group_ids:
        groups = query_groups(group_ids)
        if isinstance(groups, dict):
            groups = [groups]
        if {int(g["group_id"]) for g in groups if g.get("tenant_id") == tenant_id} != {int(g) for g in group_ids}:
            raise ForbiddenError("Invitation groups must belong to the target tenant")
    invitation_code = invitation_code.upper() if invitation_code else _generate_unique_invitation_code()
    if query_invitation_by_code(invitation_code):
        raise DuplicateError("Invitation code already exists")
    with get_db_session() as session:
        lock_tenants(session, [tenant_id, actor["tenant_id"]])
        locked_actor = locked_members(session, [user_id]).get(user_id)
        _check_invitation_manager(locked_actor, tenant_id, special)
        invitation_id = add_invitation(
            tenant_id=tenant_id,
            invitation_code=invitation_code,
            code_type=code_type,
            roles=list(assigned),
            group_ids=group_ids,
            capacity=capacity,
            expiry_date=expiry_date,
            status=status,
            created_by=user_id,
            db_session=session,
        )
    return {
        "invitation_id": invitation_id,
        "invitation_code": invitation_code,
        "code_type": code_type,
        "roles": list(assigned),
        "group_ids": group_ids,
        "capacity": capacity,
        "expiry_date": expiry_date,
        "status": status,
    }


def update_invitation_code(invitation_id: int, updates: Dict[str, Any], user_id: str) -> bool:
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

    user_role = roles_from_record(user_info)

    invitation_info = query_invitation_by_id(invitation_id)
    if not invitation_info:
        raise NotFoundException(f"Invitation {invitation_id} not found")

    if not has_any_role(user_role, {"SU"}) and invitation_info["tenant_id"] != user_info["tenant_id"]:
        raise ForbiddenError("Cannot manage another tenant's invitations")
    code_type = invitation_info.get("code_type")
    if code_type == ASSET_OWNER_INVITE_CODE_TYPE and not has_any_role(user_role, {"SU"}):
        raise UnauthorizedError(f"User role {user_role} not authorized to update invitation codes")
    elif not has_any_role(user_role, {"SU", "ADMIN"}):
        raise UnauthorizedError(f"User role {user_role} not authorized to update invitation codes")

    if "roles" in updates or "code_type" in updates:
        raise ValueError("Invitation roles are immutable")
    if updates.get("group_ids"):
        groups = query_groups(updates["group_ids"])
        groups = [groups] if isinstance(groups, dict) else groups
        if {int(g["group_id"]) for g in groups if g.get("tenant_id") == invitation_info["tenant_id"]} != set(
            updates["group_ids"]
        ):
            raise ForbiddenError("Invitation groups must belong to the target tenant")
    with _managed_invitation(invitation_id, user_id) as (session, row):
        success = modify_invitation(invitation_id, updates, user_id, db_session=session)
        session.expire(row)
        if row.status != "DISABLE":
            if row.expiry_date and row.expiry_date.date() < datetime.utcnow().date():
                row.status = "EXPIRE"
            elif invitation_usage(session, row.invitation_id) >= row.capacity:
                row.status = "RUN_OUT"
            else:
                row.status = "IN_USE"
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

    user_role = roles_from_record(user_info)

    invitation_info = query_invitation_by_id(invitation_id)
    if not invitation_info:
        raise NotFoundException(f"Invitation {invitation_id} not found")

    if not has_any_role(user_role, {"SU"}) and invitation_info["tenant_id"] != user_info["tenant_id"]:
        raise ForbiddenError("Cannot manage another tenant's invitations")
    code_type = invitation_info.get("code_type")
    if code_type == ASSET_OWNER_INVITE_CODE_TYPE and not has_any_role(user_role, {"SU"}):
        raise UnauthorizedError(f"User role {user_role} not authorized to delete invitation codes")
    elif not has_any_role(user_role, {"SU", "ADMIN"}):
        raise UnauthorizedError(f"User role {user_role} not authorized to delete invitation codes")

    with _managed_invitation(invitation_id, user_id) as (session, row):
        return remove_invitation(invitation_id, user_id, db_session=session)


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
    normalized = dict(invitation_data)
    if "roles" in normalized or "code_type" in normalized:
        normalized["roles"] = list(invitation_roles(normalized))

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
    invitation_data = dict(invitation_data)

    invitation_id = invitation_data.get("invitation_id")
    if not invitation_id:
        return invitation_data

    current_time = datetime.now()
    expiry_date = invitation_data.get("expiry_date")
    capacity = int(invitation_data.get("capacity", 1))

    # Get usage count
    usage_count = count_invitation_usage(invitation_id)
    current_status = invitation_data.get("status", "IN_USE")

    if current_status == "DISABLE":
        return invitation_data
    new_status = current_status

    # Check expiry
    if expiry_date:
        try:
            if isinstance(expiry_date, datetime):
                expiry_datetime = expiry_date
            else:
                expiry_datetime = datetime.fromisoformat(str(expiry_date).replace("Z", "+00:00"))
            # Treat same date as not expired - only expire when current date is strictly after expiry date
            if current_time.date() > expiry_datetime.date():
                new_status = "EXPIRE"
        except (ValueError, AttributeError, TypeError):
            logger.warning(f"Invalid expiry_date format for invitation {invitation_id}: {expiry_date}")

    # Check capacity
    if new_status != "EXPIRE":
        new_status = "RUN_OUT" if usage_count >= capacity else "IN_USE"

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

    if invitation.get("status") != "IN_USE":
        return False
    invitation = _calculate_current_status(invitation)
    # Check status
    if invitation.get("status") != "IN_USE":
        return False

    return True


def use_invitation_code(invitation_code: str, user_id: str) -> Dict[str, Any]:
    """Record an existing matching membership once, without granting extra roles."""
    code = invitation_code.strip().upper()
    snapshot = query_invitation_by_code(code)
    if not snapshot:
        raise NotFoundException("Invitation is unavailable")
    with get_db_session() as session:
        row = locked_invitation(session, code, snapshot)
        member = locked_members(session, [user_id]).get(user_id)
        if (
            not member
            or member["tenant_id"] != row.tenant_id
            or roles_from_record(member) != invitation_roles({"roles": row.roles})
        ):
            raise ForbiddenError("Invitation usage requires its matching registered membership")
        record = session.execute(
            select(TenantInvitationRecord).where(
                TenantInvitationRecord.invitation_id == row.invitation_id,
                TenantInvitationRecord.user_id == user_id,
                TenantInvitationRecord.delete_flag == "N",
            )
        ).scalar_one_or_none()
        if record is None:
            if row.status != "IN_USE" or invitation_usage(session, row.invitation_id) >= row.capacity:
                raise IncorrectInviteCodeException("Invitation capacity is exhausted")
            record = TenantInvitationRecord(
                invitation_id=row.invitation_id,
                user_id=user_id,
                created_by=user_id,
                updated_by=user_id,
                delete_flag="N",
            )
            session.add(record)
            session.flush()
            if invitation_usage(session, row.invitation_id) >= row.capacity:
                row.status = "RUN_OUT"
        return {
            "invitation_record_id": record.invitation_record_id,
            "invitation_code": code,
            "user_id": user_id,
            "invitation_id": row.invitation_id,
            "code_type": row.code_type,
            "roles": list(row.roles),
            "group_ids": convert_string_to_list(row.group_ids) if row.group_ids else [],
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
    if current_status == "DISABLE":
        return False

    # Determine new status based on current conditions
    # Priority: EXPIRE > RUN_OUT > IN_USE
    new_status = "IN_USE"

    # Check expiry first (highest priority)
    if expiry_date:
        try:
            if isinstance(expiry_date, datetime):
                expiry_datetime = expiry_date
            else:
                expiry_datetime = datetime.fromisoformat(str(expiry_date).replace("Z", "+00:00"))
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
        modify_invitation(invitation_id=invitation_id, updates={"status": new_status}, updated_by="system")
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
        code = "".join(random.choices(string.ascii_letters + string.digits, k=length))

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
    sort_order: Optional[str] = None,
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

    user_role = roles_from_record(user_info)

    read_only = has_any_role(user_role, {"OPS"}) and not has_any_role(user_role, {"SU", "ADMIN"})

    # Permission logic:
    # - If tenant_id is provided: ADMIN or SU can view that tenant's invitations
    # - If tenant_id is not provided: Only SU can view all invitations
    if tenant_id is not None:
        # ASSET_OWNER_TENANT_ID virtual tenant_id is used for asset-owner invites (SU only)
        if tenant_id == ASSET_OWNER_TENANT_ID:
            if not has_any_role(user_role, {"SU"}):
                raise UnauthorizedError(f"User role {user_role} not authorized to view asset owner invitations")
        elif not has_any_role(user_role, {"SU", "ADMIN", "OPS"}):
            raise UnauthorizedError(f"User role {user_role} not authorized to view invitation lists")
    else:
        # If no tenant_id specified, only SU can view all invitations
        if not has_any_role(user_role, {"SU"}):
            raise UnauthorizedError(f"User role {user_role} not authorized to view all tenant invitations")

    if not has_any_role(user_role, {"SU"}) and tenant_id != user_info["tenant_id"]:
        raise ForbiddenError("Cannot list another tenant's invitations")

    # Query invitations with pagination
    result = query_invitations_with_pagination(
        tenant_id=tenant_id, page=page, page_size=page_size, sort_by=sort_by, sort_order=sort_order
    )

    logger.info(
        f"User {user_id} queried invitations list (tenant: {tenant_id or 'all'}, page: {page}, size: {page_size})"
    )

    # Normalize each invitation item in the list
    if result and "items" in result:
        result["items"] = [_normalize_invitation_data(item) for item in result["items"]]
        if read_only:
            for item in result["items"]:
                item["invitation_code"] = ""

    return result


def _check_invitation_manager(actor, tenant_id, special=False):
    if not actor:
        raise ForbiddenError("Acting user is unavailable")
    roles = roles_from_record(actor)
    if has_any_role(roles, {"SU"}):
        return
    if special or not has_any_role(roles, {"ADMIN"}) or actor["tenant_id"] != tenant_id:
        raise ForbiddenError("Not authorized to manage these invitations")


@contextmanager
def _managed_invitation(invitation_id, user_id):
    snapshot = query_invitation_by_id(invitation_id)
    actor = get_user_tenant_by_user_id(user_id)
    if not snapshot or not actor:
        raise NotFoundException("Invitation or acting user is unavailable")
    with get_db_session() as session:
        lock_tenants(session, [snapshot["tenant_id"], actor["tenant_id"]])
        actor = locked_members(session, [user_id]).get(user_id)
        row = session.execute(
            select(TenantInvitationCode)
            .where(TenantInvitationCode.invitation_id == invitation_id, TenantInvitationCode.delete_flag == "N")
            .with_for_update()
        ).scalar_one_or_none()
        if row is None or row.tenant_id != snapshot["tenant_id"]:
            raise NotFoundException("Invitation is unavailable")
        _check_invitation_manager(actor, row.tenant_id, row.code_type == ASSET_OWNER_INVITE_CODE_TYPE)
        yield session, row
