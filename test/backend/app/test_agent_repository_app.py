"""Unit tests for backend.apps.agent_repository_app module."""

import os
import sys
import types
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.insert(0, backend_dir)

sys.modules.setdefault("services.agent_repository_service", MagicMock())
sys.modules.setdefault("utils.auth_utils", MagicMock())

consts_model = types.ModuleType("consts.model")


class _AgentRepositoryListingCreateRequest(BaseModel):
    icon: Optional[str] = None
    downloads: int = Field(0, ge=0)
    tags: Optional[List[str]] = None
    tool_count: Optional[int] = Field(None, ge=0)


consts_model.AgentRepositoryListingCreateRequest = _AgentRepositoryListingCreateRequest
sys.modules["consts.model"] = consts_model

from apps.agent_repository_app import agent_repository_router

app = FastAPI()
app.include_router(agent_repository_router)
client = TestClient(app)


@pytest.fixture
def mock_auth_header():
    return {"Authorization": "Bearer test_token"}


def test_list_agent_repository_listings_api_success(
    mocker,
    mock_auth_header,
):
    """Test list API forwards query parameters to service."""
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
        "test_tenant_id",
        status=None,
        agent_id=None,
        page=1,
        page_size=10,
        search=None,
    )


def test_list_agent_repository_listings_api_passes_agent_id(
    mocker,
    mock_auth_header,
):
    """Test list API forwards agent_id query parameter to service."""
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
        "test_tenant_id",
        status=None,
        agent_id=123,
        page=1,
        page_size=10,
        search=None,
    )


def test_list_agent_repository_listings_api_passes_pending_review_status(
    mocker,
    mock_auth_header,
):
    """Test list API forwards pending_review status to service."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_list = mocker.patch(
        "apps.agent_repository_app.list_agent_repository_listings_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list.return_value = {"items": []}

    response = client.get(
        "/repository/agent?status=pending_review",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_list.assert_called_once_with(
        "test_tenant_id",
        status="pending_review",
        agent_id=None,
        page=1,
        page_size=10,
        search=None,
    )


def test_list_agent_repository_listings_api_passes_pagination_and_search(
    mocker,
    mock_auth_header,
):
    """Test list API forwards pagination and search query parameters to service."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_list = mocker.patch(
        "apps.agent_repository_app.list_agent_repository_listings_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list.return_value = {
        "items": [],
        "pagination": {
            "page": 2,
            "page_size": 6,
            "total": 0,
            "total_pages": 0,
        },
    }

    response = client.get(
        "/repository/agent?page=2&page_size=6&search=alpha",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_list.assert_called_once_with(
        "test_tenant_id",
        status=None,
        agent_id=None,
        page=2,
        page_size=6,
        search="alpha",
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
        card_fields=None,
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
        card_fields=None,
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
    """Test create_agent_repository_listing_api propagates unknown exceptions."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_create_listing = mocker.patch(
        "apps.agent_repository_app.create_agent_repository_listing_impl",
        new_callable=AsyncMock,
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_create_listing.side_effect = Exception("Database error")

    with pytest.raises(Exception, match="Database error"):
        client.post(
            "/repository/agent/123/versions/1",
            headers=mock_auth_header,
        )


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
        notify_content=None,
        content=None,
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


def test_create_agent_repository_listing_api_passes_card_fields(mocker, mock_auth_header):
    """Test create listing API forwards card_fields from request body."""
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

    payload = {
        "icon": "🤖",
        "tags": ["代码审查", "自定义"],
        "downloads": 0,
    }
    response = client.post(
        "/repository/agent/123/versions/1",
        headers=mock_auth_header,
        json=payload,
    )

    assert response.status_code == 200
    mock_create_listing.assert_awaited_once_with(
        agent_id=123,
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        version_no=1,
        card_fields=payload,
    )


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
        new_callable=AsyncMock,
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list_mine.return_value = {
        "items": [{"agent_id": 1, "name": "Agent One", "repository_info": []}],
        "counts": {"all": 1, "created": 1, "others": 0},
        "pagination": {
            "page": 1,
            "page_size": 10,
            "total": 1,
            "total_pages": 1,
        },
    }

    response = client.get("/repository/agent/mine", headers=mock_auth_header)

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"agent_id": 1, "name": "Agent One", "repository_info": []}],
        "counts": {"all": 1, "created": 1, "others": 0},
        "pagination": {
            "page": 1,
            "page_size": 10,
            "total": 1,
            "total_pages": 1,
        },
    }
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_list_mine.assert_called_once_with(
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        ownership="all",
        page=1,
        page_size=10,
        search=None,
        new_agent_padding=False,
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
        new_callable=AsyncMock,
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list_mine.return_value = {
        "items": [],
        "counts": {"all": 0, "created": 0, "others": 0},
        "pagination": {
            "page": 1,
            "page_size": 10,
            "total": 0,
            "total_pages": 0,
        },
    }

    response = client.get(
        "/repository/agent/mine?ownership=others",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_list_mine.assert_called_once_with(
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        ownership="others",
        page=1,
        page_size=10,
        search=None,
        new_agent_padding=False,
    )


def test_list_my_editable_agents_api_passes_pagination_and_search(
    mocker,
    mock_auth_header,
):
    """Test mine API forwards pagination and search query parameters to service."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_list_mine = mocker.patch(
        "apps.agent_repository_app.list_my_editable_agents_impl",
        new_callable=AsyncMock,
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list_mine.return_value = {
        "items": [],
        "counts": {"all": 0, "created": 0, "others": 0},
        "pagination": {
            "page": 2,
            "page_size": 5,
            "total": 0,
            "total_pages": 0,
        },
    }

    response = client.get(
        "/repository/agent/mine?page=2&page_size=5&search=alpha",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_list_mine.assert_called_once_with(
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        ownership="all",
        page=2,
        page_size=5,
        search="alpha",
        new_agent_padding=False,
    )


def test_list_my_editable_agents_api_passes_new_agent_padding(
    mocker,
    mock_auth_header,
):
    """Test mine API forwards new_agent_padding query parameter to service."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_list_mine = mocker.patch(
        "apps.agent_repository_app.list_my_editable_agents_impl",
        new_callable=AsyncMock,
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list_mine.return_value = {
        "items": [{"new_agent_padding": True}],
        "counts": {"all": 0, "created": 0, "others": 0},
        "pagination": {
            "page": 1,
            "page_size": 6,
            "total": 1,
            "total_pages": 1,
        },
    }

    response = client.get(
        "/repository/agent/mine?new_agent_padding=true",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_list_mine.assert_called_once_with(
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        ownership="all",
        page=1,
        page_size=10,
        search=None,
        new_agent_padding=True,
    )


def test_list_my_editable_agents_api_bad_request(mocker, mock_auth_header):
    """Test mine API maps ValueError to 400."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_list_mine = mocker.patch(
        "apps.agent_repository_app.list_my_editable_agents_impl",
        new_callable=AsyncMock,
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_list_mine.side_effect = ValueError("Invalid ownership filter: bad")

    response = client.get(
        "/repository/agent/mine?ownership=bad",
        headers=mock_auth_header,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid ownership filter: bad"


def test_get_agent_repository_listing_detail_api_passes_tenant_id(
    mocker,
    mock_auth_header,
):
    """Test detail API forwards caller tenant_id to service."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_get_detail = mocker.patch(
        "apps.agent_repository_app.get_agent_repository_listing_detail_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_detail.return_value = {
        "agent_repository_id": 42,
        "name": "agent_one",
    }

    response = client.get("/repository/agent/42", headers=mock_auth_header)

    assert response.status_code == 200
    mock_get_detail.assert_called_once_with(42, "test_tenant_id")


def test_import_agent_from_repository_api_passes_tenant_id(
    mocker,
    mock_auth_header,
):
    """Test import API forwards caller tenant_id to service."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_import = mocker.patch(
        "apps.agent_repository_app.import_agent_from_repository_impl",
        new_callable=AsyncMock,
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_import.return_value = {}

    response = client.post(
        "/repository/agent/42/import",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_import.assert_awaited_once_with(
        agent_repository_id=42,
        tenant_id="test_tenant_id",
        authorization=mock_auth_header["Authorization"],
    )


def test_check_repository_import_precheck_api_passes_tenant_id(
    mocker,
    mock_auth_header,
):
    """Test import precheck API forwards caller tenant_id to service."""
    mock_get_user_id = mocker.patch(
        "apps.agent_repository_app.get_current_user_id"
    )
    mock_precheck = mocker.patch(
        "apps.agent_repository_app.check_repository_import_precheck_impl",
    )

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_precheck.return_value = {
        "agent_repository_id": 42,
        "display_name": "Agent One",
        "total_count": 1,
        "available_count": 1,
        "percent": 100,
        "has_abnormal": False,
        "items": [],
    }

    response = client.get(
        "/repository/agent/42/import_precheck",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_precheck.assert_called_once_with(
        agent_repository_id=42,
        tenant_id="test_tenant_id",
    )
