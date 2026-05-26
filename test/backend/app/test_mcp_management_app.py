"""
Unit tests for backend/apps/mcp_management_app.py

Tests community/registry management REST API endpoints.
"""

import sys
import os
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
sys.modules['boto3'] = MagicMock()
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.minio_client', minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

from backend.consts.exceptions import (
    McpNotFoundError, McpValidationError, UnauthorizedError,
)
from fastapi.testclient import TestClient
from fastapi import FastAPI
from http import HTTPStatus

from apps.mcp_management_app import router

import apps.mcp_management_app as mgmt_app
mgmt_app.McpNotFoundError = McpNotFoundError
mgmt_app.McpValidationError = McpValidationError
mgmt_app.UnauthorizedError = UnauthorizedError

app = FastAPI()
app.include_router(router)
client = TestClient(app)

AUTH_HEADER = {"Authorization": "Bearer test_token"}


# ============================================================================
# GET /mcp-tools/registry/list
# ============================================================================

class TestRegistryList:
    """Test GET /mcp-tools/registry/list"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_registry_mcp_services')
    def test_list_success(self, mock_list, mock_auth):
        """Test successful registry list retrieval."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.return_value = {"servers": [{"name": "s1"}], "metadata": {}}
        resp = client.get("/mcp-tools/registry/list", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert len(resp.json()["servers"]) == 1

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_registry_mcp_services')
    def test_list_with_filters(self, mock_list, mock_auth):
        """Test registry list with search and limit filters."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.return_value = {"servers": [], "metadata": {}}
        resp = client.get("/mcp-tools/registry/list?search=test&limit=10", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK


# ============================================================================
# GET /mcp-tools/community/list
# ============================================================================

class TestCommunityList:
    """Test GET /mcp-tools/community/list"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_services')
    def test_list_success(self, mock_list, mock_auth):
        """Test successful community list retrieval."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.return_value = {"count": 1, "nextCursor": None, "items": []}
        resp = client.get("/mcp-tools/community/list", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["status"] == "success"

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_services')
    def test_list_with_tag_filter(self, mock_list, mock_auth):
        """Test community list with tag and transport type filters."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.return_value = {"count": 0, "nextCursor": None, "items": []}
        resp = client.get("/mcp-tools/community/list?tag=python&transport_type=url", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK


# ============================================================================
# GET /mcp-tools/community/tags/stats
# ============================================================================

class TestCommunityTagStats:
    """Test GET /mcp-tools/community/tags/stats"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_tag_stats')
    def test_tag_stats(self, mock_stats, mock_auth):
        """Test community tag statistics retrieval."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_stats.return_value = [{"tag": "python", "count": 10}]
        resp = client.get("/mcp-tools/community/tags/stats", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["data"][0]["tag"] == "python"


# ============================================================================
# POST /mcp-tools/community/publish
# ============================================================================

class TestCommunityPublish:
    """Test POST /mcp-tools/community/publish"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_publish_success(self, mock_publish, mock_auth):
        """Test successful publishing of a community MCP service."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.return_value = 42
        resp = client.post("/mcp-tools/community/publish", json={
            "mcp_id": 1, "name": "svc", "description": "desc",
            "version": "1.0", "tags": ["a"],
            "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["data"]["community_id"] == 42

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_publish_not_found(self, mock_publish, mock_auth):
        """Test publishing fails when source MCP record is not found."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.side_effect = McpNotFoundError("not found")
        resp = client.post("/mcp-tools/community/publish", json={
            "mcp_id": 999, "name": "x", "description": "d",
            "version": "1.0", "tags": [],
            "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND


# ============================================================================
# PUT /mcp-tools/community/update
# ============================================================================

class TestCommunityUpdate:
    """Test PUT /mcp-tools/community/update"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_success(self, mock_update, mock_auth):
        """Test successful community MCP service update."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.put("/mcp-tools/community/update", json={
            "community_id": 1, "name": "new-name",
            "description": "desc", "tags": [], "version": "2.0",
            "registry_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_not_found(self, mock_update, mock_auth):
        """Test update fails when community record is not found."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_update.side_effect = McpNotFoundError("not found")
        resp = client.put("/mcp-tools/community/update", json={
            "community_id": 999, "name": "x",
            "description": "d", "tags": [], "version": "1.0",
            "registry_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND


# ============================================================================
# DELETE /mcp-tools/community/delete
# ============================================================================

class TestCommunityDelete:
    """Test DELETE /mcp-tools/community/delete"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.delete_community_mcp_service')
    def test_delete_success(self, mock_delete, mock_auth):
        """Test successful deletion of a community MCP service."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.delete("/mcp-tools/community/delete?community_id=1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.delete_community_mcp_service')
    def test_delete_not_found(self, mock_delete, mock_auth):
        """Test deletion fails when community record is not found."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_delete.side_effect = McpNotFoundError("not found")
        resp = client.delete("/mcp-tools/community/delete?community_id=999", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND


# ============================================================================
# GET /mcp-tools/community/mine
# ============================================================================

class TestCommunityMine:
    """Test GET /mcp-tools/community/mine"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_my_community_mcp_services')
    def test_list_mine(self, mock_list, mock_auth):
        """Test listing of current user's published community services."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.return_value = {"count": 1, "items": []}
        resp = client.get("/mcp-tools/community/mine", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["status"] == "success"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
