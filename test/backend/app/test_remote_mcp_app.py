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
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.minio_client', minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Import exception classes
from consts.exceptions import MCPConnectionError, MCPNameIllegal

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
        mock_get_tools.side_effect = MCPConnectionError("MCP connection failed")

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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_remote_proxy_success(self, mock_add_server, mock_get_user_id):
        """Test successful addition of remote MCP proxy"""
        mock_get_user_id.return_value = ("user123", "tenant456")
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

        mock_get_user_id.assert_called_once_with("Bearer test_token")
        mock_add_server.assert_called_once_with(
            tenant_id="tenant456",
            user_id="user123",
            remote_mcp_server="http://test.com",
            remote_mcp_server_name="test_service"
        )

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_remote_proxy_name_exists(self, mock_add_server, mock_get_user_id):
        """Test adding MCP server with existing name"""
        mock_get_user_id.return_value = ("user123", "tenant456")
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_remote_proxy_connection_failed(self, mock_add_server, mock_get_user_id):
        """Test MCP connection failure"""
        mock_get_user_id.return_value = ("user123", "tenant456")
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_remote_proxy_database_error(self, mock_add_server, mock_get_user_id):
        """Test database error - should be handled as general exception"""
        from sqlalchemy.exc import SQLAlchemyError
        
        mock_get_user_id.return_value = ("user123", "tenant456")
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.delete_remote_mcp_server_list')
    def test_delete_remote_proxy_success(self, mock_delete_server, mock_get_user_id):
        """Test successful deletion of remote MCP proxy"""
        mock_get_user_id.return_value = ("user123", "tenant456")
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

        mock_get_user_id.assert_called_once_with("Bearer test_token")
        mock_delete_server.assert_called_once_with(
            tenant_id="tenant456",
            user_id="user123",
            remote_mcp_server="http://test.com",
            remote_mcp_server_name="test_service"
        )

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.delete_remote_mcp_server_list')
    def test_delete_remote_proxy_database_error(self, mock_delete_server, mock_get_user_id):
        """Test database error during deletion - should be handled as general exception"""
        from sqlalchemy.exc import SQLAlchemyError
        
        mock_get_user_id.return_value = ("user123", "tenant456")
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list')
    def test_get_remote_proxies_success(self, mock_get_list, mock_get_user_id):
        """Test successful retrieval of remote MCP proxy list"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_server_list = [
            {
                "remote_mcp_server_name": "server1",
                "remote_mcp_server": "http://server1.com",
                "status": True
            },
            {
                "remote_mcp_server_name": "server2",
                "remote_mcp_server": "http://server2.com",
                "status": False
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

        mock_get_user_id.assert_called_once_with("Bearer test_token")
        mock_get_list.assert_called_once_with(tenant_id="tenant456")

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list')
    def test_get_remote_proxies_error(self, mock_get_list, mock_get_user_id):
        """Test error when getting list"""
        mock_get_user_id.return_value = ("user123", "tenant456")
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.check_mcp_health_and_update_db')
    def test_check_mcp_health_success(self, mock_health_check, mock_get_user_id):
        """Test successful health check"""
        mock_get_user_id.return_value = ("user123", "tenant456")
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

        mock_get_user_id.assert_called_once_with("Bearer test_token")
        mock_health_check.assert_called_once_with(
            "http://test.com", "test_service", "tenant456", "user123"
        )

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.check_mcp_health_and_update_db')
    def test_check_mcp_health_connection_error(self, mock_health_check, mock_get_user_id):
        """Test MCP connection error during health check"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_health_check.side_effect = MCPConnectionError("MCP connection failed")

        response = client.get(
            "/mcp/healthcheck",
            params={"mcp_url": "http://unreachable.com",
                    "service_name": "test_service"},
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "MCP connection failed" in data["detail"]

        mock_get_user_id.assert_called_once_with("Bearer test_token")
        mock_health_check.assert_called_once_with(
            "http://unreachable.com", "test_service", "tenant456", "user123"
        )

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.check_mcp_health_and_update_db')
    def test_check_mcp_health_database_error(self, mock_health_check, mock_get_user_id):
        """Test database error during health check - should be handled as general exception"""
        from sqlalchemy.exc import SQLAlchemyError
        
        mock_get_user_id.return_value = ("user123", "tenant456")
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list')
    @patch('apps.remote_mcp_app.delete_remote_mcp_server_list')
    def test_full_lifecycle(self, mock_delete, mock_get_list, mock_add, mock_get_user_id):
        """Test complete MCP server lifecycle"""
        mock_get_user_id.return_value = ("user123", "tenant456")

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
             "status": True}
        ]
        list_response = client.get(
            "/mcp/list",
            headers={"Authorization": "Bearer test_token"}
        )
        assert list_response.status_code == HTTPStatus.OK
        data = list_response.json()
        assert len(data["remote_mcp_server_list"]) == 1

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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.get_remote_mcp_server_list')
    def test_authorization_header_handling(self, mock_get_list, mock_get_user_id):
        """Test authorization header handling"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_get_list.return_value = []  # Mock empty list

        # Test case without Authorization header
        response = client.get("/mcp/list")
        # Should return OK with empty list
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert "remote_mcp_server_list" in data

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_unexpected_error_handling(self, mock_add_server, mock_get_user_id):
        """Test unexpected error handling"""
        mock_get_user_id.return_value = ("user123", "tenant456")
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_invalid_url_format(self, mock_add_server, mock_get_user_id):
        """Test invalid URL format with valid authentication"""
        mock_get_user_id.return_value = ("user123", "tenant456")
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_mcp_from_config_success(self, mock_add_server, mock_container_manager_class, mock_get_user_id):
        """Test successful addition of MCP server from config"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_mcp_from_config_multiple_servers(self, mock_add_server, mock_container_manager_class, mock_get_user_id):
        """Test adding multiple MCP servers from config"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_add_mcp_from_config_missing_command(self, mock_container_manager_class, mock_get_user_id):
        """Test adding MCP server with missing command"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_add_mcp_from_config_empty_command(self, mock_container_manager_class, mock_get_user_id):
        """Test adding MCP server with empty command string (covers line 189-191)"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_add_mcp_from_config_missing_port(self, mock_container_manager_class, mock_get_user_id):
        """Test adding MCP server with missing port"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_mcp_from_config_name_exists(self, mock_add_server, mock_container_manager_class, mock_get_user_id):
        """Test adding MCP server when name already exists"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.start_mcp_container = AsyncMock(return_value={
            "container_id": "container-123",
            "mcp_url": "http://localhost:5020/mcp",
            "host_port": "5020",
            "status": "started",
            "container_name": "test-service-user1234"
        })
        mock_container_manager.stop_mcp_container = AsyncMock(return_value=True)
        
        mock_add_server.side_effect = MCPNameIllegal("MCP name already exists")

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
        mock_container_manager.stop_mcp_container.assert_called_once_with("container-123")

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_mcp_from_config_name_exists_stop_fails(self, mock_add_server, mock_container_manager_class, mock_get_user_id):
        """Test adding MCP server when name exists and stopping container fails (covers line 236)"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.start_mcp_container = AsyncMock(return_value={
            "container_id": "container-123",
            "mcp_url": "http://localhost:5020/mcp",
            "host_port": "5020",
            "status": "started",
            "container_name": "test-service-user1234"
        })
        # stop_mcp_container raises exception, should be silently caught
        mock_container_manager.stop_mcp_container = AsyncMock(side_effect=Exception("Stop failed"))
        
        mock_add_server.side_effect = MCPNameIllegal("MCP name already exists")

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
        # Verify stop was attempted even though it failed
        mock_container_manager.stop_mcp_container.assert_called_once_with("container-123")

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_add_mcp_from_config_container_error(self, mock_container_manager_class, mock_get_user_id):
        """Test adding MCP server when container startup fails"""
        from consts.exceptions import MCPContainerError
        
        mock_get_user_id.return_value = ("user123", "tenant456")
        
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.start_mcp_container = AsyncMock(side_effect=MCPContainerError("Container failed"))

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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_add_mcp_from_config_unexpected_error_in_loop(self, mock_container_manager_class, mock_get_user_id):
        """Test adding MCP server when unexpected exception occurs in loop (covers line 253-255)"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        # Raise a non-MCPContainerError exception to trigger the general Exception handler
        mock_container_manager.start_mcp_container = AsyncMock(side_effect=ValueError("Unexpected error"))

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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_add_mcp_from_config_all_fail(self, mock_container_manager_class, mock_get_user_id):
        """Test adding MCP servers when all fail"""
        from consts.exceptions import MCPContainerError
        
        mock_get_user_id.return_value = ("user123", "tenant456")
        
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.start_mcp_container = AsyncMock(side_effect=MCPContainerError("Container failed"))

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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_add_mcp_from_config_docker_unavailable(self, mock_container_manager_class, mock_get_user_id):
        """Test adding MCP server when Docker is unavailable"""
        from consts.exceptions import MCPContainerError
        
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_container_manager_class.side_effect = MCPContainerError("Docker unavailable")

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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    @patch('apps.remote_mcp_app.add_remote_mcp_server_list')
    def test_add_mcp_from_config_with_custom_image(self, mock_add_server, mock_container_manager_class, mock_get_user_id):
        """Test adding MCP server with custom Docker image"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    def test_add_mcp_from_config_outer_exception(self, mock_get_user_id):
        """Test adding MCP server when exception occurs outside loop (covers line 275-277)"""
        # Make get_current_user_id raise an exception to trigger outer exception handler
        mock_get_user_id.side_effect = RuntimeError("Failed to get user ID")

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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_stop_mcp_container_success(self, mock_container_manager_class, mock_get_user_id):
        """Test successful stopping of MCP container"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.stop_mcp_container = AsyncMock(return_value=True)

        response = client.delete(
            "/mcp/container/container-123",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert "stopped successfully" in data["message"]
        mock_container_manager.stop_mcp_container.assert_called_once_with("container-123")

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_stop_mcp_container_not_found(self, mock_container_manager_class, mock_get_user_id):
        """Test stopping non-existent container"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.stop_mcp_container = AsyncMock(return_value=False)

        response = client.delete(
            "/mcp/container/non-existent",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.NOT_FOUND
        data = response.json()
        assert data["status"] == "error"
        assert "not found" in data["message"]

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_stop_mcp_container_docker_unavailable(self, mock_container_manager_class, mock_get_user_id):
        """Test stopping container when Docker is unavailable"""
        from consts.exceptions import MCPContainerError
        
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_container_manager_class.side_effect = MCPContainerError("Docker unavailable")

        response = client.delete(
            "/mcp/container/container-123",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "Docker service unavailable" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_stop_mcp_container_exception(self, mock_container_manager_class, mock_get_user_id):
        """Test stopping container when exception occurs"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.stop_mcp_container = AsyncMock(side_effect=Exception("Unexpected error"))

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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_list_mcp_containers_success(self, mock_container_manager_class, mock_get_user_id):
        """Test successful listing of MCP containers"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.list_mcp_containers.return_value = [
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

        response = client.get(
            "/mcp/containers",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == "success"
        assert len(data["containers"]) == 2
        mock_container_manager.list_mcp_containers.assert_called_once_with(tenant_id="tenant456")

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_list_mcp_containers_empty(self, mock_container_manager_class, mock_get_user_id):
        """Test listing containers when none exist"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
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

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_list_mcp_containers_docker_unavailable(self, mock_container_manager_class, mock_get_user_id):
        """Test listing containers when Docker is unavailable"""
        from consts.exceptions import MCPContainerError
        
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_container_manager_class.side_effect = MCPContainerError("Docker unavailable")

        response = client.get(
            "/mcp/containers",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "Docker service unavailable" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_list_mcp_containers_exception(self, mock_container_manager_class, mock_get_user_id):
        """Test listing containers when exception occurs"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.list_mcp_containers.side_effect = Exception("Unexpected error")

        response = client.get(
            "/mcp/containers",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to list containers" in data["detail"]


# ---------------------------------------------------------------------------
# Test get_container_logs
# ---------------------------------------------------------------------------


class TestGetContainerLogs:
    """Test endpoint for getting container logs"""

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_get_container_logs_success(self, mock_container_manager_class, mock_get_user_id):
        """Test successful retrieval of container logs"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
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
        mock_container_manager.get_container_logs.assert_called_once_with("container-123", tail=100)

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_get_container_logs_custom_tail(self, mock_container_manager_class, mock_get_user_id):
        """Test getting container logs with custom tail"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.get_container_logs.return_value = "Log line 1"

        response = client.get(
            "/mcp/container/container-123/logs?tail=50",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        mock_container_manager.get_container_logs.assert_called_once_with("container-123", tail=50)

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_get_container_logs_docker_unavailable(self, mock_container_manager_class, mock_get_user_id):
        """Test getting logs when Docker is unavailable"""
        from consts.exceptions import MCPContainerError
        
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_container_manager_class.side_effect = MCPContainerError("Docker unavailable")

        response = client.get(
            "/mcp/container/container-123/logs",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert "Docker service unavailable" in data["detail"]

    @patch('apps.remote_mcp_app.get_current_user_id')
    @patch('apps.remote_mcp_app.MCPContainerManager')
    def test_get_container_logs_exception(self, mock_container_manager_class, mock_get_user_id):
        """Test getting logs when exception occurs"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.get_container_logs.side_effect = Exception("Unexpected error")

        response = client.get(
            "/mcp/container/container-123/logs",
            headers={"Authorization": "Bearer test_token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to get container logs" in data["detail"]


if __name__ == "__main__":
    pytest.main([__file__])
