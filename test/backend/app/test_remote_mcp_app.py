from unittest.mock import patch, MagicMock
import sys
import os

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
sys.modules['boto3'] = MagicMock()

# Import exception classes
from consts.exceptions import MCPConnectionError, MCPNameIllegal

# Import the modules we need with MinioClient and Elasticsearch mocked  
with patch('database.client.MinioClient', MagicMock()), \
     patch('elasticsearch.Elasticsearch', return_value=MagicMock()):
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


if __name__ == "__main__":
    pytest.main([__file__])
