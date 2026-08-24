"""
Database operations for user API token (API Key) management.
"""
import secrets
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import aliased

from database.client import get_db_session
from database.db_models import UserTenant, UserTokenInfo, UserTokenUsageLog


def generate_access_key() -> str:
    """Generate a random access key with format nexent-xxxxx..."""
    random_part = secrets.token_hex(12)  # 24 hex characters for more entropy
    return f"nexent-{random_part}"


def create_token(
    access_key: str,
    user_id: str,
    created_by: Optional[str] = None,
    db_session=None,
) -> Dict[str, Any]:
    """Create a new token record in the database.

    Args:
        access_key: The access key (API Key).
        user_id: The user ID who owns this token.

    Returns:
        Dictionary containing the created token information.
    """
    session_context = get_db_session() if db_session is None else get_db_session(db_session)
    with session_context as session:
        actor = created_by or user_id
        token = UserTokenInfo(
            access_key=access_key,
            user_id=user_id,
            created_by=actor,
            updated_by=actor,
            delete_flag='N'
        )
        session.add(token)
        session.flush()

        return {
            "token_id": token.token_id,
            "access_key": token.access_key,
            "user_id": token.user_id
        }


def list_tokens_by_user(user_id: str) -> List[Dict[str, Any]]:
    """List all active tokens for the specified user.

    Args:
        user_id: The user ID to query tokens for.

    Returns:
        List of token information with masked access keys.
    """
    with get_db_session() as session:
        tokens = session.query(UserTokenInfo).filter(
            UserTokenInfo.user_id == user_id,
            UserTokenInfo.delete_flag == 'N'
        ).order_by(UserTokenInfo.create_time.desc()).all()

        return [
            {
                "token_id": token.token_id,
                "access_key": token.access_key,
                "user_id": token.user_id,
                "create_time": token.create_time.isoformat() if token.create_time else None
            }
            for token in tokens
        ]


def get_token_by_id(token_id: int) -> UserTokenInfo:
    """Get a token by its ID.

    Args:
        token_id: The token ID to query.

    Returns:
        UserTokenInfo object if found and active, None otherwise.
    """
    with get_db_session() as session:
        return session.query(UserTokenInfo).filter(
            UserTokenInfo.token_id == token_id,
            UserTokenInfo.delete_flag == 'N'
        ).first()


def get_token_by_access_key(access_key: str) -> Optional[Dict[str, Any]]:
    """Get a token by its access key.

    Args:
        access_key: The access key to query.

    Returns:
        Token information dict if found and active, None otherwise.
    """
    with get_db_session() as session:
        token = session.query(UserTokenInfo).filter(
            UserTokenInfo.access_key == access_key,
            UserTokenInfo.delete_flag == 'N'
        ).first()

        if token:
            return {
                "token_id": token.token_id,
                "access_key": token.access_key,
                "user_id": token.user_id,
                "delete_flag": token.delete_flag
            }
        return None


def delete_token(token_id: int, user_id: str) -> bool:
    """Soft delete a token by setting delete_flag to 'Y'.

    Args:
        token_id: The token ID to delete.
        user_id: The user ID who owns this token (for authorization).

    Returns:
        True if the token was deleted, False if not found or not owned by user.
    """
    with get_db_session() as session:
        token = session.query(UserTokenInfo).filter(
            UserTokenInfo.token_id == token_id,
            UserTokenInfo.user_id == user_id,
            UserTokenInfo.delete_flag == 'N'
        ).first()

        if not token:
            return False

        token.delete_flag = 'Y'
        token.updated_by = user_id
        token.update_time = func.now()
        _soft_delete_usage_logs(session, [token.token_id], user_id)
        return True


def _soft_delete_usage_logs(session, token_ids: List[int], updated_by: str) -> int:
    """Soft-delete active usage logs associated with the supplied API keys."""
    if not token_ids:
        return 0

    usage_logs = session.query(UserTokenUsageLog).filter(
        UserTokenUsageLog.token_id.in_(token_ids),
        UserTokenUsageLog.delete_flag == "N",
    ).all()
    for usage_log in usage_logs:
        usage_log.delete_flag = "Y"
        usage_log.updated_by = updated_by
        usage_log.update_time = func.now()
    return len(usage_logs)


def soft_delete_tokens_by_user(user_id: str, updated_by: str, db_session=None) -> int:
    """Soft-delete a user's active API keys and their usage logs atomically."""
    session_context = get_db_session() if db_session is None else get_db_session(db_session)
    with session_context as session:
        tokens = session.query(UserTokenInfo).filter(
            UserTokenInfo.user_id == user_id,
            UserTokenInfo.delete_flag == "N",
        ).all()
        token_ids = [token.token_id for token in tokens]
        for token in tokens:
            token.delete_flag = "Y"
            token.updated_by = updated_by
            token.update_time = func.now()
        _soft_delete_usage_logs(session, token_ids, updated_by)
        return len(tokens)


def list_active_tokens_by_tenant(
    tenant_id: str,
    page: int = 1,
    page_size: int = 20,
    sort_order: str = "desc",
) -> Dict[str, Any]:
    """List active tenant API keys with owner, creator, and usage aggregates."""
    owner = aliased(UserTenant)
    creator = aliased(UserTenant)

    with get_db_session() as session:
        usage = session.query(
            UserTokenUsageLog.token_id.label("token_id"),
            func.max(UserTokenUsageLog.create_time).label("last_used_time"),
            func.count(UserTokenUsageLog.token_usage_id).label("total_usage_count"),
        ).filter(
            UserTokenUsageLog.delete_flag == "N",
        ).group_by(UserTokenUsageLog.token_id).subquery()

        base_query = session.query(
            UserTokenInfo.token_id,
            UserTokenInfo.access_key,
            UserTokenInfo.user_id,
            UserTokenInfo.created_by,
            UserTokenInfo.create_time,
            owner.user_email.label("owner_email"),
            owner.user_role.label("owner_role"),
            creator.user_email.label("creator_email"),
            usage.c.last_used_time,
            func.coalesce(usage.c.total_usage_count, 0).label("total_usage_count"),
        ).join(
            owner,
            (owner.user_id == UserTokenInfo.user_id)
            & (owner.tenant_id == tenant_id)
            & (owner.delete_flag == "N"),
        ).outerjoin(
            creator,
            (creator.user_id == UserTokenInfo.created_by)
            & (creator.delete_flag == "N"),
        ).outerjoin(
            usage,
            usage.c.token_id == UserTokenInfo.token_id,
        ).filter(
            UserTokenInfo.delete_flag == "N",
        )

        total = base_query.count()
        order_column = UserTokenInfo.create_time.desc() if sort_order == "desc" else UserTokenInfo.create_time.asc()
        rows = base_query.order_by(order_column).offset((page - 1) * page_size).limit(page_size).all()

        return {
            "items": [
                {
                    "token_id": row.token_id,
                    "access_key": row.access_key,
                    "user_id": row.user_id,
                    "created_by": row.created_by,
                    "creator_email": row.creator_email,
                    "owner_email": row.owner_email,
                    "owner_role": row.owner_role,
                    "create_time": row.create_time.isoformat() if row.create_time else None,
                    "last_used_time": row.last_used_time.isoformat() if row.last_used_time else None,
                    "total_usage_count": int(row.total_usage_count or 0),
                }
                for row in rows
            ],
            "total": total,
        }


def log_token_usage(
    token_id: int,
    call_function_name: str,
    related_id: Optional[int],
    created_by: str,
    metadata: Optional[Dict[str, Any]] = None
) -> int:
    """Log token usage to the database.

    Args:
        token_id: The token ID used.
        call_function_name: The API function name being called.
        related_id: Related resource ID (e.g., conversation_id).
        created_by: User ID who initiated the call.
        metadata: Optional additional metadata for this usage log entry.

    Returns:
        The created token_usage_id.
    """
    with get_db_session() as session:
        usage_log = UserTokenUsageLog(
            token_id=token_id,
            call_function_name=call_function_name,
            related_id=related_id,
            created_by=created_by,
            meta_data=metadata
        )
        session.add(usage_log)
        session.flush()
        return usage_log.token_usage_id


def get_latest_usage_metadata(token_id: int, related_id: int, call_function_name: str) -> Optional[Dict[str, Any]]:
    """Get the latest metadata for a given token, related_id and function name.

    Args:
        token_id: The token ID used.
        related_id: Related resource ID (e.g., conversation_id).
        call_function_name: The API function name.

    Returns:
        The metadata dict if found, None otherwise.
    """
    with get_db_session() as session:
        usage_log = session.query(UserTokenUsageLog).filter(
            UserTokenUsageLog.token_id == token_id,
            UserTokenUsageLog.related_id == related_id,
            UserTokenUsageLog.call_function_name == call_function_name
        ).order_by(UserTokenUsageLog.create_time.desc()).first()

        if usage_log and usage_log.meta_data:
            return usage_log.meta_data
        return None
