"""Unit tests for database.notification_db."""
import sys
import types
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock

import pytest

client_mod = types.ModuleType("database.client")
client_mod.get_db_session = MagicMock(name="get_db_session")
client_mod.as_dict = MagicMock(name="as_dict")
client_mod.filter_property = MagicMock(name="filter_property")
sys.modules["database.client"] = client_mod
sys.modules["backend.database.client"] = client_mod

db_models_mod = types.ModuleType("database.db_models")


class Notification:
    event_type = MagicMock(name="Notification.event_type")
    resource_type = MagicMock(name="Notification.resource_type")
    unique_id = MagicMock(name="Notification.unique_id")
    is_active = MagicMock(name="Notification.is_active")
    delete_flag = MagicMock(name="Notification.delete_flag")
    notification_id = MagicMock(name="Notification.notification_id")
    create_time = MagicMock(name="Notification.create_time")

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.notification_id = kwargs.get("notification_id")


class NotificationReceiver:
    notification_id = MagicMock(name="NotificationReceiver.notification_id")
    receiver_user_id = MagicMock(name="NotificationReceiver.receiver_user_id")
    is_read = MagicMock(name="NotificationReceiver.is_read")
    delete_flag = MagicMock(name="NotificationReceiver.delete_flag")
    receiver_id = MagicMock(name="NotificationReceiver.receiver_id")
    create_time = MagicMock(name="NotificationReceiver.create_time")

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class UserTenant:
    user_id = MagicMock(name="UserTenant.user_id")
    tenant_id = MagicMock(name="UserTenant.tenant_id")
    delete_flag = MagicMock(name="UserTenant.delete_flag")
    user_role = MagicMock(name="UserTenant.user_role")


db_models_mod.Notification = Notification
db_models_mod.NotificationReceiver = NotificationReceiver
db_models_mod.UserTenant = UserTenant
sys.modules["database.db_models"] = db_models_mod
sys.modules["backend.database.db_models"] = db_models_mod

from backend.database import notification_db as db
from consts.notification import (
    EVENT_TYPE_REPOSITORY_REVIEW_APPROVED,
    EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
    RESOURCE_TYPE_AGENT_REPOSITORY,
    SCOPE_SU,
    SCOPE_TENANT,
    SCOPE_TENANT_ADMIN,
    SCOPE_TENANT_USER,
    SCOPE_USER,
)


@pytest.fixture
def mock_session(monkeypatch):
    session = MagicMock(name="session")

    @contextmanager
    def session_ctx():
        yield session

    monkeypatch.setattr(db, "get_db_session", session_ctx)
    return session


def test_create_notification_rejects_invalid_event_type():
    with pytest.raises(ValueError, match="Invalid event_type"):
        db.create_notification(
            event_type="invalid_event",
            resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
            scope=SCOPE_USER,
            receiver_user_id="user-1",
        )


def test_create_notification_rejects_invalid_resource_type():
    with pytest.raises(ValueError, match="Invalid resource_type"):
        db.create_notification(
            event_type=EVENT_TYPE_REPOSITORY_REVIEW_APPROVED,
            resource_type="invalid_resource",
            scope=SCOPE_USER,
            receiver_user_id="user-1",
        )


def test_create_notification_rejects_invalid_scope():
    with pytest.raises(ValueError, match="Invalid notification scope"):
        db.create_notification(
            event_type=EVENT_TYPE_REPOSITORY_REVIEW_APPROVED,
            resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
            scope="INVALID",
            receiver_user_id="user-1",
        )


def test_create_notification_requires_tenant_for_tenant_scopes():
    with pytest.raises(ValueError, match="tenant_id is required"):
        db.create_notification(
            event_type=EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
            resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
            scope=SCOPE_TENANT_ADMIN,
        )


def test_create_notification_requires_receiver_for_user_scope():
    with pytest.raises(ValueError, match="receiver_user_id is required"):
        db.create_notification(
            event_type=EVENT_TYPE_REPOSITORY_REVIEW_APPROVED,
            resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
            scope=SCOPE_USER,
            tenant_id="tenant-a",
        )


def test_create_notification_user_scope_success(mock_session):
    def _flush_side_effect():
        added = mock_session.add.call_args[0][0]
        added.notification_id = 101

    mock_session.flush.side_effect = _flush_side_effect

    result = db.create_notification(
        event_type=EVENT_TYPE_REPOSITORY_REVIEW_APPROVED,
        resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
        scope=SCOPE_USER,
        details={"name": "Agent One"},
        tenant_id="tenant-a",
        receiver_user_id="user-1",
        unique_id=42,
        created_by="admin-1",
    )

    assert result == {"notification_id": 101, "receiver_count": 1}
    mock_session.add.assert_called_once()
    mock_session.flush.assert_called_once()
    mock_session.add_all.assert_called_once()
    receivers = mock_session.add_all.call_args[0][0]
    assert len(receivers) == 1
    assert receivers[0].receiver_user_id == "user-1"
    assert receivers[0].tenant_id == "tenant-a"
    assert receivers[0].notification_id == 101
    assert receivers[0].is_read is False


@pytest.mark.parametrize(
    "scope,query_rows,expected_count,expected_users",
    [
        (SCOPE_SU, [("su-1", "t1"), ("su-2", "t2"), ("su-1", "t3")], 2, {"su-1", "su-2"}),
        (SCOPE_TENANT, [("u1", "tenant-a"), ("u2", "tenant-a")], 2, {"u1", "u2"}),
        (SCOPE_TENANT_ADMIN, [("admin-1", "tenant-a")], 1, {"admin-1"}),
        (SCOPE_TENANT_USER, [("user-1", "tenant-a"), ("user-2", "tenant-a")], 2, {"user-1", "user-2"}),
    ],
)
def test_create_notification_resolves_scoped_receivers(
    mock_session, scope, query_rows, expected_count, expected_users
):
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = query_rows
    mock_session.query.return_value = query_chain

    def _flush_side_effect():
        added = mock_session.add.call_args[0][0]
        added.notification_id = 200

    mock_session.flush.side_effect = _flush_side_effect

    result = db.create_notification(
        event_type=EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
        resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
        scope=scope,
        tenant_id="tenant-a",
        unique_id=7,
        created_by="actor",
    )

    assert result["notification_id"] == 200
    assert result["receiver_count"] == expected_count
    receivers = mock_session.add_all.call_args[0][0]
    assert {r.receiver_user_id for r in receivers} == expected_users


def test_deactivate_notifications(mock_session):
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.update.return_value = 3
    mock_session.query.return_value = query_chain

    updated = db.deactivate_notifications(
        event_type=EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
        resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
        unique_id=42,
        updated_by="admin-1",
    )

    assert updated == 3
    query_chain.update.assert_called_once_with(
        {"is_active": False, "updated_by": "admin-1"},
        synchronize_session=False,
    )


def test_list_notifications_by_user(mock_session):
    recv = MagicMock()
    recv.receiver_id = 11
    recv.notification_id = 101
    recv.is_read = False
    recv.create_time = datetime(2026, 1, 2, 3, 4, 5)

    notif = MagicMock()
    notif.event_type = EVENT_TYPE_REPOSITORY_REVIEW_APPROVED
    notif.resource_type = RESOURCE_TYPE_AGENT_REPOSITORY
    notif.details = {"name": "Agent"}
    notif.scope = SCOPE_USER

    base = MagicMock()
    base.filter.return_value = base
    base.count.return_value = 1
    base.order_by.return_value = base
    base.offset.return_value = base
    base.limit.return_value = base
    base.all.return_value = [(recv, notif)]

    join_chain = MagicMock()
    join_chain.filter.return_value = base
    mock_session.query.return_value = join_chain
    join_chain.join.return_value = join_chain

    result = db.list_notifications_by_user("user-1", page=2, page_size=5)

    assert result["pagination"] == {
        "page": 2,
        "page_size": 5,
        "total": 1,
        "total_pages": 1,
    }
    assert result["items"] == [
        {
            "receiver_id": 11,
            "notification_id": 101,
            "event_type": EVENT_TYPE_REPOSITORY_REVIEW_APPROVED,
            "resource_type": RESOURCE_TYPE_AGENT_REPOSITORY,
            "details": {"name": "Agent"},
            "scope": SCOPE_USER,
            "is_read": False,
            "create_time": datetime(2026, 1, 2, 3, 4, 5),
        }
    ]
    base.offset.assert_called_once_with(5)
    base.limit.assert_called_once_with(5)


def test_list_notifications_by_user_only_unread(mock_session):
    base = MagicMock()
    base.filter.return_value = base
    base.count.return_value = 0
    base.order_by.return_value = base
    base.offset.return_value = base
    base.limit.return_value = base
    base.all.return_value = []

    join_chain = MagicMock()
    join_chain.filter.return_value = base
    join_chain.join.return_value = join_chain
    mock_session.query.return_value = join_chain

    result = db.list_notifications_by_user("user-1", only_unread=True)

    assert result["items"] == []
    assert result["pagination"]["total_pages"] == 0
    assert base.filter.call_count >= 1


def test_count_unread_by_user(mock_session):
    join_chain = MagicMock()
    join_chain.join.return_value = join_chain
    join_chain.filter.return_value = join_chain
    join_chain.count.return_value = 4
    mock_session.query.return_value = join_chain

    assert db.count_unread_by_user("user-1") == 4


def test_mark_notifications_read_mark_all(mock_session):
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.update.return_value = 5
    mock_session.query.return_value = query_chain

    updated = db.mark_notifications_read("user-1", mark_all=True)

    assert updated == 5
    query_chain.update.assert_called_once_with(
        {"is_read": True, "updated_by": "user-1"},
        synchronize_session=False,
    )


def test_mark_notifications_read_single(mock_session):
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.update.return_value = 1
    mock_session.query.return_value = query_chain

    updated = db.mark_notifications_read("user-1", receiver_id=99)

    assert updated == 1
    assert query_chain.filter.call_count >= 2
