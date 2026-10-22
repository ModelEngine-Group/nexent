# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from typing import Any
from typing import Dict
from contracts.constants.notification import EVENT_TYPE_REPOSITORY_REVIEW_PENDING
from typing import Optional
from contracts.constants.notification import SCOPE_TENANT_ADMIN
from contracts.constants.notification import SCOPE_USER
from contracts.constants.notification import EVENT_TYPE_REPOSITORY_REVIEW_APPROVED, EVENT_TYPE_REPOSITORY_REVIEW_REJECTED
from contracts.constants.agent import STATUS_REJECTED
from contracts.constants.agent import STATUS_SHARED
from management.db.notification.repository import create_notification

import logging
logger = logging.getLogger('management.services.notification.service')

_REVIEW_STATUS_TO_EVENT_TYPE = {
    STATUS_SHARED: EVENT_TYPE_REPOSITORY_REVIEW_APPROVED,
    STATUS_REJECTED: EVENT_TYPE_REPOSITORY_REVIEW_REJECTED,
}

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
