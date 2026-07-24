"""Unit tests for services.notification_service."""
from datetime import datetime, timezone

import pytest

from consts.agent_repository import STATUS_REJECTED, STATUS_SHARED
from consts.exceptions import NotFoundException
from consts.notification import (
    EVENT_TYPE_REPOSITORY_REVIEW_APPROVED,
    EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
    EVENT_TYPE_REPOSITORY_REVIEW_REJECTED,
    RESOURCE_TYPE_AGENT_REPOSITORY,
    SCOPE_TENANT_ADMIN,
    SCOPE_USER,
)
from services import notification_service as service


def test_list_notifications_serializes_naive_and_aware_datetimes(mocker):
    naive = datetime(2026, 1, 2, 3, 4, 5)
    aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    mocker.patch(
        "services.notification_service.list_notifications_by_user",
        return_value={
            "items": [
                {"create_time": naive, "receiver_id": 1},
                {"create_time": aware, "receiver_id": 2},
                {"create_time": "already-string", "receiver_id": 3},
            ],
            "pagination": {"page": 1, "page_size": 10, "total": 3, "total_pages": 1},
        },
    )

    result = service.list_notifications("user-1", only_unread=True, page=1, page_size=10)

    assert result["items"][0]["create_time"] == "2026-01-02T03:04:05Z"
    assert result["items"][1]["create_time"] == aware.isoformat()
    assert result["items"][2]["create_time"] == "already-string"


def test_mark_notifications_read_requires_receiver_id_when_not_mark_all():
    with pytest.raises(ValueError, match="receiver_id is required"):
        service.mark_notifications_read("user-1", mark_all=False, receiver_id=None)


def test_mark_notifications_read_raises_not_found_when_zero_updated(mocker):
    mocker.patch(
        "services.notification_service.mark_notifications_read_db",
        return_value=0,
    )

    with pytest.raises(NotFoundException, match="Notification receiver 99 not found"):
        service.mark_notifications_read("user-1", receiver_id=99)


def test_mark_notifications_read_success(mocker):
    mock_db = mocker.patch(
        "services.notification_service.mark_notifications_read_db",
        return_value=2,
    )

    result = service.mark_notifications_read("user-1", mark_all=True)

    assert result == {"updated_count": 2}
    mock_db.assert_called_once_with("user-1", mark_all=True, receiver_id=None)


def test_deactivate_notifications(mocker):
    mock_db = mocker.patch(
        "services.notification_service.deactivate_notifications_db",
        return_value=3,
    )

    result = service.deactivate_notifications(
        event_type=EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
        resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
        unique_id=42,
        updated_by="admin-1",
    )

    assert result == {"updated_count": 3}
    mock_db.assert_called_once_with(
        event_type=EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
        resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
        unique_id=42,
        updated_by="admin-1",
    )


@pytest.mark.parametrize(
    "review_status,expected_event",
    [
        (STATUS_SHARED, EVENT_TYPE_REPOSITORY_REVIEW_APPROVED),
        (STATUS_REJECTED, EVENT_TYPE_REPOSITORY_REVIEW_REJECTED),
    ],
)
def test_create_repository_review_notification_maps_status(mocker, review_status, expected_event):
    mock_create = mocker.patch(
        "services.notification_service.create_notification",
        return_value={"notification_id": 1, "receiver_count": 1},
    )

    result = service.create_repository_review_notification(
        resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
        review_status=review_status,
        receiver_user_id="publisher-1",
        details={"name": "Agent"},
        tenant_id="tenant-a",
        unique_id=42,
        created_by="admin-1",
    )

    assert result == {"notification_id": 1, "receiver_count": 1}
    mock_create.assert_called_once_with(
        event_type=expected_event,
        resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
        scope=SCOPE_USER,
        details={"name": "Agent"},
        tenant_id="tenant-a",
        receiver_user_id="publisher-1",
        unique_id=42,
        created_by="admin-1",
    )


def test_create_repository_review_notification_skips_invalid_status(mocker):
    mock_create = mocker.patch("services.notification_service.create_notification")

    result = service.create_repository_review_notification(
        resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
        review_status="pending_review",
        receiver_user_id="publisher-1",
    )

    assert result == {"notification_id": None, "receiver_count": 0}
    mock_create.assert_not_called()


def test_create_repository_pending_review_notification(mocker):
    mock_create = mocker.patch(
        "services.notification_service.create_notification",
        return_value={"notification_id": 9, "receiver_count": 2},
    )

    result = service.create_repository_pending_review_notification(
        resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
        tenant_id="tenant-a",
        unique_id=42,
        details={"name": "Agent"},
        created_by="user-1",
    )

    assert result == {"notification_id": 9, "receiver_count": 2}
    mock_create.assert_called_once_with(
        event_type=EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
        resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
        scope=SCOPE_TENANT_ADMIN,
        details={"name": "Agent"},
        tenant_id="tenant-a",
        unique_id=42,
        created_by="user-1",
    )
