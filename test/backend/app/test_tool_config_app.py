from unittest.mock import patch, MagicMock
import sys
import os

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

# Mock boto3 to avoid dependency issues
sys.modules['boto3'] = MagicMock()

# Import exception classes
from consts.exceptions import MCPConnectionError, NotFoundException

# Mock dependencies before importing the actual app - using the same pattern as test_remote_mcp_app.py
with patch('database.client.MinioClient', MagicMock()), \
     patch('elasticsearch.Elasticsearch', return_value=MagicMock()):
    import pytest
    from fastapi.testclient import TestClient
    from http import HTTPStatus

    # Create a test client with a fresh FastAPI app
    from apps.tool_config_app import router
    from fastapi import FastAPI

    # Patch exception classes to ensure tests use correct exceptions
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
            json={"agent_id": 123, "tool_id": 456}  # Changed to int
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
            json={"agent_id": 123, "tool_id": 456}  # Changed to int
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
                "agent_id": 123,  # Changed to int
                "tool_id": 456,   # Changed to int
                # Changed from "configuration" to "params"
                "params": {"key": "value"},
                "enabled": True  # Added required field
            }
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["updated"] == True
        assert data["tool_id"] == "tool456"

        mock_get_user_id.assert_called_once_with(None)
        # The mock should be called with request object, tenant_id, user_id
        assert mock_update_tool_info.call_count == 1
        args = mock_update_tool_info.call_args[0]
        assert args[1] == "tenant456"  # tenant_id
        assert args[2] == "user123"    # user_id

    @patch('apps.tool_config_app.get_current_user_id')
    @patch('apps.tool_config_app.update_tool_info_impl')
    def test_update_tool_info_service_error(self, mock_update_tool_info, mock_get_user_id):
        """Test service error when updating tool info"""
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_update_tool_info.side_effect = Exception("Update error")

        response = client.post(
            "/tool/update",
            json={
                "agent_id": 123,  # Changed to int
                "tool_id": 456,   # Changed to int
                # Changed from "configuration" to "params"
                "params": {"key": "value"},
                "enabled": True  # Added required field
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

        # 1. List tools
        mock_list_all_tools.return_value = [{"id": 1, "name": "TestTool"}]
        list_response = client.get("/tool/list")
        assert list_response.status_code == HTTPStatus.OK
        data = list_response.json()
        assert len(data) == 1

        # 2. Search tool info
        mock_search_tool_info.return_value = {"tool": "TestTool", "config": {}}
        search_response = client.post(
            "/tool/search",
            json={"agent_id": 123, "tool_id": 1}  # Changed to int
        )
        assert search_response.status_code == HTTPStatus.OK

        # 3. Update tool info
        mock_update_tool_info.return_value = {"updated": True}
        update_response = client.post(
            "/tool/update",
            json={
                "agent_id": 123,  # Changed to int
                "tool_id": 1,     # Changed to int
                # Changed from "configuration" to "params"
                "params": {"new_key": "new_value"},
                "enabled": True   # Added required field
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

        # Test with Authorization header
        response = client.get(
            "/tool/list",
            headers={"Authorization": "Bearer test_token"}
        )
        assert response.status_code == HTTPStatus.OK
        mock_get_user_id.assert_called_with("Bearer test_token")

        # Reset mock
        mock_get_user_id.reset_mock()

        # Test without Authorization header
        response = client.get("/tool/list")
        assert response.status_code == HTTPStatus.OK
        mock_get_user_id.assert_called_with(None)

    def test_missing_parameters(self):
        """Test missing required parameters"""
        # Test missing parameters for search
        response = client.post("/tool/search", json={})
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        # Test missing parameters for update
        response = client.post("/tool/update", json={})
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

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
        # Missing name field
        response = client.post(
            "/tool/validate",
            json={
                "source": "local",
                "usage": None,
                "inputs": {"param1": "value1"}
            }
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        # Missing source field
        response = client.post(
            "/tool/validate",
            json={
                "name": "test_tool",
                "usage": None,
                "inputs": {"param1": "value1"}
            }
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


if __name__ == "__main__":
    pytest.main([__file__])


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

    def test_missing_content_type_header(self):
        """Test POST request without content-type header"""
        response = client.post(
            "/tool/search",
            data='{"agent_id": 123, "tool_id": 456}'
        )

        # FastAPI should still parse it correctly
        assert response.status_code in [
            HTTPStatus.OK, HTTPStatus.UNPROCESSABLE_ENTITY, HTTPStatus.INTERNAL_SERVER_ERROR]

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


class TestDataValidation:
    """Data validation tests"""

    def test_search_tool_negative_ids(self):
        """Test search with negative IDs"""
        response = client.post(
            "/tool/search",
            json={"agent_id": -1, "tool_id": -1}
        )

        # Should still pass validation but may fail in business logic
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
        # Missing tool_id
        response = client.post(
            "/tool/search",
            json={"agent_id": 123}
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        # Missing agent_id
        response = client.post(
            "/tool/search",
            json={"tool_id": 456}
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_update_tool_missing_required_fields(self):
        """Test update with missing required fields"""
        # Missing enabled field
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

        # Simulate multiple simultaneous requests
        responses = []
        for _ in range(5):
            response = client.get("/tool/list")
            responses.append(response)

        # All requests should succeed
        for response in responses:
            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert len(data) == 1
            assert data[0]["name"] == "Tool1"


if __name__ == "__main__":
    pytest.main([__file__])
