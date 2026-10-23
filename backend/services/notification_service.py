"""Notification business logic orchestration."""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from consts.agent_repository import STATUS_REJECTED, STATUS_SHARED
from consts.exceptions import NotFoundException
from consts.notification import (
    EVENT_TYPE_REPOSITORY_REVIEW_APPROVED,
    EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
    EVENT_TYPE_REPOSITORY_REVIEW_REJECTED,
    SCOPE_TENANT_ADMIN,
    SCOPE_USER,
)
from database.notification_db import (
    create_notification,
    deactivate_notifications as deactivate_notifications_db,
    list_notifications_by_user,
    mark_notifications_read as mark_notifications_read_db,
)

logger = logging.getLogger(__name__)

_REVIEW_STATUS_TO_EVENT_TYPE = {
    STATUS_SHARED: EVENT_TYPE_REPOSITORY_REVIEW_APPROVED,
    STATUS_REJECTED: EVENT_TYPE_REPOSITORY_REVIEW_REJECTED,
}


def _serialize_create_time(value: Any) -> Any:
    """Convert datetime to ISO string for JSON serialization."""
    if not isinstance(value, datetime):
        return value
    iso = value.isoformat()
    return iso if value.tzinfo else iso + "Z"


def list_notifications(
    user_id: str,
    *,
    only_unread: bool = False,
    page: int = 1,
    page_size: int = 10,
) -> Dict[str, Any]:
    """List notifications for a user, newest first."""
    result = list_notifications_by_user(
        user_id,
        only_unread=only_unread,
        page=page,
        page_size=page_size,
    )
    for item in result["items"]:
        item["create_time"] = _serialize_create_time(item.get("create_time"))
    return result


def mark_notifications_read(
    user_id: str,
    *,
    mark_all: bool = False,
    receiver_id: Optional[int] = None,
) -> Dict[str, int]:
    """Mark one or all unread notifications as read for the user."""
    if not mark_all and receiver_id is None:
        raise ValueError("receiver_id is required when mark_all is false")

    updated_count = mark_notifications_read_db(
        user_id,
        mark_all=mark_all,
        receiver_id=receiver_id,
    )
    if not mark_all and updated_count == 0:
        raise NotFoundException(f"Notification receiver {receiver_id} not found")
    return {"updated_count": updated_count}


def deactivate_notifications(
    *,
    event_type: str,
    resource_type: str,
    unique_id: int,
    updated_by: Optional[str] = None,
) -> Dict[str, int]:
    """Deactivate active notifications matching event_type + resource_type + unique_id."""
    updated_count = deactivate_notifications_db(
        event_type=event_type,
        resource_type=resource_type,
        unique_id=unique_id,
        updated_by=updated_by,
    )
    return {"updated_count": updated_count}


def create_repository_review_notification(
    *,
    resource_type: str,
    review_status: str,
    receiver_user_id: str,
    details: Optional[Dict[str, Any]] = None,
    tenant_id: Optional[str] = None,
    unique_id: Optional[int] = None,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a USER-scoped notification for a repository review result.

    Reusable by agent / skill / mcp repository flows.

    Args:
        resource_type: One of VALID_RESOURCE_TYPES (e.g. agent_repository).
        review_status: Listing status after review (`shared` or `rejected`).
        receiver_user_id: Publisher user who should receive the notification.
        details: i18n interpolation details (e.g. listing name, reviewer reason).
        tenant_id: Optional tenant stored on the receiver row.
        unique_id: Related resource primary key (e.g. agent_repository_id).
        created_by: Actor who triggered the review action.

    Returns:
        Dict with notification_id and receiver_count from the DB layer.
    """
    event_type = _REVIEW_STATUS_TO_EVENT_TYPE.get(review_status)
    if event_type is None:
        logger.warning(
            "Skipping review notification: invalid review_status '%s'; "
            "expected '%s' or '%s'",
            review_status,
            STATUS_SHARED,
            STATUS_REJECTED,
        )
        return {"notification_id": None, "receiver_count": 0}

    return create_notification(
        event_type=event_type,
        resource_type=resource_type,
        scope=SCOPE_USER,
        details=details,
        tenant_id=tenant_id,
        receiver_user_id=receiver_user_id,
        unique_id=unique_id,
        created_by=created_by,
    )


def create_repository_pending_review_notification(
    *,
    resource_type: str,
    tenant_id: str,
    unique_id: int,
    details: Optional[Dict[str, Any]] = None,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a TENANT_ADMIN-scoped notification for a pending repository review.

    Notifies all ADMIN users in the publisher tenant that a listing awaits review.

    Args:
        resource_type: One of VALID_RESOURCE_TYPES (e.g. agent_repository).
        tenant_id: Publisher tenant whose admins should receive the notification.
        unique_id: Related resource primary key (e.g. agent_repository_id).
        details: i18n interpolation details (e.g. listing name).
        created_by: Actor who submitted the listing for review.

    Returns:
        Dict with notification_id and receiver_count from the DB layer.
    """
    return create_notification(
        event_type=EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
        resource_type=resource_type,
        scope=SCOPE_TENANT_ADMIN,
        details=details,
        tenant_id=tenant_id,
        unique_id=unique_id,
        created_by=created_by,
    )
