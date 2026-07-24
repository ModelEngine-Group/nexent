"""
Unit tests for backend/apps/mcp_management_app.py

Tests community/registry management REST API endpoints including the review
workflow, tenant isolation, and download tracking.
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
    McpNotFoundError, McpValidationError, McpNameConflictError, UnauthorizedError,
)
from fastapi.testclient import TestClient
from fastapi import FastAPI
from http import HTTPStatus

from apps.mcp_management_app import router

import apps.mcp_management_app as mgmt_app
mgmt_app.McpNotFoundError = McpNotFoundError
mgmt_app.McpValidationError = McpValidationError
mgmt_app.McpNameConflictError = McpNameConflictError
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

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_registry_mcp_services')
    def test_list_unauthorized(self, mock_list, mock_auth):
        """Test registry list returns 401 on UnauthorizedError."""
        mock_auth.side_effect = UnauthorizedError("unauthorized")
        resp = client.get("/mcp-tools/registry/list", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_registry_mcp_services')
    def test_list_server_error(self, mock_list, mock_auth):
        """Test registry list returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.side_effect = RuntimeError("unexpected")
        resp = client.get("/mcp-tools/registry/list", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ============================================================================
# GET /mcp-tools/community/list
# ============================================================================

class TestCommunityList:
    """Test GET /mcp-tools/community/list"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_services')
    def test_list_success(self, mock_list, mock_auth):
        """Test successful community list retrieval (tenant-scoped)."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.return_value = {"count": 1, "nextCursor": None, "items": []}
        resp = client.get("/mcp-tools/community/list", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["status"] == "success"
        mock_list.assert_called_once_with(
            tenant_id="tid", user_id="uid", search=None, tag=None,
            transport_type=None, cursor=None, limit=30,
        )

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_services')
    def test_list_with_tag_filter(self, mock_list, mock_auth):
        """Test community list with tag and transport type filters."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.return_value = {"count": 0, "nextCursor": None, "items": []}
        resp = client.get(
            "/mcp-tools/community/list?tag=python&transport_type=url",
            headers=AUTH_HEADER,
        )
        assert resp.status_code == HTTPStatus.OK

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_services')
    def test_list_unauthorized(self, mock_list, mock_auth):
        """Test community list returns 401 on UnauthorizedError."""
        mock_auth.side_effect = UnauthorizedError("unauthorized")
        resp = client.get("/mcp-tools/community/list", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_services')
    def test_list_server_error(self, mock_list, mock_auth):
        """Test community list returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.side_effect = RuntimeError("unexpected")
        resp = client.get("/mcp-tools/community/list", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ============================================================================
# GET /mcp-tools/community/tags/stats
# ============================================================================

class TestCommunityTagStats:
    """Test GET /mcp-tools/community/tags/stats"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_tag_stats')
    def test_tag_stats(self, mock_stats, mock_auth):
        """Test community tag statistics retrieval (tenant-scoped)."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_stats.return_value = [{"tag": "python", "count": 10}]
        resp = client.get("/mcp-tools/community/tags/stats", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["data"][0]["tag"] == "python"
        mock_stats.assert_called_once_with(tenant_id="tid")

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_tag_stats')
    def test_tag_stats_unauthorized(self, mock_stats, mock_auth):
        """Test tag stats returns 401 on UnauthorizedError."""
        mock_auth.side_effect = UnauthorizedError("unauthorized")
        resp = client.get("/mcp-tools/community/tags/stats", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_tag_stats')
    def test_tag_stats_server_error(self, mock_stats, mock_auth):
        """Test tag stats returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_stats.side_effect = RuntimeError("unexpected")
        resp = client.get("/mcp-tools/community/tags/stats", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ============================================================================
# GET /mcp-tools/community/review/list
# ============================================================================

class TestCommunityReviewList:
    """Test GET /mcp-tools/community/review/list"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_review_services')
    def test_list_reviews(self, mock_list, mock_auth):
        """Test listing review submissions."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.return_value = {"count": 1, "nextCursor": None, "items": []}
        resp = client.get("/mcp-tools/community/review/list", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["status"] == "success"

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_review_services')
    def test_list_reviews_with_status_filter(self, mock_list, mock_auth):
        """Test listing reviews filtered by status."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.return_value = {"count": 0, "nextCursor": None, "items": []}
        resp = client.get(
            "/mcp-tools/community/review/list?status=pending",
            headers=AUTH_HEADER,
        )
        assert resp.status_code == HTTPStatus.OK

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_review_services')
    def test_list_reviews_unauthorized(self, mock_list, mock_auth):
        """Test listing reviews returns 401 on UnauthorizedError."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.side_effect = UnauthorizedError("unauthorized")
        resp = client.get("/mcp-tools/community/review/list", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_community_mcp_review_services')
    def test_list_reviews_server_error(self, mock_list, mock_auth):
        """Test listing reviews returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.side_effect = RuntimeError("unexpected")
        resp = client.get("/mcp-tools/community/review/list", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ============================================================================
# POST /mcp-tools/community/review/approve
# ============================================================================

class TestCommunityReviewApprove:
    """Test POST /mcp-tools/community/review/approve"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.approve_community_mcp_service')
    def test_approve_success(self, mock_approve, mock_auth):
        """Test successful review approval."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.post(
            "/mcp-tools/community/review/approve",
            json={"review_id": 1},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["status"] == "success"
        mock_approve.assert_called_once_with(
            tenant_id="tid", user_id="uid", market_id=1,
        )

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.approve_community_mcp_service')
    def test_approve_not_found(self, mock_approve, mock_auth):
        """Test approval fails when review is not found."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_approve.side_effect = McpNotFoundError("not found")
        resp = client.post(
            "/mcp-tools/community/review/approve",
            json={"review_id": 999},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.approve_community_mcp_service')
    def test_approve_unauthorized(self, mock_approve, mock_auth):
        """Test approval returns 401 on UnauthorizedError."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_approve.side_effect = UnauthorizedError("unauthorized")
        resp = client.post(
            "/mcp-tools/community/review/approve",
            json={"review_id": 1},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.approve_community_mcp_service')
    def test_approve_server_error(self, mock_approve, mock_auth):
        """Test approval returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_approve.side_effect = RuntimeError("unexpected")
        resp = client.post(
            "/mcp-tools/community/review/approve",
            json={"review_id": 1},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ============================================================================
# POST /mcp-tools/community/review/reject
# ============================================================================

class TestCommunityReviewReject:
    """Test POST /mcp-tools/community/review/reject"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.reject_community_mcp_service')
    def test_reject_success(self, mock_reject, mock_auth):
        """Test successful review rejection."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.post(
            "/mcp-tools/community/review/reject",
            json={"review_id": 1},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["status"] == "success"

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.reject_community_mcp_service')
    def test_reject_not_found(self, mock_reject, mock_auth):
        """Test rejection fails when review is not found."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_reject.side_effect = McpNotFoundError("not found")
        resp = client.post(
            "/mcp-tools/community/review/reject",
            json={"review_id": 999},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.reject_community_mcp_service')
    def test_reject_unauthorized(self, mock_reject, mock_auth):
        """Test rejection returns 401 on UnauthorizedError."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_reject.side_effect = UnauthorizedError("unauthorized")
        resp = client.post(
            "/mcp-tools/community/review/reject",
            json={"review_id": 1},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.reject_community_mcp_service')
    def test_reject_server_error(self, mock_reject, mock_auth):
        """Test rejection returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_reject.side_effect = RuntimeError("unexpected")
        resp = client.post(
            "/mcp-tools/community/review/reject",
            json={"review_id": 1},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ============================================================================
# POST /mcp-tools/community/publish
# ============================================================================

class TestCommunityPublish:
    """Test POST /mcp-tools/community/publish"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_publish_success(self, mock_publish, mock_auth):
        """Test successful publishing creates a review and returns review_id."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.return_value = 42
        resp = client.post("/mcp-tools/community/publish", json={
            "mcp_id": 1, "name": "svc", "description": "desc",
            "tags": ["a"],
            "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["data"]["market_id"] == 42

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_publish_not_found(self, mock_publish, mock_auth):
        """Test publishing fails when source MCP record is not found."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.side_effect = McpNotFoundError("not found")
        resp = client.post("/mcp-tools/community/publish", json={
            "mcp_id": 999, "name": "x", "description": "d",
            "tags": [],
            "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_publish_name_conflict(self, mock_publish, mock_auth):
        """Test publishing fails on name conflict."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.side_effect = McpNameConflictError("name exists")
        resp = client.post("/mcp-tools/community/publish", json={
            "mcp_id": 1, "name": "taken", "description": "d",
            "tags": [],
            "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_publish_validation_error(self, mock_publish, mock_auth):
        """Test publishing fails with validation error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.side_effect = McpValidationError("invalid")
        resp = client.post("/mcp-tools/community/publish", json={
            "mcp_id": 1, "name": "svc", "description": "d",
            "tags": [],
            "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_publish_unauthorized(self, mock_publish, mock_auth):
        """Test publishing returns 401 on UnauthorizedError."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.side_effect = UnauthorizedError("unauthorized")
        resp = client.post("/mcp-tools/community/publish", json={
            "mcp_id": 1, "name": "svc", "description": "d",
            "tags": [],
            "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_publish_server_error(self, mock_publish, mock_auth):
        """Test publishing returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.side_effect = RuntimeError("unexpected")
        resp = client.post("/mcp-tools/community/publish", json={
            "mcp_id": 1, "name": "svc", "description": "d",
            "tags": [],
            "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ============================================================================
# PUT /mcp-tools/community/update
# ============================================================================

class TestCommunityUpdate:
    """Test PUT /mcp-tools/community/update"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_success(self, mock_update, mock_auth):
        """Test successful community MCP service update (using market_id)."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.put("/mcp-tools/community/update", json={
            "market_id": 1, "name": "new-name",
            "description": "desc", "tags": [],
            "registry_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_not_found(self, mock_update, mock_auth):
        """Test update fails when market record is not found."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_update.side_effect = McpNotFoundError("not found")
        resp = client.put("/mcp-tools/community/update", json={
            "market_id": 999, "name": "x",
            "description": "d", "tags": [],
            "registry_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_validation_error(self, mock_update, mock_auth):
        """Test update fails with validation error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_update.side_effect = McpValidationError("invalid")
        resp = client.put("/mcp-tools/community/update", json={
            "market_id": 1, "name": "x",
            "description": "d", "tags": [],
            "registry_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_name_conflict(self, mock_update, mock_auth):
        """Test update fails on name conflict."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_update.side_effect = McpNameConflictError("name exists")
        resp = client.put("/mcp-tools/community/update", json={
            "market_id": 1, "name": "taken",
            "description": "d", "tags": [],
            "registry_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_unauthorized(self, mock_update, mock_auth):
        """Test update returns 401 on UnauthorizedError."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_update.side_effect = UnauthorizedError("unauthorized")
        resp = client.put("/mcp-tools/community/update", json={
            "market_id": 1, "name": "x",
            "description": "d", "tags": [],
            "registry_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_server_error(self, mock_update, mock_auth):
        """Test update returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_update.side_effect = RuntimeError("unexpected")
        resp = client.put("/mcp-tools/community/update", json={
            "market_id": 1, "name": "x",
            "description": "d", "tags": [],
            "registry_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ============================================================================
# DELETE /mcp-tools/community/delete
# ============================================================================

class TestCommunityDelete:
    """Test DELETE /mcp-tools/community/delete"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.delete_community_mcp_service')
    def test_delete_success(self, mock_delete, mock_auth):
        """Test successful deletion of a market MCP service."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.delete("/mcp-tools/community/delete?market_id=1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.delete_community_mcp_service')
    def test_delete_not_found(self, mock_delete, mock_auth):
        """Test deletion fails when record is not found."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_delete.side_effect = McpNotFoundError("not found")
        resp = client.delete("/mcp-tools/community/delete?market_id=999", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.delete_community_mcp_service')
    def test_delete_unauthorized(self, mock_delete, mock_auth):
        """Test deletion returns 401 on UnauthorizedError."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_delete.side_effect = UnauthorizedError("unauthorized")
        resp = client.delete("/mcp-tools/community/delete?market_id=1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.delete_community_mcp_service')
    def test_delete_server_error(self, mock_delete, mock_auth):
        """Test deletion returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_delete.side_effect = RuntimeError("unexpected")
        resp = client.delete("/mcp-tools/community/delete?market_id=1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


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
        mock_list.assert_called_once_with(tenant_id="tid", user_id="uid")

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_my_community_mcp_services')
    def test_list_mine_unauthorized(self, mock_list, mock_auth):
        """Test my community list returns 401 on UnauthorizedError."""
        mock_auth.side_effect = UnauthorizedError("unauthorized")
        resp = client.get("/mcp-tools/community/mine", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.list_my_community_mcp_services')
    def test_list_mine_server_error(self, mock_list, mock_auth):
        """Test my community list returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.side_effect = RuntimeError("unexpected")
        resp = client.get("/mcp-tools/community/mine", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ============================================================================
# POST /mcp-tools/community/{market_id}/download
# ============================================================================

class TestCommunityDownload:
    """Test POST /mcp-tools/community/{market_id}/download"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.increment_mcp_market_download_count')
    def test_download_success(self, mock_inc, mock_auth):
        """Test successful download count increment."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.post("/mcp-tools/community/1/download", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["status"] == "success"
        mock_inc.assert_called_once_with(1)

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.increment_mcp_market_download_count')
    def test_download_unauthorized(self, mock_inc, mock_auth):
        """Test download returns 401 on UnauthorizedError."""
        mock_auth.side_effect = UnauthorizedError("unauthorized")
        resp = client.post("/mcp-tools/community/1/download", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.increment_mcp_market_download_count')
    def test_download_server_error(self, mock_inc, mock_auth):
        """Test download returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_inc.side_effect = RuntimeError("unexpected")
        resp = client.post("/mcp-tools/community/1/download", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ============================================================================
# POST /mcp-tools/community (RESTful create)
# ============================================================================

class TestCreateCommunity:
    """Test POST /mcp-tools/community"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_create_success(self, mock_publish, mock_auth):
        """Test successful community MCP creation."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.return_value = 42
        resp = client.post("/mcp-tools/community", json={
            "mcp_id": 1, "name": "svc", "description": "desc",
            "tags": ["a"],
            "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["data"]["market_id"] == 42

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_create_not_found(self, mock_publish, mock_auth):
        """Test create fails when source MCP not found."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.side_effect = McpNotFoundError("not found")
        resp = client.post("/mcp-tools/community", json={
            "mcp_id": 999, "name": "x", "description": "d",
            "tags": [], "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_create_validation_error(self, mock_publish, mock_auth):
        """Test create fails with validation error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.side_effect = McpValidationError("invalid")
        resp = client.post("/mcp-tools/community", json={
            "mcp_id": 1, "name": "svc", "description": "d",
            "tags": [], "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_create_name_conflict(self, mock_publish, mock_auth):
        """Test create fails on name conflict."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.side_effect = McpNameConflictError("name exists")
        resp = client.post("/mcp-tools/community", json={
            "mcp_id": 1, "name": "taken", "description": "d",
            "tags": [], "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_create_unauthorized(self, mock_publish, mock_auth):
        """Test create returns 401 on UnauthorizedError."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.side_effect = UnauthorizedError("unauthorized")
        resp = client.post("/mcp-tools/community", json={
            "mcp_id": 1, "name": "svc", "description": "d",
            "tags": [], "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.publish_community_mcp_service')
    def test_create_server_error(self, mock_publish, mock_auth):
        """Test create returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_publish.side_effect = RuntimeError("unexpected")
        resp = client.post("/mcp-tools/community", json={
            "mcp_id": 1, "name": "svc", "description": "d",
            "tags": [], "mcp_server": "http://srv", "config_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ============================================================================
# PUT /mcp-tools/community/{market_id} (RESTful update)
# ============================================================================

class TestUpdateCommunityByMarketId:
    """Test PUT /mcp-tools/community/{market_id}"""

    COMMON_BODY = {"market_id": 1, "name": "x", "description": "d", "tags": [], "registry_json": None}

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_success(self, mock_update, mock_auth):
        """Test successful update by market_id."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.put("/mcp-tools/community/1", json={
            "market_id": 1, "name": "new-name", "description": "desc", "tags": [],
            "registry_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["status"] == "success"

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_not_found(self, mock_update, mock_auth):
        """Test update by market_id fails when record not found."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_update.side_effect = McpNotFoundError("not found")
        resp = client.put("/mcp-tools/community/999", json={
            "market_id": 999, "name": "x", "description": "d", "tags": [],
            "registry_json": None,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_validation_error(self, mock_update, mock_auth):
        """Test update by market_id fails with validation error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_update.side_effect = McpValidationError("invalid")
        resp = client.put("/mcp-tools/community/1", json={
            **self.COMMON_BODY,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_name_conflict(self, mock_update, mock_auth):
        """Test update by market_id fails on name conflict."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_update.side_effect = McpNameConflictError("name exists")
        resp = client.put("/mcp-tools/community/1", json={
            **self.COMMON_BODY, "name": "taken",
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_unauthorized(self, mock_update, mock_auth):
        """Test update by market_id returns 401 on UnauthorizedError."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_update.side_effect = UnauthorizedError("unauthorized")
        resp = client.put("/mcp-tools/community/1", json={
            **self.COMMON_BODY,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.update_community_mcp_service')
    def test_update_server_error(self, mock_update, mock_auth):
        """Test update by market_id returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_update.side_effect = RuntimeError("unexpected")
        resp = client.put("/mcp-tools/community/1", json={
            **self.COMMON_BODY,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ============================================================================
# DELETE /mcp-tools/community/{market_id} (RESTful delete)
# ============================================================================

class TestDeleteCommunityByMarketId:
    """Test DELETE /mcp-tools/community/{market_id}"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.delete_community_mcp_service')
    def test_delete_success(self, mock_delete, mock_auth):
        """Test successful RESTful deletion by market_id."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.delete("/mcp-tools/community/1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["status"] == "success"

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.delete_community_mcp_service')
    def test_delete_not_found(self, mock_delete, mock_auth):
        """Test RESTful deletion fails when record not found."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_delete.side_effect = McpNotFoundError("not found")
        resp = client.delete("/mcp-tools/community/999", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.delete_community_mcp_service')
    def test_delete_unauthorized(self, mock_delete, mock_auth):
        """Test RESTful deletion returns 401 on UnauthorizedError."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_delete.side_effect = UnauthorizedError("unauthorized")
        resp = client.delete("/mcp-tools/community/1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.delete_community_mcp_service')
    def test_delete_server_error(self, mock_delete, mock_auth):
        """Test RESTful deletion returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_delete.side_effect = RuntimeError("unexpected")
        resp = client.delete("/mcp-tools/community/1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ============================================================================
# PATCH /mcp-tools/community/{market_id}/status (change listing status)
# ============================================================================

class TestChangeCommunityStatus:
    """Test PATCH /mcp-tools/community/{market_id}/status"""

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.change_mcp_market_status')
    def test_change_status_success(self, mock_change, mock_auth):
        """Test successful status change."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.patch("/mcp-tools/community/1/status", json={
            "status": "shared",
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["status"] == "success"

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.change_mcp_market_status')
    def test_change_status_not_found(self, mock_change, mock_auth):
        """Test status change fails when record not found."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_change.side_effect = McpNotFoundError("not found")
        resp = client.patch("/mcp-tools/community/999/status", json={
            "status": "shared",
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.change_mcp_market_status')
    def test_change_status_name_conflict(self, mock_change, mock_auth):
        """Test status change fails on name conflict."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_change.side_effect = McpNameConflictError("name exists")
        resp = client.patch("/mcp-tools/community/1/status", json={
            "status": "shared",
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.change_mcp_market_status')
    def test_change_status_unauthorized(self, mock_change, mock_auth):
        """Test status change returns 401 on UnauthorizedError."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_change.side_effect = UnauthorizedError("unauthorized")
        resp = client.patch("/mcp-tools/community/1/status", json={
            "status": "shared",
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.UNAUTHORIZED

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.change_mcp_market_status')
    def test_change_status_invalid_value(self, mock_change, mock_auth):
        """Test status change returns 400 on invalid status value."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_change.side_effect = ValueError("invalid status")
        resp = client.patch("/mcp-tools/community/1/status", json={
            "status": "invalid",
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    @patch('apps.mcp_management_app.get_current_user_info')
    @patch('apps.mcp_management_app.change_mcp_market_status')
    def test_change_status_server_error(self, mock_change, mock_auth):
        """Test status change returns 500 on unexpected error."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_change.side_effect = RuntimeError("unexpected")
        resp = client.patch("/mcp-tools/community/1/status", json={
            "status": "shared",
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
