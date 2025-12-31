"""
Database operations for invitation code management
"""
from typing import Any, Dict, List, Optional

from database.client import as_dict, get_db_session
from database.db_models import TenantInvitationCode, TenantInvitationRecord
from utils.str_utils import convert_list_to_string


def get_invitation_code_by_code(invitation_code: str) -> Optional[Dict[str, Any]]:
    """
    Get invitation code by invitation code

    Args:
        invitation_code (str): Invitation code

    Returns:
        Optional[Dict[str, Any]]: Invitation code record
    """
    with get_db_session() as session:
        result = session.query(TenantInvitationCode).filter(
            TenantInvitationCode.invitation_code == invitation_code,
            TenantInvitationCode.delete_flag == "N"
        ).first()

        if result:
            return as_dict(result)
        return None


def get_invitation_codes_by_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """
    Get all invitation codes for a tenant

    Args:
        tenant_id (str): Tenant ID

    Returns:
        List[Dict[str, Any]]: List of invitation code records
    """
    with get_db_session() as session:
        result = session.query(TenantInvitationCode).filter(
            TenantInvitationCode.tenant_id == tenant_id,
            TenantInvitationCode.delete_flag == "N"
        ).all()

        return [as_dict(record) for record in result]


def create_invitation_code(tenant_id: str, invitation_code: str, group_ids: Optional[List[int]] = None,
                          capacity: int = 1, expiry_date: Optional[str] = None,
                          status: str = "IN_USE", created_by: Optional[str] = None) -> int:
    """
    Create a new invitation code

    Args:
        tenant_id (str): Tenant ID
        invitation_code (str): Invitation code
        group_ids (Optional[List[int]]): Associated group IDs
        capacity (int): Invitation code capacity
        expiry_date (Optional[str]): Expiry date
        status (str): Status
        created_by (Optional[str]): Created by user

    Returns:
        int: Created invitation ID
    """
    with get_db_session() as session:
        invitation = TenantInvitationCode(
            tenant_id=tenant_id,
            invitation_code=invitation_code,
            group_ids=convert_list_to_string(group_ids),
            capacity=capacity,
            expiry_date=expiry_date,
            status=status,
            created_by=created_by,
            updated_by=created_by
        )
        session.add(invitation)
        session.flush()  # To get the ID
        return invitation.invitation_id


def update_invitation_code(invitation_id: int, updates: Dict[str, Any], updated_by: Optional[str] = None) -> bool:
    """
    Update invitation code

    Args:
        invitation_id (int): Invitation ID
        updates (Dict[str, Any]): Fields to update
        updated_by (Optional[str]): Updated by user

    Returns:
        bool: Whether update was successful
    """
    with get_db_session() as session:
        update_data = updates.copy()
        if updated_by:
            update_data["updated_by"] = updated_by

        # Convert group_ids list to string if present
        if "group_ids" in update_data and isinstance(update_data["group_ids"], list):
            update_data["group_ids"] = convert_list_to_string(update_data["group_ids"])

        result = session.query(TenantInvitationCode).filter(
            TenantInvitationCode.invitation_id == invitation_id,
            TenantInvitationCode.delete_flag == "N"
        ).update(update_data, synchronize_session=False)

        return result > 0


def soft_delete_invitation_code(invitation_id: int, updated_by: Optional[str] = None) -> bool:
    """
    Soft delete invitation code

    Args:
        invitation_id (int): Invitation ID
        updated_by (Optional[str]): Updated by user

    Returns:
        bool: Whether deletion was successful
    """
    with get_db_session() as session:
        update_data: Dict[str, Any] = {"delete_flag": "Y"}
        if updated_by:
            update_data["updated_by"] = updated_by

        result = session.query(TenantInvitationCode).filter(
            TenantInvitationCode.invitation_id == invitation_id,
            TenantInvitationCode.delete_flag == "N"
        ).update(update_data, synchronize_session=False)

        return result > 0


def get_invitation_records_by_invitation(invitation_id: int) -> List[Dict[str, Any]]:
    """
    Get invitation records by invitation ID

    Args:
        invitation_id (int): Invitation ID

    Returns:
        List[Dict[str, Any]]: List of invitation records
    """
    with get_db_session() as session:
        result = session.query(TenantInvitationRecord).filter(
            TenantInvitationRecord.invitation_id == invitation_id,
            TenantInvitationRecord.delete_flag == "N"
        ).all()

        return [as_dict(record) for record in result]


def create_invitation_record(invitation_id: int, user_id: str, created_by: Optional[str] = None) -> int:
    """
    Create invitation usage record

    Args:
        invitation_id (int): Invitation ID
        user_id (str): User ID
        created_by (Optional[str]): Created by user

    Returns:
        int: Created invitation record ID
    """
    with get_db_session() as session:
        record = TenantInvitationRecord(
            invitation_id=invitation_id,
            user_id=user_id,
            created_by=created_by,
            updated_by=created_by
        )
        session.add(record)
        session.flush()  # To get the ID
        return record.invitation_record_id


def get_invitation_records_by_user(user_id: str) -> List[Dict[str, Any]]:
    """
    Get invitation records by user ID

    Args:
        user_id (str): User ID

    Returns:
        List[Dict[str, Any]]: List of invitation records
    """
    with get_db_session() as session:
        result = session.query(TenantInvitationRecord).filter(
            TenantInvitationRecord.user_id == user_id,
            TenantInvitationRecord.delete_flag == "N"
        ).all()

        return [as_dict(record) for record in result]


def get_invitation_usage_count(invitation_id: int) -> int:
    """
    Get usage count for an invitation code

    Args:
        invitation_id (int): Invitation ID

    Returns:
        int: Number of times the invitation has been used
    """
    with get_db_session() as session:
        result = session.query(TenantInvitationRecord).filter(
            TenantInvitationRecord.invitation_id == invitation_id,
            TenantInvitationRecord.delete_flag == "N"
        ).count()

        return result


def check_invitation_code_available(invitation_code: str) -> bool:
    """
    Check if invitation code is available for use

    Args:
        invitation_code (str): Invitation code

    Returns:
        bool: Whether the code is available
    """
    with get_db_session() as session:
        invitation = session.query(TenantInvitationCode).filter(
            TenantInvitationCode.invitation_code == invitation_code,
            TenantInvitationCode.status == "IN_USE",
            TenantInvitationCode.delete_flag == "N"
        ).first()

        if not invitation:
            return False

        # Check capacity
        usage_count = get_invitation_usage_count(invitation.invitation_id)
        return usage_count < invitation.capacity
