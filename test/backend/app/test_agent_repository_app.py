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
        "source_version_no": 1,
        "is_updated": False,
    }

    response = client.post(
        "/repository/123/versions/1",
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
        "source_version_no": 0,
        "is_updated": True,
    }

    response = client.post(
        "/repository/123/versions/0",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_create_listing.assert_awaited_once_with(
        agent_id=123,
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        version_no=0,
    )
    assert response.json()["source_version_no"] == 0


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
        "/repository/123/versions/-1",
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
        "/repository/123/versions/1",
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
        "/repository/123/versions/1",
        headers=mock_auth_header,
    )

    assert response.status_code == 500
    assert "Create agent repository listing error." in response.json()["detail"]
