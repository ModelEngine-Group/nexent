"""Unit tests for backend.apps.agent_repository_app module."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.insert(0, backend_dir)

sys.modules.setdefault("services.agent_repository_service", MagicMock())
sys.modules.setdefault("utils.auth_utils", MagicMock())

from apps.agent_repository_app import agent_repository_router

app = FastAPI()
app.include_router(agent_repository_router)
client = TestClient(app)


@pytest.fixture
def mock_auth_header():
    return {"Authorization": "Bearer test_token"}


def test_list_agent_repository_listings_api_defaults_dedupe_without_agent_id(
    mocker,
    mock_auth_header,
):
    """Test list API defaults to dedupe when agent_id is not provided."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_list = mocker.patch(
        "apps.agent_repository_app.list_agent_repository_listings_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list.return_value = {"items": []}

    response = client.get("/repository/agent", headers=mock_auth_header)

    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_list.assert_called_once_with(
        status=None,
        agent_id=None,
        deduplicate_by_agent_id=True,
    )


def test_list_agent_repository_listings_api_disables_dedupe_for_agent_id(
    mocker,
    mock_auth_header,
):
    """Test agent_id lookup defaults to returning all records for the agent."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_list = mocker.patch(
        "apps.agent_repository_app.list_agent_repository_listings_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list.return_value = {"items": []}

    response = client.get(
        "/repository/agent?agent_id=123",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_list.assert_called_once_with(
        status=None,
        agent_id=123,
        deduplicate_by_agent_id=False,
    )


def test_list_agent_repository_listings_api_passes_explicit_dedupe(
    mocker,
    mock_auth_header,
):
    """Test explicit dedupe query parameter overrides the agent_id default."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_list = mocker.patch(
        "apps.agent_repository_app.list_agent_repository_listings_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list.return_value = {"items": []}

    response = client.get(
        "/repository/agent?agent_id=123&deduplicate_by_agent_id=true",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_list.assert_called_once_with(
        status=None,
        agent_id=123,
        deduplicate_by_agent_id=True,
    )


def test_create_agent_repository_listing_api_success(mocker, mock_auth_header):
    """Test create_agent_repository_listing_api success case."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_create_listing = mocker.patch(
        "apps.agent_repository_app.create_agent_repository_listing_impl",
        new_callable=AsyncMock,
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_create_listing.return_value = {
        "agent_repository_id": 42,
        "agent_id": 123,
        "version_no": 1,
        "is_updated": False,
    }

    response = client.post(
        "/repository/agent/123/versions/1",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_create_listing.assert_awaited_once_with(
        agent_id=123,
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        version_no=1,
    )
    assert response.json()["agent_repository_id"] == 42
    assert response.json()["is_updated"] is False


def test_create_agent_repository_listing_api_draft_version(mocker, mock_auth_header):
    """Test create_agent_repository_listing_api with draft version (version_no=0)."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_create_listing = mocker.patch(
        "apps.agent_repository_app.create_agent_repository_listing_impl",
        new_callable=AsyncMock,
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_create_listing.return_value = {
        "agent_repository_id": 42,
        "agent_id": 123,
        "version_no": 0,
        "is_updated": True,
    }

    response = client.post(
        "/repository/agent/123/versions/0",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_create_listing.assert_awaited_once_with(
        agent_id=123,
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        version_no=0,
    )
    assert response.json()["version_no"] == 0


def test_create_agent_repository_listing_api_bad_request(mocker, mock_auth_header):
    """Test create_agent_repository_listing_api with ValueError."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_create_listing = mocker.patch(
        "apps.agent_repository_app.create_agent_repository_listing_impl",
        new_callable=AsyncMock,
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_create_listing.side_effect = ValueError("version_no must be >= 0")

    response = client.post(
        "/repository/agent/123/versions/-1",
        headers=mock_auth_header,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "version_no must be >= 0"


def test_create_agent_repository_listing_api_rejects_asset_owner(mocker, mock_auth_header):
    """Test create_agent_repository_listing_api rejects ASSET_OWNER agents with 400."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_create_listing = mocker.patch(
        "apps.agent_repository_app.create_agent_repository_listing_impl",
        new_callable=AsyncMock,
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_create_listing.side_effect = ValueError("租户管理员智能体无法共享")

    response = client.post(
        "/repository/agent/123/versions/1",
        headers=mock_auth_header,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "租户管理员智能体无法共享"


def test_create_agent_repository_listing_api_exception(mocker, mock_auth_header):
    """Test create_agent_repository_listing_api with general exception."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_create_listing = mocker.patch(
        "apps.agent_repository_app.create_agent_repository_listing_impl",
        new_callable=AsyncMock,
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_create_listing.side_effect = Exception("Database error")

    response = client.post(
        "/repository/agent/123/versions/1",
        headers=mock_auth_header,
    )

    assert response.status_code == 500
    assert "Create agent repository listing error." in response.json()["detail"]


def test_update_agent_repository_status_api_success(mocker, mock_auth_header):
    """Test update_agent_repository_status_api passes tenant_id to service."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_update_status = mocker.patch(
        "apps.agent_repository_app.update_agent_repository_status_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_update_status.return_value = {
        "agent_repository_id": 42,
        "status": "shared",
        "name": "agent_one",
    }

    response = client.patch(
        "/repository/agent/42/status",
        headers=mock_auth_header,
        json={"status": "shared"},
    )

    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_update_status.assert_called_once_with(
        agent_repository_id=42,
        status="shared",
        user_id="test_user_id",
        tenant_id="test_tenant_id",
    )
    assert response.json()["status"] == "shared"


def test_update_agent_repository_status_api_unauthorized(mocker, mock_auth_header):
    """Test update_agent_repository_status_api maps UnauthorizedError to 401."""
    from consts.exceptions import UnauthorizedError

    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_update_status = mocker.patch(
        "apps.agent_repository_app.update_agent_repository_status_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_update_status.side_effect = UnauthorizedError("Not authorized")

    response = client.patch(
        "/repository/agent/42/status",
        headers=mock_auth_header,
        json={"status": "pending_review"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authorized"


def test_update_agent_repository_status_api_bad_request(mocker, mock_auth_header):
    """Test update_agent_repository_status_api maps ValueError to 400."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_update_status = mocker.patch(
        "apps.agent_repository_app.update_agent_repository_status_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_update_status.side_effect = ValueError("Invalid status transition")

    response = client.patch(
        "/repository/agent/42/status",
        headers=mock_auth_header,
        json={"status": "shared"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid status transition"


def test_list_agent_repository_categories_api_success(mocker, mock_auth_header):
    """Test categories API returns hardcoded category array."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_list_categories = mocker.patch(
        "apps.agent_repository_app.list_agent_repository_categories_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list_categories.return_value = [
        {"id": 1, "name": "写作助手"},
        {"id": 1000, "name": "其它"},
    ]

    response = client.get("/repository/agent/categories", headers=mock_auth_header)

    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "name": "写作助手"},
        {"id": 1000, "name": "其它"},
    ]
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_list_categories.assert_called_once_with()


def test_list_agent_repository_categories_api_unauthorized(mocker, mock_auth_header):
    """Test categories API maps UnauthorizedError to 401."""
    from consts.exceptions import UnauthorizedError

    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_get_user_id.side_effect = UnauthorizedError("Not authorized")

    response = client.get("/repository/agent/categories", headers=mock_auth_header)

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authorized"


def test_list_my_editable_agents_api_success_default_ownership(
    mocker,
    mock_auth_header,
):
    """Test mine API returns items and counts with default ownership."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_list_mine = mocker.patch(
        "apps.agent_repository_app.list_my_editable_agents_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list_mine.return_value = {
        "items": [{"agent_id": 1, "name": "Agent One", "repository_info": []}],
        "counts": {"all": 1, "created": 1, "others": 0},
    }

    response = client.get("/repository/agent/mine", headers=mock_auth_header)

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"agent_id": 1, "name": "Agent One", "repository_info": []}],
        "counts": {"all": 1, "created": 1, "others": 0},
    }
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_list_mine.assert_called_once_with(
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        ownership="all",
    )


def test_list_my_editable_agents_api_passes_ownership_filter(
    mocker,
    mock_auth_header,
):
    """Test mine API forwards ownership query parameter to service."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_list_mine = mocker.patch(
        "apps.agent_repository_app.list_my_editable_agents_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list_mine.return_value = {"items": [], "counts": {"all": 0, "created": 0, "others": 0}}

    response = client.get(
        "/repository/agent/mine?ownership=others",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_list_mine.assert_called_once_with(
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        ownership="others",
    )


def test_list_my_editable_agents_api_bad_request(mocker, mock_auth_header):
    """Test mine API maps ValueError to 400."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_list_mine = mocker.patch(
        "apps.agent_repository_app.list_my_editable_agents_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list_mine.side_effect = ValueError("Invalid ownership filter: bad")

    response = client.get(
        "/repository/agent/mine?ownership=bad",
        headers=mock_auth_header,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid ownership filter: bad"
