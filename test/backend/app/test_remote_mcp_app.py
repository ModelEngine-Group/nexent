"""
Unit tests for backend/apps/remote_mcp_app.py

Tests all MCP REST API endpoints covering: tools, add, update, delete,
list, healthcheck, port management, enable/disable, and container operations.
"""

import sys
import os
import types
import importlib.machinery
from unittest.mock import patch, MagicMock, AsyncMock

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules['boto3'] = boto3_module

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
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
patch('consts.const.ENABLE_UPLOAD_IMAGE', True).start()
patch('services.mcp_container_service.create_container_client_from_config').start()
patch('services.mcp_container_service.DockerContainerConfig').start()

from backend.consts.exceptions import (
    MCPConnectionError, MCPNameIllegal, MCPContainerError,
    McpNotFoundError, McpValidationError, McpNameConflictError, McpPortConflictError,
)
from fastapi.testclient import TestClient
from fastapi import FastAPI
from http import HTTPStatus

from apps.remote_mcp_app import router

import apps.remote_mcp_app as remote_app
remote_app.MCPConnectionError = MCPConnectionError
remote_app.MCPNameIllegal = MCPNameIllegal
remote_app.MCPContainerError = MCPContainerError
remote_app.McpNotFoundError = McpNotFoundError
remote_app.McpValidationError = McpValidationError
remote_app.McpNameConflictError = McpNameConflictError
remote_app.McpPortConflictError = McpPortConflictError

app = FastAPI()
app.include_router(router)
client = TestClient(app)

AUTH_HEADER = {"Authorization": "Bearer test_token"}


# ============================================================================
# GET /mcp/tools
# ============================================================================

class TestGetTools:
    """Test GET /mcp/tools"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.list_mcp_service_tools_by_id')
    def test_get_tools_success(self, mock_list_tools, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_tool = MagicMock()
        mock_tool.model_dump.return_value = {"name": "tool1", "description": "desc"}
        mock_list_tools.return_value = [mock_tool]

        resp = client.get("/mcp/tools?mcp_id=1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["tools"]) == 1

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.list_mcp_service_tools_by_id')
    def test_get_tools_not_found(self, mock_list_tools, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list_tools.side_effect = McpNotFoundError("not found")

        resp = client.get("/mcp/tools?mcp_id=999", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.list_mcp_service_tools_by_id')
    def test_get_tools_connection_error(self, mock_list_tools, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list_tools.side_effect = MCPConnectionError("connection failed")

        resp = client.get("/mcp/tools?mcp_id=1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.SERVICE_UNAVAILABLE


# ============================================================================
# POST /mcp/add
# ============================================================================

class TestAddMcpService:
    """Test POST /mcp/add"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_mcp_service')
    def test_add_success(self, mock_add, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.post("/mcp/add", json={
            "name": "test-svc", "description": "desc",
            "source": "local", "server_url": "http://srv/mcp",
            "tags": [], "enabled": False,
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["status"] == "success"

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_mcp_service')
    def test_add_name_conflict(self, mock_add, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_add.side_effect = MCPNameIllegal("name exists")
        resp = client.post("/mcp/add", json={
            "name": "dup", "source": "local", "server_url": "http://srv",
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.CONFLICT

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_mcp_service')
    def test_add_validation_error(self, mock_add, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_add.side_effect = McpValidationError("bad input")
        resp = client.post("/mcp/add", json={
            "name": "x", "source": "local", "server_url": "http://srv",
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_mcp_service')
    def test_add_with_custom_headers(self, mock_add, mock_auth):
        """Test that custom_headers is passed to add_mcp_service (line 125)."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.post("/mcp/add", json={
            "name": "test-svc", "description": "desc",
            "source": "local", "server_url": "http://srv/mcp",
            "tags": [], "enabled": False,
            "custom_headers": {"X-Custom-Header": "test-value", "X-Api-Key": "secret"},
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["status"] == "success"
        mock_add.assert_called_once()
        call_kwargs = mock_add.call_args[1]
        assert call_kwargs["custom_headers"] == {"X-Custom-Header": "test-value", "X-Api-Key": "secret"}

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_mcp_service')
    def test_add_with_empty_custom_headers(self, mock_add, mock_auth):
        """Test that empty custom_headers is passed correctly (line 125)."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.post("/mcp/add", json={
            "name": "test-svc", "description": "desc",
            "source": "local", "server_url": "http://srv/mcp",
            "tags": [], "enabled": False,
            "custom_headers": {},
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        call_kwargs = mock_add.call_args[1]
        assert call_kwargs["custom_headers"] == {}


# ============================================================================
# POST /mcp/add-from-config
# ============================================================================

class TestAddFromConfig:
    """Test POST /mcp/add-from-config"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_container_mcp_service')
    def test_add_from_config_success(self, mock_add, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_add.return_value = {
            "service_name": "svc", "mcp_url": "http://localhost:8080/mcp",
            "container_id": "cid", "container_name": "svc-uid", "host_port": 8080,
        }
        resp = client.post("/mcp/add-from-config", json={
            "name": "svc", "source": "local", "port": 8080,
            "mcp_config": {"mcpServers": {"svc": {"command": "echo", "args": []}}},
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        data = resp.json()
        assert data["status"] == "success"
        assert data["data"]["container_id"] == "cid"

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_container_mcp_service')
    def test_add_from_config_name_conflict(self, mock_add, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_add.side_effect = McpNameConflictError("name exists")
        resp = client.post("/mcp/add-from-config", json={
            "name": "dup", "source": "local", "port": 8080,
            "mcp_config": {"mcpServers": {"dup": {"command": "echo"}}},
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.CONFLICT


# ============================================================================
# PUT /mcp/update
# ============================================================================

class TestUpdateMcpService:
    """Test PUT /mcp/update"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_mcp_service')
    def test_update_success(self, mock_update, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.put("/mcp/update", json={
            "mcp_id": 1, "name": "new-name", "server_url": "http://new.url",
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_mcp_service')
    def test_update_not_found(self, mock_update, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_update.side_effect = McpNotFoundError("not found")
        resp = client.put("/mcp/update", json={
            "mcp_id": 999, "name": "x", "server_url": "http://u",
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_mcp_service')
    def test_update_with_custom_headers(self, mock_update, mock_auth):
        """Test that custom_headers is passed to update_mcp_service (line 243)."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.put("/mcp/update", json={
            "mcp_id": 1, "name": "new-name", "server_url": "http://new.url",
            "custom_headers": {"X-Updated-Header": "new-value"},
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args[1]
        assert call_kwargs["custom_headers"] == {"X-Updated-Header": "new-value"}

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_mcp_service')
    def test_update_clears_custom_headers(self, mock_update, mock_auth):
        """Test that empty custom_headers can be passed (line 243)."""
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.put("/mcp/update", json={
            "mcp_id": 1, "name": "new-name", "server_url": "http://new.url",
            "custom_headers": {},
        }, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        call_kwargs = mock_update.call_args[1]
        assert call_kwargs["custom_headers"] == {}


# ============================================================================
# DELETE /mcp/{mcp_id}
# ============================================================================

class TestDeleteMcpService:
    """Test DELETE /mcp/{mcp_id}"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.delete_mcp_service')
    def test_delete_success(self, mock_delete, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.delete("/mcp/1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.delete_mcp_service')
    def test_delete_not_found(self, mock_delete, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_delete.side_effect = McpNotFoundError("not found")
        resp = client.delete("/mcp/999", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND


# ============================================================================
# DELETE /mcp/container/{container_id}
# ============================================================================

class TestStopMcpContainer:
    """Test DELETE /mcp/container/{container_id}"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.delete_mcp_by_container_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_stop_container_success(self, mock_mgr_cls, mock_delete, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_mgr = MagicMock()
        mock_mgr.stop_mcp_container = AsyncMock(return_value=True)
        mock_mgr_cls.return_value = mock_mgr

        resp = client.delete("/mcp/container/container-123", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_stop_container_not_found(self, mock_mgr_cls, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_mgr = MagicMock()
        mock_mgr.stop_mcp_container = AsyncMock(return_value=False)
        mock_mgr_cls.return_value = mock_mgr

        resp = client.delete("/mcp/container/nonexistent", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_stop_container_docker_unavailable(self, mock_mgr_cls, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_mgr_cls.side_effect = MCPContainerError("Docker unavailable")

        resp = client.delete("/mcp/container/container-123", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.SERVICE_UNAVAILABLE


# ============================================================================
# GET /mcp/list
# ============================================================================

class TestGetMcpList:
    """Test GET /mcp/list"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list')
    def test_list_success(self, mock_list, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.return_value = [
            {"remote_mcp_server_name": "svc1", "remote_mcp_server": "http://srv1", "status": True},
        ]
        resp = client.get("/mcp/list", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert len(resp.json()["remote_mcp_server_list"]) == 1

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list')
    def test_list_with_tenant_id(self, mock_list, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_list.return_value = []
        resp = client.get("/mcp/list?tenant_id=explicit_tid", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK


# ============================================================================
# GET /mcp/record/{mcp_id}
# ============================================================================

class TestGetMcpRecord:
    """Test GET /mcp/record/{mcp_id}"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.get_mcp_record_by_id')
    def test_get_record_success(self, mock_get, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_get.return_value = {"mcp_name": "svc", "mcp_server": "http://srv", "authorization_token": "tok"}
        resp = client.get("/mcp/record/1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["mcp_name"] == "svc"

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.get_mcp_record_by_id')
    def test_get_record_with_custom_headers(self, mock_get, mock_auth):
        """Test that custom_headers is returned in response (line 426)."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_get.return_value = {
            "mcp_name": "svc",
            "mcp_server": "http://srv",
            "authorization_token": "tok",
            "custom_headers": {"X-Custom-Header": "test-value", "X-Api-Key": "secret"},
        }
        resp = client.get("/mcp/record/1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        data = resp.json()
        assert data["custom_headers"] == {"X-Custom-Header": "test-value", "X-Api-Key": "secret"}
        assert data["mcp_name"] == "svc"
        assert data["authorization_token"] == "tok"

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.get_mcp_record_by_id')
    def test_get_record_with_empty_custom_headers(self, mock_get, mock_auth):
        """Test that empty custom_headers is returned correctly (line 426)."""
        mock_auth.return_value = ("uid", "tid", "en")
        mock_get.return_value = {
            "mcp_name": "svc",
            "mcp_server": "http://srv",
            "authorization_token": "tok",
            "custom_headers": {},
        }
        resp = client.get("/mcp/record/1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["custom_headers"] == {}

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.get_mcp_record_by_id')
    def test_get_record_not_found(self, mock_get, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_get.return_value = None
        resp = client.get("/mcp/record/999", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND


# ============================================================================
# GET /mcp/healthcheck
# ============================================================================

class TestHealthcheck:
    """Test GET /mcp/healthcheck"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.check_mcp_service_health')
    def test_healthcheck_healthy(self, mock_check, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_check.return_value = "healthy"
        resp = client.get("/mcp/healthcheck?mcp_id=1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["data"]["health_status"] == "healthy"

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.check_mcp_service_health')
    def test_healthcheck_not_found(self, mock_check, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_check.side_effect = McpNotFoundError("not found")
        resp = client.get("/mcp/healthcheck?mcp_id=999", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.check_mcp_service_health')
    def test_healthcheck_connection_error(self, mock_check, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_check.side_effect = MCPConnectionError("unreachable")
        resp = client.get("/mcp/healthcheck?mcp_id=1", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.SERVICE_UNAVAILABLE


# ============================================================================
# GET /mcp/port/check
# ============================================================================

class TestPortCheck:
    """Test GET /mcp/port/check"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.check_container_port_conflict')
    def test_port_available(self, mock_check, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_check.return_value = True
        resp = client.get("/mcp/port/check?port=8080", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["data"]["available"] is True

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.check_container_port_conflict')
    def test_port_in_use(self, mock_check, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_check.return_value = False
        resp = client.get("/mcp/port/check?port=8080", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["data"]["available"] is False


# ============================================================================
# GET /mcp/port/suggest
# ============================================================================

class TestPortSuggest:
    """Test GET /mcp/port/suggest"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.suggest_container_port')
    def test_port_suggest(self, mock_suggest, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_suggest.return_value = 5000
        resp = client.get("/mcp/port/suggest", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert resp.json()["data"]["port"] == 5000


# ============================================================================
# POST /mcp/enable
# ============================================================================

class TestEnableMcpService:
    """Test POST /mcp/enable"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_mcp_service_enabled')
    def test_enable_success(self, mock_enable, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.post("/mcp/enable", json={"mcp_id": 1}, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        mock_enable.assert_called_once_with(tenant_id="tid", user_id="uid", mcp_id=1, enabled=True)

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_mcp_service_enabled')
    def test_enable_not_found(self, mock_enable, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_enable.side_effect = McpNotFoundError("not found")
        resp = client.post("/mcp/enable", json={"mcp_id": 999}, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_mcp_service_enabled')
    def test_enable_name_conflict(self, mock_enable, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_enable.side_effect = McpNameConflictError("name conflict")
        resp = client.post("/mcp/enable", json={"mcp_id": 1}, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.CONFLICT


# ============================================================================
# POST /mcp/disable
# ============================================================================

class TestDisableMcpService:
    """Test POST /mcp/disable"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_mcp_service_enabled')
    def test_disable_success(self, mock_enable, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        resp = client.post("/mcp/disable", json={"mcp_id": 1}, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        mock_enable.assert_called_once_with(tenant_id="tid", user_id="uid", mcp_id=1, enabled=False)

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_mcp_service_enabled')
    def test_disable_not_found(self, mock_enable, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_enable.side_effect = McpNotFoundError("not found")
        resp = client.post("/mcp/disable", json={"mcp_id": 999}, headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.NOT_FOUND


# ============================================================================
# GET /mcp/containers
# ============================================================================

class TestListContainers:
    """Test GET /mcp/containers"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.attach_mcp_container_permissions')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_list_containers_success(self, mock_mgr_cls, mock_attach, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_mgr = MagicMock()
        mock_mgr.list_mcp_containers.return_value = [{"container_id": "c1"}]
        mock_mgr_cls.return_value = mock_mgr
        mock_attach.return_value = [{"container_id": "c1", "permission": "EDIT"}]

        resp = client.get("/mcp/containers", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK
        assert len(resp.json()["containers"]) == 1

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_list_containers_docker_unavailable(self, mock_mgr_cls, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_mgr_cls.side_effect = MCPContainerError("Docker unavailable")
        resp = client.get("/mcp/containers", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.SERVICE_UNAVAILABLE


# ============================================================================
# GET /mcp/container/{container_id}/logs
# ============================================================================

class TestGetContainerLogs:
    """Test GET /mcp/container/{container_id}/logs"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_get_logs_success(self, mock_mgr_cls, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_mgr = MagicMock()

        async def mock_stream(container_id, tail=100, follow=True):
            yield "line1"
            yield "line2"

        mock_mgr.stream_container_logs = mock_stream
        mock_mgr_cls.return_value = mock_mgr

        resp = client.get("/mcp/container/cid/logs?follow=false", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.OK

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_get_logs_docker_unavailable(self, mock_mgr_cls, mock_auth):
        mock_auth.return_value = ("uid", "tid", "en")
        mock_mgr_cls.side_effect = MCPContainerError("Docker unavailable")
        resp = client.get("/mcp/container/cid/logs", headers=AUTH_HEADER)
        assert resp.status_code == HTTPStatus.SERVICE_UNAVAILABLE


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
