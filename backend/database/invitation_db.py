"""
Database operations for invitation code management
"""
from typing import Any, Dict, List, Optional

from database.client import as_dict, get_db_session
from database.db_models import TenantInvitationCode, TenantInvitationRecord
from utils.str_utils import convert_list_to_string


def query_invitation_by_code(invitation_code: str) -> Optional[Dict[str, Any]]:
    """
    Query invitation by invitation code

    Args:
        invitation_code (str): Invitation code

    Returns:
        Optional[Dict[str, Any]]: Invitation record
    """
    with get_db_session() as session:
        result = session.query(TenantInvitationCode).filter(
            TenantInvitationCode.invitation_code == invitation_code,
            TenantInvitationCode.delete_flag == "N"
        ).first()

        if result:
            return as_dict(result)
        return None


def query_invitation_by_id(invitation_id: int) -> Optional[Dict[str, Any]]:
    """
    Query invitation by ID

    Args:
        invitation_id (int): Invitation ID

    Returns:
        Optional[Dict[str, Any]]: Invitation record
    """
    with get_db_session() as session:
        result = session.query(TenantInvitationCode).filter(
            TenantInvitationCode.invitation_id == invitation_id,
            TenantInvitationCode.delete_flag == "N"
        ).first()

        if result:
            return as_dict(result)
        return None


def query_invitations_by_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """
    Query all invitations for a tenant

    Args:
        tenant_id (str): Tenant ID

    Returns:
        List[Dict[str, Any]]: List of invitation records
    """
    with get_db_session() as session:
        result = session.query(TenantInvitationCode).filter(
            TenantInvitationCode.tenant_id == tenant_id,
            TenantInvitationCode.delete_flag == "N"
        ).all()

        return [as_dict(record) for record in result]


def add_invitation(tenant_id: str, invitation_code: str, code_type: str, group_ids: Optional[List[int]] = None,
                          capacity: int = 1, expiry_date: Optional[str] = None,
                          status: str = "IN_USE", created_by: Optional[str] = None) -> int:
    """
    Add a new invitation

    Args:
        tenant_id (str): Tenant ID
        invitation_code (str): Invitation code
        code_type (str): Invitation code type (ADMIN_INVITE, DEV_INVITE, USER_INVITE)
        group_ids (Optional[List[int]]): Associated group IDs
        capacity (int): Invitation capacity
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
            code_type=code_type,
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


def modify_invitation(invitation_id: int, updates: Dict[str, Any], updated_by: Optional[str] = None) -> bool:
    """
    Modify invitation

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


def remove_invitation(invitation_id: int, updated_by: Optional[str] = None) -> bool:
    """
    Remove invitation (soft delete)

    Args:
        invitation_id (int): Invitation ID
        updated_by (Optional[str]): Updated by user

    Returns:
        bool: Whether removal was successful
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


def query_invitation_records(invitation_id: int) -> List[Dict[str, Any]]:
    """
    Query invitation records by invitation ID

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


def add_invitation_record(invitation_id: int, user_id: str, created_by: Optional[str] = None) -> int:
    """
    Add invitation usage record

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


def query_invitation_records_by_user(user_id: str) -> List[Dict[str, Any]]:
    """
    Query invitation records by user ID

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


def count_invitation_usage(invitation_id: int) -> int:
    """
    Count usage for an invitation code

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


def query_invitation_status(invitation_code: str) -> Optional[str]:
    """
    Query invitation status

    Args:
        invitation_code (str): Invitation code

    Returns:
        Optional[str]: Invitation status if exists, None otherwise
    """
    with get_db_session() as session:
        invitation = session.query(TenantInvitationCode).filter(
            TenantInvitationCode.invitation_code == invitation_code,
            TenantInvitationCode.delete_flag == "N"
        ).first()

        return invitation.status if invitation else None


def query_invitations_with_pagination(
    tenant_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
) -> Dict[str, Any]:
    """
    Query invitations with pagination support, including usage count

    Args:
        tenant_id (Optional[str]): Tenant ID to filter by, None for all tenants
        page (int): Page number (1-based)
        page_size (int): Number of items per page

    Returns:
        Dict[str, Any]: Dictionary containing items list and total count
    """
    from sqlalchemy import func, outerjoin

    with get_db_session() as session:
        # Create subquery to count usage records per invitation
        usage_subquery = session.query(
            TenantInvitationRecord.invitation_id,
            func.count(TenantInvitationRecord.invitation_record_id).label('used_times')
        ).filter(
            TenantInvitationRecord.delete_flag == "N"
        ).group_by(TenantInvitationRecord.invitation_id).subquery()

        # Main query with left join to get usage counts
        query = session.query(
            TenantInvitationCode,
            func.coalesce(usage_subquery.c.used_times, 0).label('used_times')
        ).outerjoin(
            usage_subquery,
            TenantInvitationCode.invitation_id == usage_subquery.c.invitation_id
        ).filter(
            TenantInvitationCode.delete_flag == "N"
        )

        # Apply tenant filter if provided
        if tenant_id:
            query = query.filter(TenantInvitationCode.tenant_id == tenant_id)

        # Get total count
        total = query.count()

        # Apply pagination
        offset = (page - 1) * page_size
        results = query.offset(offset).limit(page_size).all()

        # Convert to dict format and add used_times
        items = []
        for invitation_record, used_times in results:
            invitation_dict = as_dict(invitation_record)
            invitation_dict['used_times'] = int(used_times)
            items.append(invitation_dict)

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            # Ceiling division
            "total_pages": (total + page_size - 1) // page_size
        }
