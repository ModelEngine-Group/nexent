"""
Database operations for in-app notifications.

Notifications use a fan-out model: one row in notification_t holds the message,
and one row per resolved receiver is written to notification_receiver_t.
"""
import logging
from typing import Any, Dict, List, Optional

from consts.notification import (
    VALID_EVENT_TYPES,
    VALID_RESOURCE_TYPES,
    VALID_NOTIFICATION_SCOPES,
    TENANT_REQUIRED_SCOPES,
    SCOPE_SU,
    SCOPE_TENANT,
    SCOPE_TENANT_ADMIN,
    SCOPE_TENANT_USER,
    SCOPE_USER,
    SU_ROLES,
    TENANT_ADMIN_ROLES,
    TENANT_USER_ROLES,
)
from database.client import get_db_session
from database.db_models import Notification, NotificationReceiver, UserTenant

logger = logging.getLogger(__name__)


def _resolve_receivers(
    session,
    scope: str,
    tenant_id: Optional[str],
    receiver_user_id: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Resolve (user_id, tenant_id) receivers for a scope. Deduplicated by user_id."""
    if scope == SCOPE_USER:
        return [{"user_id": receiver_user_id, "tenant_id": tenant_id}]

    query = session.query(UserTenant.user_id, UserTenant.tenant_id).filter(
        UserTenant.delete_flag == "N"
    )
    if scope == SCOPE_SU:
        query = query.filter(UserTenant.user_role.in_(SU_ROLES))
    elif scope == SCOPE_TENANT:
        query = query.filter(UserTenant.tenant_id == tenant_id)
    elif scope == SCOPE_TENANT_ADMIN:
        query = query.filter(
            UserTenant.tenant_id == tenant_id,
            UserTenant.user_role.in_(TENANT_ADMIN_ROLES),
        )
    elif scope == SCOPE_TENANT_USER:
        query = query.filter(
            UserTenant.tenant_id == tenant_id,
            UserTenant.user_role.in_(TENANT_USER_ROLES),
        )

    seen: set = set()
    receivers: List[Dict[str, str]] = []
    for user_id, uid_tenant in query.all():
        if user_id in seen:
            continue
        seen.add(user_id)
        receivers.append({"user_id": user_id, "tenant_id": uid_tenant})
    return receivers


def create_notification(*, event_type: str, resource_type: str, scope: str,
                        details: Optional[dict] = None,
                        tenant_id: Optional[str] = None,
                        receiver_user_id: Optional[str] = None,
                        unique_id: Optional[int] = None,
                        created_by: Optional[str] = None) -> Dict[str, Any]:
    """Create a notification and fan-out receiver rows based on scope.

    Args:
        event_type: Event type identifier (e.g. repository_review_approved).
        resource_type: Resource type identifier (e.g. agent_repository).
        scope: Audience scope (SU / TENANT / TENANT_ADMIN / TENANT_USER / USER).
        details: i18n interpolation details for the event template.
        tenant_id: Target tenant; required for tenant-scoped notifications.
        receiver_user_id: Target user; required for the USER scope.
        unique_id: Related resource primary key (e.g. agent_repository_id).
        created_by: Actor who created the notification.

    Returns:
        Dict with the new notification_id and the number of receiver rows.
    """
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Invalid event_type: {event_type}")
    if resource_type not in VALID_RESOURCE_TYPES:
        raise ValueError(f"Invalid resource_type: {resource_type}")
    if scope not in VALID_NOTIFICATION_SCOPES:
        raise ValueError(f"Invalid notification scope: {scope}")
    if scope in TENANT_REQUIRED_SCOPES and not tenant_id:
        raise ValueError(f"tenant_id is required for scope {scope}")
    if scope == SCOPE_USER and not receiver_user_id:
        raise ValueError(f"receiver_user_id is required for scope {scope}")

    with get_db_session() as session:
        notification = Notification(
            event_type=event_type,
            resource_type=resource_type,
            unique_id=unique_id,
            details=details,
            scope=scope,
            tenant_id=tenant_id,
            is_active=True,
            created_by=created_by,
            updated_by=created_by,
            delete_flag="N",
        )
        session.add(notification)
        session.flush()  # obtain notification_id
        notification_id = int(notification.notification_id)

        receivers = _resolve_receivers(session, scope, tenant_id, receiver_user_id)
        session.add_all([
            NotificationReceiver(
                notification_id=notification_id,
                receiver_user_id=receiver["user_id"],
                tenant_id=receiver["tenant_id"],
                is_read=False,
                created_by=created_by,
                updated_by=created_by,
                delete_flag="N",
            )
            for receiver in receivers
        ])
        return {"notification_id": notification_id, "receiver_count": len(receivers)}


def deactivate_notifications(
    *,
    event_type: str,
    resource_type: str,
    unique_id: int,
    updated_by: Optional[str] = None,
) -> int:
    """Deactivate active notifications matching event_type + resource_type + unique_id.

    Args:
        event_type: Event type identifier.
        resource_type: Resource type identifier.
        unique_id: Related resource primary key.
        updated_by: Actor who deactivated the notifications.

    Returns:
        Number of notification rows updated.
    """
    with get_db_session() as session:
        return session.query(Notification).filter(
            Notification.event_type == event_type,
            Notification.resource_type == resource_type,
            Notification.unique_id == unique_id,
            Notification.is_active.is_(True),
            Notification.delete_flag != "Y",
        ).update(
            {"is_active": False, "updated_by": updated_by},
            synchronize_session=False,
        )


def list_notifications_by_user(
    user_id: str,
    *,
    only_unread: bool = False,
    page: int = 1,
    page_size: int = 10,
) -> Dict[str, Any]:
    """List a user's notifications (joined with message body), newest first."""
    with get_db_session() as session:
        base = session.query(NotificationReceiver, Notification).join(
            Notification,
            Notification.notification_id == NotificationReceiver.notification_id,
        ).filter(
            NotificationReceiver.receiver_user_id == user_id,
            NotificationReceiver.delete_flag != "Y",
            Notification.delete_flag != "Y",
            Notification.is_active.is_(True),
        )
        if only_unread:
            base = base.filter(NotificationReceiver.is_read.is_(False))

        total = base.count()
        rows = (
            base.order_by(Notification.create_time.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "items": [
                {
                    "receiver_id": recv.receiver_id,
                    "notification_id": recv.notification_id,
                    "event_type": notif.event_type,
                    "resource_type": notif.resource_type,
                    "details": notif.details,
                    "scope": notif.scope,
                    "is_read": recv.is_read,
                    "create_time": recv.create_time,
                }
                for recv, notif in rows
            ],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size if total else 0,
            },
        }


def count_unread_by_user(user_id: str) -> int:
    """Count unread active notifications for a user."""
    with get_db_session() as session:
        return session.query(NotificationReceiver).join(
            Notification,
            Notification.notification_id == NotificationReceiver.notification_id,
        ).filter(
            NotificationReceiver.receiver_user_id == user_id,
            NotificationReceiver.is_read.is_(False),
            NotificationReceiver.delete_flag != "Y",
            Notification.is_active.is_(True),
            Notification.delete_flag != "Y",
        ).count()


def mark_notifications_read(
    user_id: str,
    *,
    mark_all: bool = False,
    receiver_id: Optional[int] = None,
) -> int:
    """Mark notification receiver rows as read for the given user.

    Always scopes updates to receiver_user_id == user_id so callers cannot
    mark another user's notifications.

    Args:
        user_id: Authenticated receiver user ID.
        mark_all: If True, mark all unread rows for the user.
        receiver_id: Specific receiver row to mark when mark_all is False.

    Returns:
        Number of rows updated.
    """
    with get_db_session() as session:
        query = session.query(NotificationReceiver).filter(
            NotificationReceiver.receiver_user_id == user_id,
            NotificationReceiver.is_read.is_(False),
            NotificationReceiver.delete_flag != "Y",
        )
        if not mark_all:
            query = query.filter(NotificationReceiver.receiver_id == receiver_id)
        return query.update(
            {"is_read": True, "updated_by": user_id},
            synchronize_session=False,
        )
