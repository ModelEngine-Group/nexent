"""
Database operations for user API token (API Key) management.
"""
import secrets
from typing import Any, Dict, List, Optional

from database.client import get_db_session
from database.db_models import UserTokenInfo, UserTokenUsageLog


def generate_access_key() -> str:
    """Generate a random access key with format nexent-xxxxx..."""
    random_part = secrets.token_hex(12)  # 24 hex characters for more entropy
    return f"nexent-{random_part}"


def create_token(access_key: str, user_id: str) -> Dict[str, Any]:
    """Create a new token record in the database.

    Args:
        access_key: The access key (API Key).
        user_id: The user ID who owns this token.

    Returns:
        Dictionary containing the created token information.
    """
    with get_db_session() as session:
        token = UserTokenInfo(
            access_key=access_key,
            user_id=user_id,
            created_by=user_id,
            updated_by=user_id,
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
        return True


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
