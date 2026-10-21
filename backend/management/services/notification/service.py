# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
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





from management.services.repository.review_notifications import (
    create_repository_review_notification,
    create_repository_pending_review_notification,
)
