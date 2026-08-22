"""Unit tests for apps.notification_app."""
import os
import sys
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.insert(0, backend_dir)

sys.modules.setdefault("services.notification_service", MagicMock())
sys.modules.setdefault("utils.auth_utils", MagicMock())

from apps.notification_app import router
from consts.exceptions import NotFoundException, UnauthorizedError

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestListNotifications:
    def test_list_notifications_success(self, mocker):
        mock_result = {
            "items": [{"receiver_id": 1, "event_type": "repository_review_approved"}],
            "pagination": {"page": 1, "page_size": 10, "total": 1, "total_pages": 1},
        }
        mock_user = mocker.patch("apps.notification_app.get_current_user_id")
        mock_list = mocker.patch("apps.notification_app.list_notifications")
        mock_user.return_value = ("user-1", "tenant-a")
        mock_list.return_value = mock_result

        response = client.get("/notifications?only_unread=true&page=1&page_size=10")

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"message": "OK", "data": mock_result}
        mock_list.assert_called_once_with(
            "user-1",
            only_unread=True,
            page=1,
            page_size=10,
        )

    def test_list_notifications_unauthorized(self, mocker):
        mock_user = mocker.patch("apps.notification_app.get_current_user_id")
        mock_user.side_effect = UnauthorizedError("bad token")

        response = client.get("/notifications")

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert "bad token" in response.json()["detail"]


class TestMarkNotificationsRead:
    def test_mark_read_success(self, mocker):
        mock_user = mocker.patch("apps.notification_app.get_current_user_id")
        mock_mark = mocker.patch("apps.notification_app.mark_notifications_read")
        mock_user.return_value = ("user-1", "tenant-a")
        mock_mark.return_value = {"updated_count": 1}

        response = client.post(
            "/notifications/read",
            json={"mark_all": False, "receiver_id": 11},
        )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"message": "OK", "data": {"updated_count": 1}}
        mock_mark.assert_called_once_with(
            "user-1",
            mark_all=False,
            receiver_id=11,
        )

    def test_mark_read_unauthorized(self, mocker):
        mock_user = mocker.patch("apps.notification_app.get_current_user_id")
        mock_user.side_effect = UnauthorizedError("bad token")

        response = client.post(
            "/notifications/read",
            json={"mark_all": True},
        )

        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_mark_read_not_found(self, mocker):
        mock_user = mocker.patch("apps.notification_app.get_current_user_id")
        mock_mark = mocker.patch("apps.notification_app.mark_notifications_read")
        mock_user.return_value = ("user-1", "tenant-a")
        mock_mark.side_effect = NotFoundException("Notification receiver 99 not found")

        response = client.post(
            "/notifications/read",
            json={"receiver_id": 99},
        )

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert "99" in response.json()["detail"]

    def test_mark_read_bad_request(self, mocker):
        mock_user = mocker.patch("apps.notification_app.get_current_user_id")
        mock_mark = mocker.patch("apps.notification_app.mark_notifications_read")
        mock_user.return_value = ("user-1", "tenant-a")
        mock_mark.side_effect = ValueError("receiver_id is required when mark_all is false")

        response = client.post(
            "/notifications/read",
            json={"mark_all": False},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
