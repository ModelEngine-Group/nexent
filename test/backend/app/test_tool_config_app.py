from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

sys.modules['boto3'] = MagicMock()

patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.minio_client', minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

from consts.exceptions import MCPConnectionError, NotFoundException

import pytest
from fastapi.testclient import TestClient
from http import HTTPStatus

from apps.tool_config_app import router
from fastapi import FastAPI

import apps.tool_config_app as tool_config_app
tool_config_app.MCPConnectionError = MCPConnectionError

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestListToolsAPI:
    """Test endpoint for listing tools"""

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.list_all_tools')
    def test_list_tools_success(self, mock_list_all_tools, mock_get_user_id):
        """Test successful retrieval of tool list"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_list_all_tools.return_value = [
            {"id": 1, "name": "Tool1"},
            {"id": 2, "name": "Tool2"}
        ]

        response = client.get("/tool/list")

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "Tool1"
        assert data[1]["name"] == "Tool2"

        mock_get_user_id.assert_called_once_with(None)
        mock_list_all_tools.assert_called_once_with(tenant_id="tenant456")

    @patch('apps.tool_config_app.get_current_user_id')
    def test_list_tools_auth_error(self, mock_get_user_id):
        """Test authentication error when listing tools"""
        mock_get_user_id.side_effect = Exception("Auth error")

        response = client.get("/tool/list")

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to get tool info, error in: Auth error" in data["detail"]

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.list_all_tools')
    def test_list_tools_service_error(self, mock_list_all_tools, mock_get_user_id):
        """Test service error when listing tools"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_list_all_tools.side_effect = Exception("Service error")

        response = client.get("/tool/list")

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to get tool info, error in: Service error" in data["detail"]


class TestSearchToolInfoAPI:
    """Test endpoint for searching tool information"""

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.search_tool_info_impl')
    def test_search_tool_info_success(self, mock_search_tool_info, mock_get_user_id):
        """Test successful tool information search"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_search_tool_info.return_value = {
            "tool": "info", "config": {"key": "value"}}

        response = client.post(
            "/tool/search",
            json={"agent_id": 123, "tool_id": 456}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["tool"] == "info"
        assert data["config"]["key"] == "value"

        mock_get_user_id.assert_called_once_with(None)
        mock_search_tool_info.assert_called_once_with(123, 456, "tenant456")

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.search_tool_info_impl')
    def test_search_tool_info_service_error(self, mock_search_tool_info, mock_get_user_id):
        """Test service error when searching tool info"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_search_tool_info.side_effect = Exception("Search error")

        response = client.post(
            "/tool/search",
            json={"agent_id": 123, "tool_id": 456}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to search tool info" in data["detail"]


class TestUpdateToolInfoAPI:
    """Test endpoint for updating tool information"""

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.update_tool_info_impl')
    def test_update_tool_info_success(self, mock_update_tool_info, mock_get_user_id):
        """Test successful tool information update"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_update_tool_info.return_value = {
            "updated": True, "tool_id": "tool456"}

        response = client.post(
            "/tool/update",
            json={
                "agent_id": 123,
                "tool_id": 456,
                "params": {"key": "value"},
                "enabled": True
            }
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["updated"] == True
        assert data["tool_id"] == "tool456"

        mock_get_user_id.assert_called_once_with(None)
        assert mock_update_tool_info.call_count == 1
        args = mock_update_tool_info.call_args[0]
        assert args[1] == "tenant456"
        assert args[2] == "user123"

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.update_tool_info_impl')
    def test_update_tool_info_service_error(self, mock_update_tool_info, mock_get_user_id):
        """Test service error when updating tool info"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_update_tool_info.side_effect = Exception("Update error")

        response = client.post(
            "/tool/update",
            json={
                "agent_id": 123,
                "tool_id": 456,
                "params": {"key": "value"},
                "enabled": True
            }
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to update tool, error in: Update error" in data["detail"]


class TestScanAndUpdateToolAPI:
    """Test endpoint for scanning and updating tools"""

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.update_tool_list')
    def test_scan_and_update_tool_success(self, mock_update_tool_list, mock_get_user_id):
        """Test successful tool scan and update"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_update_tool_list.return_value = None

        response = client.get("/tool/scan_tool")

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert "Successfully update tool" in data["message"]

        mock_get_user_id.assert_called_once_with(None)
        mock_update_tool_list.assert_called_once_with(
            tenant_id="tenant456", user_id="user123")

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.update_tool_list')
    def test_scan_and_update_tool_mcp_error(self, mock_update_tool_list, mock_get_user_id):
        """Test MCP connection error during tool scan"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_update_tool_list.side_effect = MCPConnectionError(
            "MCP connection failed")

        response = client.get("/tool/scan_tool")

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "MCP connection failed" in data["detail"]

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.update_tool_list')
    def test_scan_and_update_tool_general_error(self, mock_update_tool_list, mock_get_user_id):
        """Test general error during tool scan"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_update_tool_list.side_effect = Exception("General update error")

        response = client.get("/tool/scan_tool")

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to update tool" in data["detail"]


class TestLoadLastToolConfigAPI:
    """Test endpoint for loading last tool configuration"""

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.load_last_tool_config_impl')
    def test_load_last_tool_config_success(self, mock_load_config, mock_get_user_id):
        """Test successful loading of last tool configuration"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_load_config.return_value = {
            "param1": "value1", "param2": "value2"}

        response = client.get("/tool/load_config/123")

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert data["message"] == {"param1": "value1", "param2": "value2"}

        mock_get_user_id.assert_called_once_with(None)
        mock_load_config.assert_called_once_with(123, "tenant456", "user123")

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.load_last_tool_config_impl')
    def test_load_last_tool_config_not_found(self, mock_load_config, mock_get_user_id):
        """Test loading tool config when not found"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_load_config.side_effect = ValueError(
            "Tool configuration not found for tool ID: 123")

        response = client.get("/tool/load_config/123")

        assert response.status_code == HTTPStatus.NOT_FOUND
        data = response.json()
        assert "Tool configuration not found" in data["detail"]

        mock_get_user_id.assert_called_once_with(None)
        mock_load_config.assert_called_once_with(123, "tenant456", "user123")

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.load_last_tool_config_impl')
    def test_load_last_tool_config_service_error(self, mock_load_config, mock_get_user_id):
        """Test service error when loading tool config"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_load_config.side_effect = Exception("Database error")

        response = client.get("/tool/load_config/123")

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to load tool config" in data["detail"]

        mock_get_user_id.assert_called_once_with(None)
        mock_load_config.assert_called_once_with(123, "tenant456", "user123")

    @patch('apps.tool_config_app.get_current_user_id')
    def test_load_last_tool_config_auth_error(self, mock_get_user_id):
        """Test authentication error when loading tool config"""
        mock_get_user_id.side_effect = Exception("Auth error")

        response = client.get("/tool/load_config/123")

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to load tool config" in data["detail"]

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.load_last_tool_config_impl')
    def test_load_last_tool_config_with_authorization_header(self, mock_load_config, mock_get_user_id):
        """Test loading tool config with authorization header"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_load_config.return_value = {"param1": "value1"}

        response = client.get(
            "/tool/load_config/123",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        mock_get_user_id.assert_called_with("Bearer test_token")


class TestValidateToolAPI:
    """Test endpoint for validating tools"""

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.validate_tool_impl')
    def test_validate_tool_success(self, mock_validate_tool, mock_get_user_id):
        """Test successful tool validation"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_validate_tool.return_value = {
            "status": "valid", "result": "test_result"}

        response = client.post(
            "/tool/validate",
            json={
                "name": "test_tool",
                "source": "local",
                "usage": None,
                "inputs": {"param1": "value1"},
                "params": {"config": "value"}
            }
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "valid"
        assert data["result"] == "test_result"

        mock_get_user_id.assert_called_once_with(None)
        mock_validate_tool.assert_called_once()

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.validate_tool_impl')
    def test_validate_tool_mcp_connection_error(self, mock_validate_tool, mock_get_user_id):
        """Test MCP connection error during tool validation"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_validate_tool.side_effect = MCPConnectionError(
            "MCP connection failed")

        response = client.post(
            "/tool/validate",
            json={
                "name": "test_tool",
                "source": "mcp",
                "usage": "nexent",
                "inputs": {"param1": "value1"}
            }
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "MCP connection failed" in data["detail"]

        mock_get_user_id.assert_called_once_with(None)
        mock_validate_tool.assert_called_once()

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.validate_tool_impl')
    def test_validate_tool_not_found_error(self, mock_validate_tool, mock_get_user_id):
        """Test tool not found error during validation"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_validate_tool.side_effect = NotFoundException("Tool not found")

        response = client.post(
            "/tool/validate",
            json={
                "name": "nonexistent_tool",
                "source": "local",
                "usage": None,
                "inputs": {"param1": "value1"}
            }
        )

        assert response.status_code == HTTPStatus.NOT_FOUND
        data = response.json()
        assert "Tool not found" in data["detail"]

        mock_get_user_id.assert_called_once_with(None)
        mock_validate_tool.assert_called_once()

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.validate_tool_impl')
    def test_validate_tool_general_error(self, mock_validate_tool, mock_get_user_id):
        """Test general error during tool validation"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_validate_tool.side_effect = Exception("General validation error")

        response = client.post(
            "/tool/validate",
            json={
                "name": "test_tool",
                "source": "local",
                "usage": None,
                "inputs": {"param1": "value1"}
            }
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "General validation error" in data["detail"]

        mock_get_user_id.assert_called_once_with(None)
        mock_validate_tool.assert_called_once()

    @patch('apps.tool_config_app.get_current_user_id')
    def test_validate_tool_auth_error(self, mock_get_user_id):
        """Test authentication error during tool validation"""
        mock_get_user_id.side_effect = Exception("Auth error")

        response = client.post(
            "/tool/validate",
            json={
                "name": "test_tool",
                "source": "local",
                "usage": None,
                "inputs": {"param1": "value1"}
            }
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Auth error" in data["detail"]

        mock_get_user_id.assert_called_once_with(None)

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.validate_tool_impl')
    def test_validate_tool_with_authorization_header(self, mock_validate_tool, mock_get_user_id):
        """Test tool validation with authorization header"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_validate_tool.return_value = {"status": "valid"}

        response = client.post(
            "/tool/validate",
            json={
                "name": "test_tool",
                "source": "mcp",
                "usage": "nexent",
                "inputs": {"param1": "value1"}
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        mock_get_user_id.assert_called_with("Bearer test_token")

    def test_validate_tool_missing_required_fields(self):
        """Test tool validation with missing required fields"""
        response = client.post(
            "/tool/validate",
            json={
                "source": "local",
                "usage": None,
                "inputs": {"param1": "value1"}
            }
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        response = client.post(
            "/tool/validate",
            json={
                "name": "test_tool",
                "usage": None,
                "inputs": {"param1": "value1"}
            }
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


# ============================================================================
# OpenAPI Service Management Tests
# ============================================================================

class TestImportOpenAPIServiceAPI:
    """Test endpoint for importing OpenAPI services"""

    @patch('apps.tool_config_app._refresh_openapi_services_in_mcp')
    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.import_openapi_service')
    def test_import_openapi_service_success(
        self, mock_import_service, mock_get_user_id, mock_refresh_mcp
    ):
        """Test successful OpenAPI service import"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_import_service.return_value = {
            "tools_created": 5,
            "tools_updated": 2,
            "tools_deleted": 1
        }
        mock_refresh_mcp.return_value = {"status": "refreshed"}

        response = client.post(
            "/tool/openapi_service",
            json={
                "service_name": "test_service",
                "server_url": "https://api.example.com",
                "openapi_json": {"openapi": "3.0.0", "info": {"title": "Test"}, "paths": {}},
                "service_description": "Test API",
                "force_update": False
            }
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert data["message"] == "OpenAPI service import successful"
        assert data["data"]["tools_created"] == 5
        assert data["data"]["tools_updated"] == 2
        assert data["data"]["tools_deleted"] == 1
        assert data["data"]["mcp_refresh"]["status"] == "refreshed"

        mock_get_user_id.assert_called_once_with(None)
        mock_import_service.assert_called_once_with(
            service_name="test_service",
            openapi_json={"openapi": "3.0.0", "info": {"title": "Test"}, "paths": {}},
            server_url="https://api.example.com",
            tenant_id="tenant456",
            user_id="user123",
            service_description="Test API",
            force_update=False
        )
        mock_refresh_mcp.assert_called_once_with("tenant456")

    @patch('apps.tool_config_app.get_current_user_id')
    def test_import_openapi_service_missing_service_name(self, mock_get_user_id):
        """Test import with missing service_name"""
        mock_get_user_id.return_value = ("user123", "tenant456")

        response = client.post(
            "/tool/openapi_service",
            json={
                "server_url": "https://api.example.com",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}}
            }
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "service_name is required" in data["detail"]

    @patch('apps.tool_config_app.get_current_user_id')
    def test_import_openapi_service_missing_server_url(self, mock_get_user_id):
        """Test import with missing server_url"""
        mock_get_user_id.return_value = ("user123", "tenant456")

        response = client.post(
            "/tool/openapi_service",
            json={
                "service_name": "test_service",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}}
            }
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "server_url is required" in data["detail"]

    @patch('apps.tool_config_app.get_current_user_id')
    def test_import_openapi_service_missing_openapi_json(self, mock_get_user_id):
        """Test import with missing openapi_json"""
        mock_get_user_id.return_value = ("user123", "tenant456")

        response = client.post(
            "/tool/openapi_service",
            json={
                "service_name": "test_service",
                "server_url": "https://api.example.com"
            }
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "openapi_json is required" in data["detail"]

    @patch('apps.tool_config_app._refresh_openapi_services_in_mcp')
    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.import_openapi_service')
    def test_import_openapi_service_with_force_update(
        self, mock_import_service, mock_get_user_id, mock_refresh_mcp
    ):
        """Test import with force_update=True"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_import_service.return_value = {"tools_created": 0, "tools_updated": 3}
        mock_refresh_mcp.return_value = {"status": "refreshed"}

        response = client.post(
            "/tool/openapi_service",
            json={
                "service_name": "test_service",
                "server_url": "https://api.example.com",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}},
                "force_update": True
            }
        )

        assert response.status_code == HTTPStatus.OK
        mock_import_service.assert_called_once()
        args = mock_import_service.call_args
        assert args[1]["force_update"] == True

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.import_openapi_service')
    def test_import_openapi_service_service_error(
        self, mock_import_service, mock_get_user_id
    ):
        """Test service error during OpenAPI service import"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_import_service.side_effect = Exception("Import failed")

        response = client.post(
            "/tool/openapi_service",
            json={
                "service_name": "test_service",
                "server_url": "https://api.example.com",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}}
            }
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to import OpenAPI service" in data["detail"]

        mock_get_user_id.assert_called_once_with(None)
        mock_import_service.assert_called_once()

    @patch('apps.tool_config_app.get_current_user_id')
    def test_import_openapi_service_auth_error(self, mock_get_user_id):
        """Test authentication error during OpenAPI service import"""
        mock_get_user_id.side_effect = Exception("Auth error")

        response = client.post(
            "/tool/openapi_service",
            json={
                "service_name": "test_service",
                "server_url": "https://api.example.com",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}}
            }
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Auth error" in data["detail"]

    @patch('apps.tool_config_app._refresh_openapi_services_in_mcp')
    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.import_openapi_service')
    def test_import_openapi_service_with_authorization_header(
        self, mock_import_service, mock_get_user_id, mock_refresh_mcp
    ):
        """Test OpenAPI service import with authorization header"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_import_service.return_value = {"tools_created": 1}
        mock_refresh_mcp.return_value = {}

        response = client.post(
            "/tool/openapi_service",
            json={
                "service_name": "test_service",
                "server_url": "https://api.example.com",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}}
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        mock_get_user_id.assert_called_with("Bearer test_token")


class TestListOpenAPIServicesAPI:
    """Test endpoint for listing OpenAPI services"""

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.list_openapi_services')
    def test_list_openapi_services_success(
        self, mock_list_services, mock_get_user_id
    ):
        """Test successful listing of OpenAPI services"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_list_services.return_value = [
            {"name": "Service1", "tool_count": 5},
            {"name": "Service2", "tool_count": 3}
        ]

        response = client.get("/tool/openapi_services")

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "success"
        assert len(data["data"]) == 2
        assert data["data"][0]["name"] == "Service1"
        assert data["data"][1]["name"] == "Service2"

        mock_get_user_id.assert_called_once_with(None)
        mock_list_services.assert_called_once_with("tenant456")

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.list_openapi_services')
    def test_list_openapi_services_empty(
        self, mock_list_services, mock_get_user_id
    ):
        """Test listing when no OpenAPI services exist"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_list_services.return_value = []

        response = client.get("/tool/openapi_services")

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "success"
        assert data["data"] == []

        mock_get_user_id.assert_called_once_with(None)
        mock_list_services.assert_called_once_with("tenant456")

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.list_openapi_services')
    def test_list_openapi_services_service_error(
        self, mock_list_services, mock_get_user_id
    ):
        """Test service error when listing OpenAPI services"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_list_services.side_effect = Exception("Database error")

        response = client.get("/tool/openapi_services")

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to list OpenAPI services" in data["detail"]

        mock_get_user_id.assert_called_once_with(None)
        mock_list_services.assert_called_once_with("tenant456")

    @patch('apps.tool_config_app.get_current_user_id')
    def test_list_openapi_services_auth_error(self, mock_get_user_id):
        """Test authentication error when listing OpenAPI services"""
        mock_get_user_id.side_effect = Exception("Auth error")

        response = client.get("/tool/openapi_services")

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Auth error" in data["detail"]

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.list_openapi_services')
    def test_list_openapi_services_with_authorization_header(
        self, mock_list_services, mock_get_user_id
    ):
        """Test listing OpenAPI services with authorization header"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_list_services.return_value = [{"name": "Service1"}]

        response = client.get(
            "/tool/openapi_services",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        mock_get_user_id.assert_called_with("Bearer test_token")


class TestDeleteOpenAPIServiceAPI:
    """Test endpoint for deleting an OpenAPI service"""

    @patch('apps.tool_config_app._refresh_openapi_services_in_mcp')
    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.delete_openapi_service')
    def test_delete_openapi_service_success(
        self, mock_delete_service, mock_get_user_id, mock_refresh_mcp
    ):
        """Test successful deletion of OpenAPI service"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_delete_service.return_value = True
        mock_refresh_mcp.return_value = {"status": "refreshed"}

        response = client.delete("/tool/openapi_service/test_service")

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Service deleted successfully"
        assert data["status"] == "success"
        assert data["mcp_refresh"]["status"] == "refreshed"

        mock_get_user_id.assert_called_once_with(None)
        mock_delete_service.assert_called_once_with("test_service", "tenant456", "user123")
        mock_refresh_mcp.assert_called_once_with("tenant456")

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.delete_openapi_service')
    def test_delete_openapi_service_not_found(
        self, mock_delete_service, mock_get_user_id
    ):
        """Test deleting non-existent OpenAPI service"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_delete_service.return_value = False

        response = client.delete("/tool/openapi_service/nonexistent_service")

        assert response.status_code == HTTPStatus.NOT_FOUND
        data = response.json()
        assert "Service not found" in data["detail"]

        mock_get_user_id.assert_called_once_with(None)
        mock_delete_service.assert_called_once_with("nonexistent_service", "tenant456", "user123")

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.delete_openapi_service')
    def test_delete_openapi_service_http_exception_reraised(
        self, mock_delete_service, mock_get_user_id
    ):
        """Test HTTPException is re-raised correctly"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        from fastapi import HTTPException
        mock_delete_service.side_effect = HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Access denied"
        )

        response = client.delete("/tool/openapi_service/test_service")

        assert response.status_code == HTTPStatus.FORBIDDEN
        data = response.json()
        assert "Access denied" in data["detail"]

    @patch('apps.tool_config_app._refresh_openapi_services_in_mcp')
    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.delete_openapi_service')
    def test_delete_openapi_service_mcp_refresh_error(
        self, mock_delete_service, mock_get_user_id, mock_refresh_mcp
    ):
        """Test MCP refresh error after successful deletion"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_delete_service.return_value = True
        mock_refresh_mcp.side_effect = Exception("MCP refresh failed")

        response = client.delete("/tool/openapi_service/test_service")

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to delete OpenAPI service" in data["detail"]

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.delete_openapi_service')
    def test_delete_openapi_service_service_error(
        self, mock_delete_service, mock_get_user_id
    ):
        """Test service error when deleting OpenAPI service"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_delete_service.side_effect = Exception("Database error")

        response = client.delete("/tool/openapi_service/test_service")

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to delete OpenAPI service" in data["detail"]

        mock_get_user_id.assert_called_once_with(None)
        mock_delete_service.assert_called_once_with("test_service", "tenant456", "user123")

    @patch('apps.tool_config_app.get_current_user_id')
    def test_delete_openapi_service_auth_error(self, mock_get_user_id):
        """Test authentication error when deleting OpenAPI service"""
        mock_get_user_id.side_effect = Exception("Auth error")

        response = client.delete("/tool/openapi_service/test_service")

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Auth error" in data["detail"]

    @patch('apps.tool_config_app._refresh_openapi_services_in_mcp')
    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.delete_openapi_service')
    def test_delete_openapi_service_with_authorization_header(
        self, mock_delete_service, mock_get_user_id, mock_refresh_mcp
    ):
        """Test deleting OpenAPI service with authorization header"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_delete_service.return_value = True
        mock_refresh_mcp.return_value = {}

        response = client.delete(
            "/tool/openapi_service/test_service",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        mock_get_user_id.assert_called_with("Bearer test_token")
        mock_delete_service.assert_called_once_with("test_service", "tenant456", "user123")


# ============================================================================
# Additional Edge Case Tests
# ============================================================================

class TestEdgeCases:
    """Edge cases and boundary condition tests"""

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.list_all_tools')
    def test_list_tools_empty_response(self, mock_list_all_tools, mock_get_user_id):
        """Test handling of empty tool list"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_list_all_tools.return_value = []

        response = client.get("/tool/list")

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data == []

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.search_tool_info_impl')
    def test_search_tool_info_not_found(self, mock_search_tool_info, mock_get_user_id):
        """Test searching for non-existent tool"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_search_tool_info.return_value = None

        response = client.post(
            "/tool/search",
            json={"agent_id": 999, "tool_id": 999}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data is None

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.update_tool_info_impl')
    def test_update_tool_info_with_empty_params(self, mock_update_tool_info, mock_get_user_id):
        """Test updating tool with empty parameters"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_update_tool_info.return_value = {"updated": True}

        response = client.post(
            "/tool/update",
            json={
                "agent_id": 123,
                "tool_id": 456,
                "params": {},
                "enabled": False
            }
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["updated"] == True

    def test_invalid_json_payload(self):
        """Test handling of invalid JSON payload"""
        response = client.post(
            "/tool/search",
            data="invalid json",
            headers={"content-type": "application/json"}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @patch('apps.tool_config_app.get_current_user_id')
    def test_auth_with_invalid_token_format(self, mock_get_user_id):
        """Test authentication with invalid token format"""
        mock_get_user_id.side_effect = Exception("Invalid token format")

        response = client.get(
            "/tool/list",
            headers={"Authorization": "InvalidTokenFormat"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Invalid token format" in data["detail"]

    @patch('apps.tool_config_app.get_current_user_id')
    def test_scan_tool_auth_failure(self, mock_get_user_id):
        """Test scan tool with authentication failure"""
        mock_get_user_id.side_effect = Exception("Authentication failed")

        response = client.get("/tool/scan_tool")

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to update tool" in data["detail"]


class TestDataValidation:
    """Data validation tests"""

    def test_search_tool_negative_ids(self):
        """Test search with negative IDs"""
        response = client.post(
            "/tool/search",
            json={"agent_id": -1, "tool_id": -1}
        )

        assert response.status_code in [
            HTTPStatus.OK, HTTPStatus.INTERNAL_SERVER_ERROR]

    def test_update_tool_invalid_data_types(self):
        """Test update with invalid data types"""
        response = client.post(
            "/tool/update",
            json={
                "agent_id": "not_an_int",
                "tool_id": "not_an_int",
                "params": "not_a_dict",
                "enabled": "not_a_bool"
            }
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_search_tool_missing_required_fields(self):
        """Test search with missing required fields"""
        response = client.post(
            "/tool/search",
            json={"agent_id": 123}
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        response = client.post(
            "/tool/search",
            json={"tool_id": 456}
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_update_tool_missing_required_fields(self):
        """Test update with missing required fields"""
        response = client.post(
            "/tool/update",
            json={
                "agent_id": 123,
                "tool_id": 456,
                "params": {}
            }
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


class TestConcurrency:
    """Concurrency and performance tests"""

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.list_all_tools')
    def test_multiple_simultaneous_requests(self, mock_list_all_tools, mock_get_user_id):
        """Test handling multiple simultaneous requests"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_list_all_tools.return_value = [{"id": 1, "name": "Tool1"}]

        responses = []
        for _ in range(5):
            response = client.get("/tool/list")
            responses.append(response)

        for response in responses:
            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert len(data) == 1
            assert data[0]["name"] == "Tool1"


class TestIntegration:
    """Integration tests"""

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.list_all_tools')
    @patch('apps.tool_config_app.search_tool_info_impl')
    @patch('apps.tool_config_app.update_tool_info_impl')
    def test_full_tool_lifecycle(self, mock_update_tool_info, mock_search_tool_info,
                                 mock_list_all_tools, mock_get_user_id):
        """Test complete tool configuration lifecycle"""
        mock_get_user_id.return_value = ("user123", "tenant456")

        mock_list_all_tools.return_value = [{"id": 1, "name": "TestTool"}]
        list_response = client.get("/tool/list")
        assert list_response.status_code == HTTPStatus.OK
        data = list_response.json()
        assert len(data) == 1

        mock_search_tool_info.return_value = {"tool": "TestTool", "config": {}}
        search_response = client.post(
            "/tool/search",
            json={"agent_id": 123, "tool_id": 1}
        )
        assert search_response.status_code == HTTPStatus.OK

        mock_update_tool_info.return_value = {"updated": True}
        update_response = client.post(
            "/tool/update",
            json={
                "agent_id": 123,
                "tool_id": 1,
                "params": {"new_key": "new_value"},
                "enabled": True
            }
        )
        assert update_response.status_code == HTTPStatus.OK


class TestErrorHandling:
    """Error handling tests"""

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.list_all_tools')
    def test_authorization_header_handling(self, mock_list_all_tools, mock_get_user_id):
        """Test authorization header handling"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_list_all_tools.return_value = []

        response = client.get(
            "/tool/list",
            headers={"Authorization": "Bearer test_token"}
        )
        assert response.status_code == HTTPStatus.OK
        mock_get_user_id.assert_called_with("Bearer test_token")

        mock_get_user_id.reset_mock()

        response = client.get("/tool/list")
        assert response.status_code == HTTPStatus.OK
        mock_get_user_id.assert_called_with(None)


if __name__ == "__main__":
    pytest.main([__file__])
