from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
sys.modules['boto3'] = MagicMock()

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate',
      lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.minio_client', minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Enable upload image feature for tests
patch('consts.const.ENABLE_UPLOAD_IMAGE', True).start()

# Patch container service dependencies to avoid Docker connections
patch('services.mcp_container_service.create_container_client_from_config').start()
patch('services.mcp_container_service.DockerContainerConfig').start()

# Import exception classes
from consts.exceptions import MCPConnectionError, MCPNameIllegal, MCPContainerError

# Import the modules we need
import pytest
from fastapi.testclient import TestClient
from http import HTTPStatus

# Create a test client with a fresh FastAPI app
from apps.remote_mcp_app import router
from fastapi import FastAPI

# Patch exception classes to ensure tests use correct exceptions
import apps.remote_mcp_app as remote_app
remote_app.MCPConnectionError = MCPConnectionError
remote_app.MCPNameIllegal = MCPNameIllegal
remote_app.MCPContainerError = MCPContainerError

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class MockToolInfo:
    """Mock ToolInfo class for testing"""

    def __init__(self, name, description, params=None):
        self.name = name
        self.description = description
        self.params = params or []

    @property
    def __dict__(self):
        return {
            "name": self.name,
            "description": self.description,
            "params": self.params
        }


class TestGetToolsFromRemoteMCP:
    """Test endpoint for getting tools from remote MCP server"""

    @patch('apps.remote_mcp_app.get_tool_from_remote_mcp_server')
    def test_get_tools_success(self, mock_get_tools):
        """Test successful retrieval of tool information"""
        # Mock tool information
        mock_tools = [
            MockToolInfo("tool1", "Tool 1 description"),
            MockToolInfo("tool2", "Tool 2 description")
        ]
        mock_get_tools.return_value = mock_tools

        response = client.post(
            "/mcp/tools",
            params={"service_name": "test_service",
                    "mcp_url": "http://test.com"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert "tools" in data
        assert len(data["tools"]) == 2
        assert data["status"] == "success"

        mock_get_tools.assert_called_once_with(
            mcp_server_name="test_service",
            remote_mcp_server="http://test.com"
        )

    @patch('apps.remote_mcp_app.get_tool_from_remote_mcp_server')
    def test_get_tools_connection_error(self, mock_get_tools):
        """Test MCP connection error when retrieving tool information"""
        mock_get_tools.side_effect = MCPConnectionError(
            "MCP connection failed")

        response = client.post(
            "/mcp/tools",
            params={"service_name": "test_service",
                    "mcp_url": "http://unreachable.com"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "MCP connection failed" in data["detail"]

    @patch('apps.remote_mcp_app.get_tool_from_remote_mcp_server')
    def test_get_tools_general_failure(self, mock_get_tools):
        """Test general failure to retrieve tool information"""
        mock_get_tools.side_effect = Exception("Unexpected error")

        response = client.post(
            "/mcp/tools",
            params={"service_name": "test_service",
                    "mcp_url": "http://test.com"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to get tools from remote MCP server" in data["detail"]


class TestAddRemoteProxies:
    """Test endpoint for adding remote MCP servers"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_remote_proxy_success(self, mock_add_server, mock_get_user_info):
        """Test successful addition of remote MCP proxy"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_add_server.return_value = None  # No exception means success

        response = client.post(
            "/mcp/add",
            params={"mcp_url": "http://test.com",
                    "service_name": "test_service"},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert "Successfully added remote MCP proxy" in data["message"]

        mock_get_user_info.assert_called_once()
        mock_add_server.assert_called_once_with(
            tenant_id="tenant456",
            user_id="user123",
            remote_mcp_server="http://test.com",
            remote_mcp_server_name="test_service",
            container_id=None,
        )

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_remote_proxy_with_tenant_id_param(self, mock_add_server, mock_get_user_info):
        """Test adding remote MCP proxy with explicit tenant_id parameter"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_add_server.return_value = None

        response = client.post(
            "/mcp/add",
            params={
                "mcp_url": "http://test.com",
                "service_name": "test_service",
                "tenant_id": "explicit_tenant789"
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"

        # Verify that explicit tenant_id is used instead of auth tenant_id
        mock_add_server.assert_called_once_with(
            tenant_id="explicit_tenant789",  # Should use explicit tenant_id
            user_id="user123",
            remote_mcp_server="http://test.com",
            remote_mcp_server_name="test_service",
            container_id=None,
        )

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_remote_proxy_name_exists(self, mock_add_server, mock_get_user_info):
        """Test adding MCP server with existing name"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_add_server.side_effect = MCPNameIllegal("MCP name already exists")

        response = client.post(
            "/mcp/add",
            params={"mcp_url": "http://test.com",
                    "service_name": "existing_service"},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.CONFLICT
        data = response.json()
        assert "MCP name already exists" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_remote_proxy_connection_failed(self, mock_add_server, mock_get_user_info):
        """Test MCP connection failure"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_add_server.side_effect = MCPConnectionError(
            "MCP connection failed")

        response = client.post(
            "/mcp/add",
            params={"mcp_url": "http://unreachable.com",
                    "service_name": "test_service"},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "MCP connection failed" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_remote_proxy_database_error(self, mock_add_server, mock_get_user_info):
        """Test database error - should be handled as general exception"""
        from sqlalchemy.exc import SQLAlchemyError

        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_add_server.side_effect = SQLAlchemyError("Database error")

        response = client.post(
            "/mcp/add",
            params={"mcp_url": "http://test.com",
                    "service_name": "test_service"},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to add remote MCP proxy" in data["detail"]


class TestDeleteRemoteProxies:
    """Test endpoint for deleting remote MCP servers"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.delete_remote_mcp_server_list')
    def test_delete_remote_proxy_success(self, mock_delete_server, mock_get_user_info):
        """Test successful deletion of remote MCP proxy"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_delete_server.return_value = None  # No exception means success

        response = client.delete(
            "/mcp/",
            params={"service_name": "test_service",
                    "mcp_url": "http://test.com"},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert "Successfully deleted remote MCP proxy" in data["message"]

        mock_get_user_info.assert_called_once()
        mock_delete_server.assert_called_once_with(
            tenant_id="tenant456",
            user_id="user123",
            remote_mcp_server="http://test.com",
            remote_mcp_server_name="test_service"
        )

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.delete_remote_mcp_server_list')
    def test_delete_remote_proxy_with_tenant_id_param(self, mock_delete_server, mock_get_user_info):
        """Test deleting remote MCP proxy with explicit tenant_id parameter"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_delete_server.return_value = None

        response = client.delete(
            "/mcp/",
            params={
                "service_name": "test_service",
                "mcp_url": "http://test.com",
                "tenant_id": "explicit_tenant789"
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        # Verify that explicit tenant_id is used
        mock_delete_server.assert_called_once_with(
            tenant_id="explicit_tenant789",
            user_id="user123",
            remote_mcp_server="http://test.com",
            remote_mcp_server_name="test_service"
        )

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.delete_remote_mcp_server_list')
    def test_delete_remote_proxy_database_error(self, mock_delete_server, mock_get_user_info):
        """Test database error during deletion - should be handled as general exception"""
        from sqlalchemy.exc import SQLAlchemyError

        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_delete_server.side_effect = SQLAlchemyError("Database error")

        response = client.delete(
            "/mcp/",
            params={"service_name": "test_service",
                    "mcp_url": "http://test.com"},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to delete remote MCP proxy" in data["detail"]


class TestGetRemoteProxies:
    """Test endpoint for getting remote MCP server list"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list')
    def test_get_remote_proxies_success(self, mock_get_list, mock_get_user_info):
        """Test successful retrieval of remote MCP proxy list"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_server_list = [
            {
                "remote_mcp_server_name": "server1",
                "remote_mcp_server": "http://server1.com",
                "status": True,
                "permission": "EDIT",
            },
            {
                "remote_mcp_server_name": "server2",
                "remote_mcp_server": "http://server2.com",
                "status": False,
                "permission": "READ_ONLY",
            }
        ]
        mock_get_list.return_value = mock_server_list

        response = client.get(
            "/mcp/list",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert "remote_mcp_server_list" in data
        assert len(data["remote_mcp_server_list"]) == 2
        assert data["status"] == "success"
        assert data["remote_mcp_server_list"][0]["permission"] == "EDIT"
        assert data["remote_mcp_server_list"][1]["permission"] == "READ_ONLY"

        mock_get_user_info.assert_called_once()
        mock_get_list.assert_called_once_with(tenant_id="tenant456", user_id="user123")

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list')
    def test_get_remote_proxies_with_tenant_id_param(self, mock_get_list, mock_get_user_info):
        """Test getting remote MCP proxy list with explicit tenant_id parameter"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_get_list.return_value = []

        response = client.get(
            "/mcp/list",
            params={"tenant_id": "explicit_tenant789"},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        # Verify that explicit tenant_id is used
        mock_get_list.assert_called_once_with(tenant_id="explicit_tenant789", user_id="user123")

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list')
    def test_get_remote_proxies_error(self, mock_get_list, mock_get_user_info):
        """Test error when getting list"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_get_list.side_effect = Exception("Database connection failed")

        response = client.get(
            "/mcp/list",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to get remote MCP proxy" in data["detail"]


class TestCheckMCPHealth:
    """Test MCP health check endpoint"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.check_mcp_health_and_update_db')
    def test_check_mcp_health_success(self, mock_health_check, mock_get_user_info):
        """Test successful health check"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_health_check.return_value = None  # No exception means success

        response = client.get(
            "/mcp/healthcheck",
            params={"mcp_url": "http://test.com",
                    "service_name": "test_service"},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"

        mock_get_user_info.assert_called_once()
        mock_health_check.assert_called_once_with(
            "http://test.com", "test_service", "tenant456", "user123"
        )

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.check_mcp_health_and_update_db')
    def test_check_mcp_health_with_tenant_id_param(self, mock_health_check, mock_get_user_info):
        """Test health check with explicit tenant_id parameter"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_health_check.return_value = None

        response = client.get(
            "/mcp/healthcheck",
            params={
                "mcp_url": "http://test.com",
                "service_name": "test_service",
                "tenant_id": "explicit_tenant789"
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        # Verify that explicit tenant_id is used
        mock_health_check.assert_called_once_with(
            "http://test.com", "test_service", "explicit_tenant789", "user123"
        )

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.check_mcp_health_and_update_db')
    def test_check_mcp_health_connection_error(self, mock_health_check, mock_get_user_info):
        """Test MCP connection error during health check"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_health_check.side_effect = MCPConnectionError(
            "MCP connection failed")

        response = client.get(
            "/mcp/healthcheck",
            params={"mcp_url": "http://unreachable.com",
                    "service_name": "test_service"},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "MCP connection failed" in data["detail"]

        mock_get_user_info.assert_called_once()
        mock_health_check.assert_called_once_with(
            "http://unreachable.com", "test_service", "tenant456", "user123"
        )

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.check_mcp_health_and_update_db')
    def test_check_mcp_health_database_error(self, mock_health_check, mock_get_user_info):
        """Test database error during health check - should be handled as general exception"""
        from sqlalchemy.exc import SQLAlchemyError

        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_health_check.side_effect = SQLAlchemyError("Database error")

        response = client.get(
            "/mcp/healthcheck",
            params={"mcp_url": "http://test.com",
                    "service_name": "test_service"},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to check the health of the MCP server" in data["detail"]


class TestIntegration:
    """Integration tests"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list')
    @patch('apps.remote_mcp_app.delete_remote_mcp_server_list')
    def test_full_lifecycle(self, mock_delete, mock_get_list, mock_add, mock_get_user_info):
        """Test complete MCP server lifecycle"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        # 1. Add server
        mock_add.return_value = None
        add_response = client.post(
            "/mcp/add",
            params={"mcp_url": "http://test.com",
                    "service_name": "test_service"},
            headers={"Authorization": "Bearer test_token"}
        )
        assert add_response.status_code == HTTPStatus.OK

        # 2. Get server list
        mock_get_list.return_value = [
            {"remote_mcp_server_name": "test_service",
             "remote_mcp_server": "http://test.com",
             "status": True,
             "permission": "EDIT"}
        ]
        list_response = client.get(
            "/mcp/list",
            headers={"Authorization": "Bearer test_token"}
        )
        assert list_response.status_code == HTTPStatus.OK
        data = list_response.json()
        assert len(data["remote_mcp_server_list"]) == 1
        assert data["remote_mcp_server_list"][0]["permission"] == "EDIT"

        # 3. Delete server
        mock_delete.return_value = None
        delete_response = client.delete(
            "/mcp/",
            params={"service_name": "test_service",
                    "mcp_url": "http://test.com"},
            headers={"Authorization": "Bearer test_token"}
        )
        assert delete_response.status_code == HTTPStatus.OK


class TestErrorHandling:
    """Error handling tests"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list')
    def test_authorization_header_handling(self, mock_get_list, mock_get_user_info):
        """Test authorization header handling"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_get_list.return_value = []  # Mock empty list

        # Test case without Authorization header
        response = client.get("/mcp/list")
        # Should return OK with empty list
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert "remote_mcp_server_list" in data

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_unexpected_error_handling(self, mock_add_server, mock_get_user_info):
        """Test unexpected error handling"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_add_server.side_effect = Exception("Unexpected error")

        response = client.post(
            "/mcp/add",
            params={"mcp_url": "http://test.com",
                    "service_name": "test_service"},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to add remote MCP proxy" in data["detail"]


class TestDataValidation:
    """Data validation tests"""

    def test_missing_parameters(self):
        """Test missing required parameters"""
        # Test missing parameters
        response = client.post("/mcp/add")
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_invalid_url_format(self, mock_add_server, mock_get_user_info):
        """Test invalid URL format with valid authentication"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_add_server.side_effect = MCPConnectionError("Invalid URL format")

        response = client.post(
            "/mcp/add",
            params={"mcp_url": "invalid-url",
                    "service_name": "test_service_invalid"},
            headers={"Authorization": "Bearer valid_token"}
        )
        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE


# ---------------------------------------------------------------------------
# Test add_mcp_from_config
# ---------------------------------------------------------------------------


class TestAddMCPFromConfig:
    """Test endpoint for adding MCP servers from configuration"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    @patch('apps.remote_mcp_app.check_mcp_name_exists', return_value=False)
    def test_add_mcp_from_config_success(self, mock_check_name, mock_add_server, mock_container_manager_class, mock_get_user_info):
        """Test successful addition of MCP server from config"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        # Mock container manager
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.start_mcp_container = AsyncMock(return_value={
            "container_id": "container-123",
            "mcp_url": "http://localhost:5020/mcp",
            "host_port": "5020",
            "status": "started",
            "container_name": "test-service-user1234"
        })

        mock_add_server.return_value = None

        response = client.post(
            "/mcp/add-from-config",
            json={
                "mcpServers": {
                    "test-service": {
                        "command": "npx",
                        "args": ["-y", "test-mcp"],
                        "env": {"NODE_ENV": "production"},
                        "port": 5020
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert len(data["results"]) == 1
        assert data["results"][0]["service_name"] == "test-service"
        assert data["results"][0]["status"] == "success"

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    @patch('apps.remote_mcp_app.check_mcp_name_exists', return_value=False)
    def test_add_mcp_from_config_with_tenant_id_param(self, mock_check_name, mock_add_server, mock_container_manager_class, mock_get_user_info):
        """Test adding MCP server from config with explicit tenant_id parameter"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        # Mock container manager
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.start_mcp_container = AsyncMock(return_value={
            "container_id": "container-123",
            "mcp_url": "http://localhost:5020/mcp",
            "host_port": "5020",
            "status": "started",
            "container_name": "test-service-user1234"
        })

        mock_add_server.return_value = None

        response = client.post(
            "/mcp/add-from-config",
            params={"tenant_id": "explicit_tenant789"},
            json={
                "mcpServers": {
                    "test-service": {
                        "command": "npx",
                        "args": ["-y", "test-mcp"],
                        "env": {"NODE_ENV": "production"},
                        "port": 5020
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        # Verify that explicit tenant_id is used
        mock_check_name.assert_called_once_with(mcp_name="test-service", tenant_id="explicit_tenant789")
        mock_container_manager.start_mcp_container.assert_called_once()
        call_kwargs = mock_container_manager.start_mcp_container.call_args[1]
        assert call_kwargs["tenant_id"] == "explicit_tenant789"
        mock_add_server.assert_called_once()
        add_call_kwargs = mock_add_server.call_args[1]
        assert add_call_kwargs["tenant_id"] == "explicit_tenant789"

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    @patch('apps.remote_mcp_app.check_mcp_name_exists', return_value=False)
    def test_add_mcp_from_config_multiple_servers(self, mock_check_name, mock_add_server, mock_container_manager_class, mock_get_user_info):
        """Test adding multiple MCP servers from config"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.start_mcp_container = AsyncMock(side_effect=[
            {
                "container_id": "container-1",
                "mcp_url": "http://localhost:5020/mcp",
                "host_port": "5020",
                "status": "started",
                "container_name": "service1-user1234"
            },
            {
                "container_id": "container-2",
                "mcp_url": "http://localhost:5021/mcp",
                "host_port": "5021",
                "status": "started",
                "container_name": "service2-user1234"
            }
        ])

        mock_add_server.return_value = None

        response = client.post(
            "/mcp/add-from-config",
            json={
                "mcpServers": {
                    "service1": {
                        "command": "npx",
                        "args": ["-y", "service1"],
                        "port": 5020
                    },
                    "service2": {
                        "command": "npx",
                        "args": ["-y", "service2"],
                        "port": 5021
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert len(data["results"]) == 2

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.check_mcp_name_exists', return_value=False)
    def test_add_mcp_from_config_missing_command(self, mock_check_name, mock_container_manager_class, mock_get_user_info):
        """Test adding MCP server with missing command"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager

        response = client.post(
            "/mcp/add-from-config",
            json={
                "mcpServers": {
                    "test-service": {
                        "args": ["-y", "test-mcp"],
                        "port": 5020
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        data = response.json()
        assert "command" in str(data["detail"]).lower()

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.check_mcp_name_exists', return_value=False)
    def test_add_mcp_from_config_empty_command(self, mock_check_name, mock_container_manager_class, mock_get_user_info):
        """Test adding MCP server with empty command string (covers line 189-191)"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager

        response = client.post(
            "/mcp/add-from-config",
            json={
                "mcpServers": {
                    "test-service": {
                        "command": "",
                        "args": ["-y", "test-mcp"],
                        "port": 5020
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "All MCP servers failed" in data["detail"]
        assert "command is required" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.check_mcp_name_exists', return_value=False)
    def test_add_mcp_from_config_missing_port(self, mock_check_name, mock_container_manager_class, mock_get_user_info):
        """Test adding MCP server with missing port"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager

        response = client.post(
            "/mcp/add-from-config",
            json={
                "mcpServers": {
                    "test-service": {
                        "command": "npx",
                        "args": ["-y", "test-mcp"]
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "port is required" in data["detail"]

    @patch('apps.remote_mcp_app.check_mcp_name_exists')
    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_mcp_from_config_name_exists(self, mock_add_server, mock_container_manager_class, mock_get_user_info, mock_check_name):
        """Test adding MCP server when name already exists"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_check_name.return_value = True  # Name already exists

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager

        response = client.post(
            "/mcp/add-from-config",
            json={
                "mcpServers": {
                    "test-service": {
                        "command": "npx",
                        "args": ["-y", "test-mcp"],
                        "port": 5020
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "All MCP servers failed" in data["detail"]
        assert "MCP name already exists" in data["detail"]
        # Container should not be started when name already exists
        mock_container_manager.start_mcp_container.assert_not_called()

    @patch('apps.remote_mcp_app.check_mcp_name_exists')
    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_mcp_from_config_name_exists_early_check(self, mock_add_server, mock_container_manager_class, mock_get_user_info, mock_check_name):
        """Test adding MCP server when name exists (checked before starting container)"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_check_name.return_value = True  # Name already exists

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager

        response = client.post(
            "/mcp/add-from-config",
            json={
                "mcpServers": {
                    "test-service": {
                        "command": "npx",
                        "args": ["-y", "test-mcp"],
                        "port": 5020
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "All MCP servers failed" in data["detail"]
        assert "MCP name already exists" in data["detail"]
        # Container should not be started when name already exists
        mock_container_manager.start_mcp_container.assert_not_called()

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.check_mcp_name_exists', return_value=False)
    def test_add_mcp_from_config_container_error(self, mock_check_name, mock_container_manager_class, mock_get_user_info):
        """Test adding MCP server when container startup fails"""
        from consts.exceptions import MCPContainerError

        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.start_mcp_container = AsyncMock(
            side_effect=MCPContainerError("Container failed"))

        response = client.post(
            "/mcp/add-from-config",
            json={
                "mcpServers": {
                    "test-service": {
                        "command": "npx",
                        "args": ["-y", "test-mcp"],
                        "port": 5020
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "All MCP servers failed" in data["detail"]
        assert "Container failed" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.check_mcp_name_exists', return_value=False)
    def test_add_mcp_from_config_unexpected_error_in_loop(self, mock_check_name, mock_container_manager_class, mock_get_user_info):
        """Test adding MCP server when unexpected exception occurs in loop (covers line 253-255)"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        # Raise a non-MCPContainerError exception to trigger the general Exception handler
        mock_container_manager.start_mcp_container = AsyncMock(
            side_effect=ValueError("Unexpected error"))

        response = client.post(
            "/mcp/add-from-config",
            json={
                "mcpServers": {
                    "test-service": {
                        "command": "npx",
                        "args": ["-y", "test-mcp"],
                        "port": 5020
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "All MCP servers failed" in data["detail"]
        assert "Unexpected error" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.check_mcp_name_exists', return_value=False)
    def test_add_mcp_from_config_all_fail(self, mock_check_name, mock_container_manager_class, mock_get_user_info):
        """Test adding MCP servers when all fail"""
        from consts.exceptions import MCPContainerError

        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.start_mcp_container = AsyncMock(
            side_effect=MCPContainerError("Container failed"))

        response = client.post(
            "/mcp/add-from-config",
            json={
                "mcpServers": {
                    "service1": {
                        "command": "npx",
                        "args": ["-y", "service1"],
                        "port": 5020
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "All MCP servers failed" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.check_mcp_name_exists', return_value=False)
    def test_add_mcp_from_config_docker_unavailable(self, mock_check_name, mock_container_manager_class, mock_get_user_info):
        """Test adding MCP server when Docker is unavailable"""
        from consts.exceptions import MCPContainerError

        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_container_manager_class.side_effect = MCPContainerError(
            "Docker unavailable")

        response = client.post(
            "/mcp/add-from-config",
            json={
                "mcpServers": {
                    "test-service": {
                        "command": "npx",
                        "args": ["-y", "test-mcp"],
                        "port": 5020
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "Docker service unavailable" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    @patch('apps.remote_mcp_app.check_mcp_name_exists', return_value=False)
    def test_add_mcp_from_config_with_custom_image(self, mock_check_name, mock_add_server, mock_container_manager_class, mock_get_user_info):
        """Test adding MCP server with custom Docker image"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.start_mcp_container = AsyncMock(return_value={
            "container_id": "container-123",
            "mcp_url": "http://localhost:5020/mcp",
            "host_port": "5020",
            "status": "started",
            "container_name": "test-service-user1234"
        })

        mock_add_server.return_value = None

        response = client.post(
            "/mcp/add-from-config",
            json={
                "mcpServers": {
                    "test-service": {
                        "command": "python",
                        "args": ["script.py"],
                        "port": 5020,
                        "image": "custom-image:latest"
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        # Verify custom image was passed
        mock_container_manager.start_mcp_container.assert_called_once()
        call_kwargs = mock_container_manager.start_mcp_container.call_args[1]
        assert call_kwargs["image"] == "custom-image:latest"

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.check_mcp_name_exists', return_value=False)
    def test_add_mcp_from_config_outer_exception(self, mock_check_name, mock_get_user_info):
        """Test adding MCP server when exception occurs outside loop (covers line 275-277)"""
        # Make get_current_user_info raise an exception to trigger outer exception handler
        mock_get_user_info.side_effect = RuntimeError("Failed to get user ID")

        response = client.post(
            "/mcp/add-from-config",
            json={
                "mcpServers": {
                    "test-service": {
                        "command": "npx",
                        "args": ["-y", "test-mcp"],
                        "port": 5020
                    }
                }
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to add MCP servers" in data["detail"]


# ---------------------------------------------------------------------------
# Test stop_mcp_container
# ---------------------------------------------------------------------------


class TestStopMCPContainer:
    """Test endpoint for stopping MCP container"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.delete_mcp_by_container_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_stop_mcp_container_success(self, mock_container_manager_class, mock_delete_mcp, mock_get_user_info):
        """Test successful stopping of MCP container"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.stop_mcp_container = AsyncMock(
            return_value=True)

        response = client.delete(
            "/mcp/container/container-123",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert "stopped successfully" in data["message"]
        mock_container_manager.stop_mcp_container.assert_called_once_with(
            "container-123")
        mock_delete_mcp.assert_called_once_with(
            tenant_id="tenant456",
            user_id="user123",
            container_id="container-123",
        )

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_stop_mcp_container_not_found(self, mock_container_manager_class, mock_get_user_info):
        """Test stopping non-existent container"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.stop_mcp_container = AsyncMock(
            return_value=False)

        response = client.delete(
            "/mcp/container/non-existent",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.NOT_FOUND
        data = response.json()
        assert data["status"] == "error"
        assert "not found" in data["message"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_stop_mcp_container_docker_unavailable(self, mock_container_manager_class, mock_get_user_info):
        """Test stopping container when Docker is unavailable"""
        from consts.exceptions import MCPContainerError

        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_container_manager_class.side_effect = MCPContainerError(
            "Docker unavailable")

        response = client.delete(
            "/mcp/container/container-123",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "Docker service unavailable" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_stop_mcp_container_exception(self, mock_container_manager_class, mock_get_user_info):
        """Test stopping container when exception occurs"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.stop_mcp_container = AsyncMock(
            side_effect=Exception("Unexpected error"))

        response = client.delete(
            "/mcp/container/container-123",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to stop container" in data["detail"]


# ---------------------------------------------------------------------------
# Test list_mcp_containers
# ---------------------------------------------------------------------------


class TestListMCPContainers:
    """Test endpoint for listing MCP containers"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.attach_mcp_container_permissions')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list', return_value=[])
    def test_list_mcp_containers_success(self, mock_get_list, mock_attach_perm, mock_container_manager_class, mock_get_user_info):
        """Test successful listing of MCP containers"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        raw_containers = [
            {
                "container_id": "container-1",
                "name": "service1-user1234",
                "status": "running",
                "mcp_url": "http://localhost:5020/mcp",
                "host_port": "5020"
            },
            {
                "container_id": "container-2",
                "name": "service2-user1234",
                "status": "running",
                "mcp_url": "http://localhost:5021/mcp",
                "host_port": "5021"
            }
        ]
        mock_container_manager.list_mcp_containers.return_value = raw_containers
        mock_attach_perm.return_value = [
            {**raw_containers[0], "permission": "EDIT"},
            {**raw_containers[1], "permission": "READ_ONLY"},
        ]

        response = client.get(
            "/mcp/containers",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert len(data["containers"]) == 2
        assert data["containers"][0]["permission"] == "EDIT"
        assert data["containers"][1]["permission"] == "READ_ONLY"
        mock_container_manager.list_mcp_containers.assert_called_once_with(
            tenant_id="tenant456")
        mock_attach_perm.assert_called_once_with(
            containers=raw_containers,
            tenant_id="tenant456",
            user_id="user123",
        )

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.attach_mcp_container_permissions')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list', return_value=[])
    def test_list_mcp_containers_with_tenant_id_param(self, mock_get_list, mock_attach_perm, mock_container_manager_class, mock_get_user_info):
        """Test listing MCP containers with explicit tenant_id parameter"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.list_mcp_containers.return_value = []
        mock_attach_perm.return_value = []

        response = client.get(
            "/mcp/containers",
            params={"tenant_id": "explicit_tenant789"},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        # Verify that explicit tenant_id is used
        mock_container_manager.list_mcp_containers.assert_called_once_with(
            tenant_id="explicit_tenant789")
        mock_attach_perm.assert_called_once_with(
            containers=[],
            tenant_id="explicit_tenant789",
            user_id="user123",
        )

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.attach_mcp_container_permissions', return_value=[])
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list', return_value=[])
    def test_list_mcp_containers_empty(self, mock_get_list, mock_attach_perm, mock_container_manager_class, mock_get_user_info):
        """Test listing containers when none exist"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.list_mcp_containers.return_value = []

        response = client.get(
            "/mcp/containers",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert len(data["containers"]) == 0
        mock_attach_perm.assert_called_once_with(
            containers=[],
            tenant_id="tenant456",
            user_id="user123",
        )

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list', return_value=[])
    def test_list_mcp_containers_docker_unavailable(self, mock_get_list, mock_container_manager_class, mock_get_user_info):
        """Test listing containers when Docker is unavailable"""
        from consts.exceptions import MCPContainerError

        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_container_manager_class.side_effect = MCPContainerError(
            "Docker unavailable")

        response = client.get(
            "/mcp/containers",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "Docker service unavailable" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list', side_effect=Exception("Unexpected error"))
    def test_list_mcp_containers_exception(self, mock_get_list, mock_container_manager_class, mock_get_user_info):
        """Test listing containers when exception occurs"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.list_mcp_containers.side_effect = Exception(
            "Unexpected error")

        response = client.get(
            "/mcp/containers",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to list containers" in data["detail"]


# ---------------------------------------------------------------------------
# Test upload_mcp_image
# ---------------------------------------------------------------------------


class TestUploadMCPImageValidation:
    """Test endpoint for uploading MCP image and starting container"""

    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_success(self, mock_get_user_info, mock_upload_service):
        """Test successful upload and start of MCP image"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_upload_service.return_value = {
            "message": "MCP container started successfully from uploaded image",
            "status": "success",
            "service_name": "test-service",
            "mcp_url": "http://localhost:5020/mcp",
            "container_id": "container-123",
            "container_name": "test-image-user1234",
            "host_port": "5020"
        }

        # Use actual file content
        file_content = b"fake tar content"

        response = client.post(
            "/mcp/upload-image",
            data={
                "port": 5020,
                "service_name": "test-service",
                "env_vars": '{"NODE_ENV": "production"}'
            },
            files={"file": ("test-image.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert "MCP container started successfully" in data["message"]
        assert data["service_name"] == "test-service"
        assert data["mcp_url"] == "http://localhost:5020/mcp"
        assert data["container_id"] == "container-123"

        mock_get_user_info.assert_called_once()
        mock_upload_service.assert_called_once_with(
            tenant_id="tenant456",
            user_id="user123",
            file_content=file_content,
            filename="test-image.tar",
            port=5020,
            service_name="test-service",
            env_vars='{"NODE_ENV": "production"}'
        )

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    def test_upload_mcp_image_with_tenant_id_param(self, mock_upload_service, mock_get_user_info):
        """Test upload MCP image with explicit tenant_id parameter"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_upload_service.return_value = {
            "message": "MCP container started successfully from uploaded image",
            "status": "success",
            "service_name": "test-service",
            "mcp_url": "http://localhost:5020/mcp",
            "container_id": "container-123",
            "container_name": "test-image-user1234",
            "host_port": "5020"
        }

        file_content = b"fake tar content"
        response = client.post(
            "/mcp/upload-image",
            data={
                "port": 5020,
                "service_name": "test-service",
                "tenant_id": "explicit_tenant789",
                "env_vars": '{"NODE_ENV": "production"}'
            },
            files={"file": ("test-image.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        # Verify that explicit tenant_id is used
        mock_upload_service.assert_called_once_with(
            tenant_id="explicit_tenant789",
            user_id="user123",
            file_content=file_content,
            filename="test-image.tar",
            port=5020,
            service_name="test-service",
            env_vars='{"NODE_ENV": "production"}'
        )

    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_invalid_file_type(self, mock_get_user_info):
        """Test upload with invalid file type"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        response = client.post(
            "/mcp/upload-image",
            data={"port": 5020},
            files={"file": ("test.txt", "content", "text/plain")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "Only .tar files are allowed" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_file_too_large(self, mock_get_user_info):
        """Test upload with file exceeding size limit"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        # Create a large file content (over 1GB) - use smaller size for test
        large_content = b"x" * (1024 * 1024 * 1024 + 1)

        response = client.post(
            "/mcp/upload-image",
            data={"port": 5020},
            files={"file": ("large.tar", large_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "File size exceeds 1GB limit" in data["detail"]

    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_auto_service_name(self, mock_get_user_info, mock_upload_service):
        """Test upload with auto-generated service name"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_upload_service.return_value = {
            "message": "MCP container started successfully from uploaded image",
            "status": "success",
            "service_name": "my-image",  # Auto-generated from filename
            "mcp_url": "http://localhost:5020/mcp",
            "container_id": "container-123",
            "container_name": "my-image-user1234",
            "host_port": "5020"
        }

        file_content = b"fake tar content"

        response = client.post(
            "/mcp/upload-image",
            data={"port": 5020},  # No service_name provided
            files={"file": ("my-image.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        # Should use filename without extension
        assert data["service_name"] == "my-image"

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.check_mcp_name_exists', return_value=False)
    def test_upload_mcp_image_invalid_env_vars_json(self, mock_check_name, mock_container_manager_class, mock_get_user_info):
        """Test upload with invalid JSON in env_vars"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager

        file_content = b"fake tar content"

        response = client.post(
            "/mcp/upload-image",
            data={
                "port": 5020,
                "env_vars": "invalid json {"
            },
            files={"file": ("test.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "Invalid environment variables format" in data["detail"]

    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_name_conflict(self, mock_get_user_info, mock_upload_service):
        """Test upload when MCP service name already exists"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        # Service layer raises MCPNameIllegal for name conflict
        mock_upload_service.side_effect = MCPNameIllegal(
            "MCP service name already exists")

        file_content = b"fake tar content"

        response = client.post(
            "/mcp/upload-image",
            data={"port": 5020, "service_name": "existing-service"},
            files={"file": ("test.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.CONFLICT
        data = response.json()
        assert "MCP service name already exists" in data["detail"]

    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_container_error(self, mock_get_user_info, mock_upload_service):
        """Test upload when container startup fails"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        # Service layer raises MCPContainerError
        mock_upload_service.side_effect = MCPContainerError("Container failed")

        file_content = b"fake tar content"

        response = client.post(
            "/mcp/upload-image",
            data={"port": 5020},
            files={"file": ("test.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "Container failed" in data["detail"]

    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_docker_unavailable(self, mock_get_user_info, mock_upload_service):
        """Test upload when Docker service is unavailable"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        # Service layer raises MCPContainerError for Docker unavailable
        mock_upload_service.side_effect = MCPContainerError(
            "Docker unavailable")

        file_content = b"fake tar content"

        response = client.post(
            "/mcp/upload-image",
            data={"port": 5020},
            files={"file": ("test.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "Docker unavailable" in data["detail"]


# ---------------------------------------------------------------------------
# Test get_container_logs
# ---------------------------------------------------------------------------


class TestGetContainerLogs:
    """Test endpoint for getting container logs"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_get_container_logs_success(self, mock_container_manager_class, mock_get_user_info):
        """Test successful retrieval of container logs"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.get_container_logs.return_value = "Log line 1\nLog line 2\nLog line 3"

        response = client.get(
            "/mcp/container/container-123/logs?tail=100",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert "Log line 1" in data["logs"]
        mock_container_manager.get_container_logs.assert_called_once_with(
            "container-123", tail=100)

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_get_container_logs_custom_tail(self, mock_container_manager_class, mock_get_user_info):
        """Test getting container logs with custom tail"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.get_container_logs.return_value = "Log line 1"

        response = client.get(
            "/mcp/container/container-123/logs?tail=50",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        mock_container_manager.get_container_logs.assert_called_once_with(
            "container-123", tail=50)

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_get_container_logs_docker_unavailable(self, mock_container_manager_class, mock_get_user_info):
        """Test getting logs when Docker is unavailable"""
        from consts.exceptions import MCPContainerError

        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_container_manager_class.side_effect = MCPContainerError(
            "Docker unavailable")

        response = client.get(
            "/mcp/container/container-123/logs",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "Docker service unavailable" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_get_container_logs_exception(self, mock_container_manager_class, mock_get_user_info):
        """Test getting logs when exception occurs"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.get_container_logs.side_effect = Exception(
            "Unexpected error")

        response = client.get(
            "/mcp/container/container-123/logs",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to get container logs" in data["detail"]


# ---------------------------------------------------------------------------
# Test upload_and_start_mcp_image endpoint with service layer
# ---------------------------------------------------------------------------


class TestUploadMCPImageWithServiceLayer:
    """Test upload_mcp_image endpoint using the new service layer approach"""

    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_success_service_layer(self, mock_get_user_info, mock_upload_service):
        """Test successful upload using service layer"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_upload_service.return_value = {
            "message": "MCP container started successfully from uploaded image",
            "status": "success",
            "service_name": "test-service",
            "mcp_url": "http://localhost:5020/mcp",
            "container_id": "container-123",
            "container_name": "test-service-user1234",
            "host_port": "5020"
        }

        file_content = b"fake tar content"
        response = client.post(
            "/mcp/upload-image",
            data={
                "port": 5020,
                "service_name": "test-service",
                "env_vars": '{"NODE_ENV": "production"}'
            },
            files={"file": ("test.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert data["service_name"] == "test-service"
        assert data["mcp_url"] == "http://localhost:5020/mcp"

        # Verify service layer was called correctly
        mock_upload_service.assert_called_once_with(
            tenant_id="tenant456",
            user_id="user123",
            file_content=file_content,
            filename="test.tar",
            port=5020,
            service_name="test-service",
            env_vars='{"NODE_ENV": "production"}'
        )

    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_auto_service_name(self, mock_get_user_info, mock_upload_service):
        """Test upload with auto-generated service name"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        mock_upload_service.return_value = {
            "message": "MCP container started successfully from uploaded image",
            "status": "success",
            "service_name": "my-image",  # Auto-generated from filename
            "mcp_url": "http://localhost:5020/mcp",
            "container_id": "container-123"
        }

        file_content = b"fake tar content"
        response = client.post(
            "/mcp/upload-image",
            data={"port": 5020},  # No service_name provided
            files={"file": ("my-image.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["service_name"] == "my-image"

        # Verify service was called with None for service_name
        mock_upload_service.assert_called_once_with(
            tenant_id="tenant456",
            user_id="user123",
            file_content=file_content,
            filename="my-image.tar",
            port=5020,
            service_name=None,
            env_vars=None
        )

    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_validation_error_from_service(self, mock_get_user_info, mock_upload_service):
        """Test validation error from service layer"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        # Service layer raises ValueError for invalid file type
        mock_upload_service.side_effect = ValueError(
            "Only .tar files are allowed")

        file_content = b"fake content"
        response = client.post(
            "/mcp/upload-image",
            data={"port": 5020},
            # Wrong file type
            files={"file": ("test.txt", file_content, "text/plain")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "Only .tar files are allowed" in data["detail"]

    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_name_conflict(self, mock_get_user_info, mock_upload_service):
        """Test MCP service name conflict"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        # Service layer raises MCPNameIllegal for name conflict
        mock_upload_service.side_effect = MCPNameIllegal(
            "MCP service name already exists")

        file_content = b"fake tar content"
        response = client.post(
            "/mcp/upload-image",
            data={"port": 5020, "service_name": "existing-service"},
            files={"file": ("test.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.CONFLICT
        data = response.json()
        assert "MCP service name already exists" in data["detail"]

    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_container_error(self, mock_get_user_info, mock_upload_service):
        """Test container startup error"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        # Service layer raises MCPContainerError
        mock_upload_service.side_effect = MCPContainerError("Container failed")

        file_content = b"fake tar content"
        response = client.post(
            "/mcp/upload-image",
            data={"port": 5020},
            files={"file": ("test.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "Container failed" in data["detail"]

    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_docker_unavailable(self, mock_get_user_info, mock_upload_service):
        """Test Docker service unavailable"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        # Service layer raises MCPContainerError for Docker unavailable
        mock_upload_service.side_effect = MCPContainerError(
            "Docker unavailable")

        file_content = b"fake tar content"
        response = client.post(
            "/mcp/upload-image",
            data={"port": 5020},
            files={"file": ("test.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "Docker unavailable" in data["detail"]

    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_general_exception(self, mock_get_user_info, mock_upload_service):
        """Test general exception handling"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        # Service layer raises unexpected exception
        mock_upload_service.side_effect = Exception("Unexpected error")

        file_content = b"fake tar content"
        response = client.post(
            "/mcp/upload-image",
            data={"port": 5020},
            files={"file": ("test.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to upload and start MCP container" in data["detail"]
        assert "Unexpected error" in data["detail"]


# ---------------------------------------------------------------------------
# Additional test cases for upload_mcp_image validation
# ---------------------------------------------------------------------------


class TestUploadMCPImageValidationAdditional:
    """Additional test cases for upload_mcp_image endpoint validation"""

    def test_upload_mcp_image_invalid_port_range_fastapi_validation(self):
        """Test upload with invalid port range using FastAPI native validation"""
        file_content = b"fake tar content"

        # Test port <= 0 - should fail FastAPI validation
        response = client.post(
            "/mcp/upload-image",
            data={"port": 0},  # Invalid port
            files={"file": ("test.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )
        # FastAPI validation error
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        data = response.json()
        assert "port" in str(data["detail"]).lower()

        # Test port > 65535 - should fail FastAPI validation
        response = client.post(
            "/mcp/upload-image",
            data={"port": 70000},  # Invalid port
            files={"file": ("test.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )
        # FastAPI validation error
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        data = response.json()
        assert "port" in str(data["detail"]).lower()

    @patch('apps.remote_mcp_app.upload_and_start_mcp_image')
    @patch('apps.remote_mcp_app.get_current_user_info')
    def test_upload_mcp_image_env_vars_validation_in_service(self, mock_get_user_info, mock_upload_service):
        """Test environment variables validation now handled in service layer"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")

        # Test with array instead of object - now handled in service layer
        mock_upload_service.side_effect = ValueError(
            "Invalid environment variables format: Environment variables must be a JSON object")

        file_content = b"fake tar content"
        response = client.post(
            "/mcp/upload-image",
            data={
                "port": 5020,
                "env_vars": '["VAR1", "VAR2"]'  # Array instead of object
            },
            files={"file": ("test.tar", file_content,
                            "application/octet-stream")},
            headers={"Authorization": "Bearer test_token"}
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "Invalid environment variables format" in data["detail"]
        assert "Environment variables must be a JSON object" in data["detail"]


class MockMCPUpdateRequest:
    """Mock MCPUpdateRequest for testing"""

    def __init__(self, current_service_name, current_mcp_url, new_service_name, new_mcp_url):
        self.current_service_name = current_service_name
        self.current_mcp_url = current_mcp_url
        self.new_service_name = new_service_name
        self.new_mcp_url = new_mcp_url


class TestUpdateRemoteProxy:
    """Test endpoint for updating remote MCP servers"""

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_remote_mcp_server_list')
    def test_update_remote_proxy_success(self, mock_update_server, mock_get_user_info):
        """Test successful update of remote MCP proxy"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_update_server.return_value = None  # No exception means success

        update_data = MockMCPUpdateRequest(
            current_service_name="old_service",
            current_mcp_url="http://old.url",
            new_service_name="new_service",
            new_mcp_url="http://new.url"
        )

        response = client.put(
            "/mcp/update",
            json={
                "current_service_name": "old_service",
                "current_mcp_url": "http://old.url",
                "new_service_name": "new_service",
                "new_mcp_url": "http://new.url"
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert "Successfully updated remote MCP proxy" in data["message"]

        mock_get_user_info.assert_called_once()
        # Verify the service was called with correct tenant_id and user_id
        # The update_data parameter is automatically parsed by FastAPI from the JSON request
        mock_update_server.assert_called_once()
        call_kwargs = mock_update_server.call_args[1]
        assert call_kwargs["tenant_id"] == "tenant456"
        assert call_kwargs["user_id"] == "user123"
        # Verify that update_data parameter exists and is not None
        assert "update_data" in call_kwargs
        assert call_kwargs["update_data"] is not None

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_remote_mcp_server_list')
    def test_update_remote_proxy_with_tenant_id_param(self, mock_update_server, mock_get_user_info):
        """Test updating remote MCP proxy with explicit tenant_id parameter"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_update_server.return_value = None

        response = client.put(
            "/mcp/update",
            params={"tenant_id": "explicit_tenant789"},
            json={
                "current_service_name": "old_service",
                "current_mcp_url": "http://old.url",
                "new_service_name": "new_service",
                "new_mcp_url": "http://new.url"
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        # Verify that explicit tenant_id is used
        mock_update_server.assert_called_once()
        call_kwargs = mock_update_server.call_args[1]
        assert call_kwargs["tenant_id"] == "explicit_tenant789"
        assert call_kwargs["user_id"] == "user123"

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_remote_mcp_server_list')
    def test_update_remote_proxy_name_conflict(self, mock_update_server, mock_get_user_info):
        """Test update MCP proxy with name conflict"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_update_server.side_effect = MCPNameIllegal(
            "New MCP name already exists")

        response = client.put(
            "/mcp/update",
            json={
                "current_service_name": "old_service",
                "current_mcp_url": "http://old.url",
                "new_service_name": "existing_service",
                "new_mcp_url": "http://new.url"
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.CONFLICT
        data = response.json()
        assert "New MCP name already exists" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_remote_mcp_server_list')
    def test_update_remote_proxy_connection_failed(self, mock_update_server, mock_get_user_info):
        """Test update MCP proxy with connection failure"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_update_server.side_effect = MCPConnectionError(
            "New MCP server connection failed")

        response = client.put(
            "/mcp/update",
            json={
                "current_service_name": "old_service",
                "current_mcp_url": "http://old.url",
                "new_service_name": "new_service",
                "new_mcp_url": "http://unreachable.url"
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "New MCP server connection failed" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_remote_mcp_server_list')
    def test_update_remote_proxy_current_name_not_exist(self, mock_update_server, mock_get_user_info):
        """Test update MCP proxy when current name doesn't exist"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_update_server.side_effect = MCPNameIllegal(
            "MCP name does not exist")

        response = client.put(
            "/mcp/update",
            json={
                "current_service_name": "nonexistent_service",
                "current_mcp_url": "http://old.url",
                "new_service_name": "new_service",
                "new_mcp_url": "http://new.url"
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.CONFLICT
        data = response.json()
        assert "MCP name does not exist" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_remote_mcp_server_list')
    def test_update_remote_proxy_database_error(self, mock_update_server, mock_get_user_info):
        """Test update MCP proxy with database error"""
        from sqlalchemy.exc import SQLAlchemyError

        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_update_server.side_effect = SQLAlchemyError(
            "Database connection failed")

        response = client.put(
            "/mcp/update",
            json={
                "current_service_name": "old_service",
                "current_mcp_url": "http://old.url",
                "new_service_name": "new_service",
                "new_mcp_url": "http://new.url"
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to update remote MCP proxy" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_remote_mcp_server_list')
    def test_update_remote_proxy_same_name_and_url(self, mock_update_server, mock_get_user_info):
        """Test update MCP proxy with same name and URL (no-op update)"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_update_server.return_value = None

        response = client.put(
            "/mcp/update",
            json={
                "current_service_name": "same_service",
                "current_mcp_url": "http://same.url",
                "new_service_name": "same_service",
                "new_mcp_url": "http://same.url"
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"

    def test_update_remote_proxy_invalid_request_data(self):
        """Test update MCP proxy with invalid request data"""
        # Missing required fields
        response = client.put(
            "/mcp/update",
            json={
                "current_service_name": "old_service"
                # Missing other required fields
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @patch('apps.remote_mcp_app.get_current_user_info')
    @patch('apps.remote_mcp_app.update_remote_mcp_server_list')
    def test_update_remote_proxy_with_special_characters(self, mock_update_server, mock_get_user_info):
        """Test update MCP proxy with special characters in names and URLs"""
        mock_get_user_info.return_value = ("user123", "tenant456", "en")
        mock_update_server.return_value = None

        response = client.put(
            "/mcp/update",
            json={
                "current_service_name": "old-service_123",
                "current_mcp_url": "http://old-server.com:8080/path",
                "new_service_name": "new-service_456",
                "new_mcp_url": "http://new-server.com:9090/api"
            },
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"


if __name__ == "__main__":
    pytest.main([__file__])
